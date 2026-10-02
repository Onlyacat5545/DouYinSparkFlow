"""Offline regression tests; run with python -m unittest discover -s tests."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_functions():
    # Avoid importing application configuration, cookies, or browser dependencies.
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "core/tasks.py").read_text()
    )
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"scroll_and_select_user", "capture_page_diagnostics"}
    ]
    namespace = {
        "config": {"browserTimeout": 120000, "friendListTimeout": 2000},
        "logger": Mock(),
        "matchMode": "nickname",
        "time": SimpleNamespace(sleep=lambda _: None, time_ns=lambda: 123),
        "Path": Path,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "tasks.py", "exec"),
         namespace)
    return namespace


class Locator:
    def __init__(self, page, kind, first=False, visible_only=False):
        self.page = page
        self.kind = kind
        self.is_first = first
        self.visible_only = visible_only

    @property
    def first(self):
        return Locator(self.page, self.kind, True, self.visible_only)

    def filter(self, *, visible):
        return Locator(self.page, self.kind, self.is_first, visible)

    def wait_for(self, *, state, timeout):
        self.page.events.append(("wait", self.kind, state))
        ready = self.page.tab_ready if self.kind == "tab" else self.page.rows_ready
        if self.kind == "loading":
            if not self.visible_only:
                raise AssertionError("Hidden loading indicators must be excluded")
            ready = self.page.loading_done
        if ready - self.page.now > timeout / 1000:
            raise TimeoutError(self.kind)
        self.page.now = max(self.page.now, ready)

    def click(self, **kwargs):
        if self.kind == "tab" and self.page.duplicate_tabs and not self.is_first:
            raise RuntimeError("strict mode violation")
        self.page.events.append(("click", self.kind))

    def all(self):
        if self.page.now < self.page.rows_ready:
            raise AssertionError("Scanned before friend rows were ready")
        if self.page.now < self.page.loading_done:
            raise AssertionError("Scanned while loading")
        self.page.events.append(("scan", self.kind))
        return [self]

    def locator(self, selector):
        return self

    def inner_text(self):
        return "Alice"

    def count(self):
        if self.kind == "root":
            return 1
        if self.kind == "tab":
            return int(self.page.now >= self.page.tab_ready)
        return 0

    def is_visible(self):
        return self.kind != "root"


class Page:
    url = "https://example.test/chat"

    def __init__(self, tab_ready=0, rows_ready=0, loading_done=0,
                 duplicate_tabs=False):
        self.now = 0
        self.tab_ready = tab_ready
        self.rows_ready = rows_ready
        self.loading_done = loading_done
        self.duplicate_tabs = duplicate_tabs
        self.events = []
        self.screenshot = Mock()

    def locator(self, selector):
        if selector == "#sub-app":
            kind = "root"
        elif "semi-list-item-body" in selector:
            kind = "row"
        elif "semi-spin" in selector:
            kind = "loading"
        elif "no-more-tip" in selector:
            kind = "end"
        else:
            kind = "tab"
        return Locator(self, kind)


class FriendsReadinessTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_functions()

    def run_scan(self, page):
        return list(self.ns["scroll_and_select_user"](
            page, "test-account", ["Alice"], {}
        ))

    def test_delayed_tab_with_invisible_root_is_usable(self):
        page = Page(tab_ready=4, rows_ready=5)
        self.assertFalse(page.locator("#sub-app").is_visible())
        self.assertEqual(self.run_scan(page), ["Alice"])
        self.assertGreaterEqual(page.now, 5)

    def test_delayed_rows_and_loading_finish_before_scan(self):
        page = Page(rows_ready=8, loading_done=12)
        self.assertEqual(self.run_scan(page), ["Alice"])
        self.assertGreaterEqual(page.now, 12)
        activation = page.events.index(("click", "row"))
        scan = page.events.index(("scan", "row"))
        self.assertLess(activation, scan)

    def test_missing_rows_raise_instead_of_reporting_completion(self):
        page = Page(rows_ready=121)
        with self.assertRaises(TimeoutError):
            self.run_scan(page)
        self.assertNotIn(("scan", "row"), page.events)

    def test_duplicate_tabs_fail_without_clicking_arbitrary_first(self):
        page = Page(duplicate_tabs=True)
        with self.assertRaisesRegex(RuntimeError, "strict mode"):
            self.run_scan(page)
        self.assertNotIn(("click", "tab"), page.events)

    def test_loading_timeout_does_not_scan(self):
        page = Page(loading_done=121)
        with self.assertRaises(TimeoutError):
            self.run_scan(page)
        self.assertNotIn(("scan", "row"), page.events)

    def test_diagnostics_record_url_root_and_screenshot(self):
        page = Page()
        with patch.object(Path, "mkdir"):
            self.ns["capture_page_diagnostics"](page)
        page.screenshot.assert_called_once_with(
            path=str(Path("logs") / "failure-123.png"), timeout=5000
        )
        message = self.ns["logger"].error.call_args_list[0].args[0]
        self.assertIn(page.url, message)
        self.assertIn("False", message)

    def test_diagnostic_failures_are_best_effort(self):
        page = Page()
        page.locator = Mock(side_effect=RuntimeError("page closed"))
        page.screenshot.side_effect = RuntimeError("page closed")
        with patch.object(Path, "mkdir"):
            self.ns["capture_page_diagnostics"](page)
        self.assertEqual(self.ns["logger"].warning.call_count, 2)


if __name__ == "__main__":
    unittest.main()

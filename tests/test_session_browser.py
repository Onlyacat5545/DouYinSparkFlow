"""Real Chromium tests. Run: python -m unittest discover -s tests -v."""
import time
import unittest
from playwright.sync_api import sync_playwright, TimeoutError
from core.session import AuthenticationRequired, wait_for_authenticated_tab


class SessionBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_login_screen_raises_actionable_error(self):
        self.page.set_content(
            "<div>扫码登录</div><div>验证码登录</div><button>登录</button>"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(AuthenticationRequired, "COOKIES_<unique_id>"):
            wait_for_authenticated_tab(self.page, "#friends", 5000, 150)
        self.assertLess(time.monotonic() - started, 3)

    def test_hidden_login_template_does_not_block(self):
        self.page.set_content(
            '<div hidden>扫码登录</div><button id="friends">好友</button>'
        )
        wait_for_authenticated_tab(self.page, "#friends", 1000)

    def test_delayed_tab_under_boxless_root(self):
        self.page.set_content('<div id="sub-app" style="display:contents"></div>')
        self.page.evaluate("""() => setTimeout(() => {
            document.querySelector('#sub-app').innerHTML =
                '<button id="friends">好友</button>';
        }, 200)""")
        wait_for_authenticated_tab(self.page, "#friends", 3000)
        self.assertFalse(self.page.locator("#sub-app").is_visible())
        self.assertTrue(self.page.locator("#friends").is_visible())

    def test_transient_login_can_resolve_to_authenticated_page(self):
        self.page.set_content('<div id="login">扫码登录</div>')
        self.page.evaluate("""() => setTimeout(() => {
            document.body.innerHTML = '<button id="friends">好友</button>';
        }, 200)""")
        wait_for_authenticated_tab(self.page, "#friends", 3000, 1000)

    def test_unknown_page_times_out_without_claiming_cookie_failure(self):
        self.page.set_content("<div>Loading...</div>")
        with self.assertRaises(TimeoutError):
            wait_for_authenticated_tab(self.page, "#friends", 200)

    def test_duplicate_tabs_remain_strict(self):
        self.page.set_content('<button class="friends">好友</button>' * 2)
        wait_for_authenticated_tab(self.page, ".friends", 1000)
        with self.assertRaisesRegex(Exception, "strict mode"):
            self.page.locator(".friends").click()


if __name__ == "__main__":
    unittest.main()

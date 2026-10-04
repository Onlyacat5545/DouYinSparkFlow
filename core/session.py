"""Detect unauthenticated Creator Center sessions before scanning friends."""
import re
import time
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class AuthenticationRequired(RuntimeError):
    """The supplied cookies did not establish a Creator Center session."""


def wait_for_authenticated_tab(page, selector, timeout, login_grace_ms=2000):
    """Wait for the tab or a persistent visible login screen.

    Login text may appear briefly while an existing session initializes. Allow a
    short grace period; hidden login templates never count as a login screen.
    """
    tab = page.locator(selector)
    login = page.get_by_text(
        re.compile(r"^(扫码登录|验证码登录|密码登录)$")
    ).filter(visible=True)
    deadline = time.monotonic() + timeout / 1000 if timeout else float("inf")
    login_since = None
    while True:
        now = time.monotonic()
        if login.count():
            if login_since is None:
                login_since = now
            if (now - login_since) * 1000 >= login_grace_ms:
                raise AuthenticationRequired(
                    "Douyin Creator Center is showing its login page. "
                    "The configured cookies were not accepted. Sign in again at "
                    "https://creator.douyin.com/, export the authenticated cookies, "
                    "and replace COOKIES_<unique_id> in GitHub Settings > "
                    "Environments > user-data > Environment secrets. "
                    "Do not paste cookies into logs, issues, or chat."
                )
        else:
            login_since = None
            if tab.first.is_visible():
                return
        if now >= deadline:
            raise PlaywrightTimeoutError(
                "Friends tab did not become visible and no persistent login "
                "screen was detected; inspect the saved failure screenshot."
            )
        page.wait_for_timeout(min(100, max(1, (deadline - now) * 1000)))

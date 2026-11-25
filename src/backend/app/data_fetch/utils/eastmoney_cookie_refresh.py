"""Fetch a fresh Eastmoney cookie and print it as a single Cookie header value.

Wire this into AkShare as the automatic refresh hook:

  AKSHARE_EASTMONEY_COOKIE_REFRESH_COMMAND="python /abs/path/to/eastmoney_cookie_refresh.py"

AkShare runs this after an Eastmoney request fails on a session/cookie error, reads
stdout, caches it at ~/.cache/akshare/eastmoney_cookie.txt and retries the request.
Only the cookie goes to stdout; diagnostics go to stderr so the header stays parseable.

The tracking cookies are set by Eastmoney's own page scripts, so a plain HTTP request
never receives them and a browser session is required.
"""

from __future__ import annotations

import argparse
import sys
import time

# Eastmoney only sets these once its page scripts have run.
_REQUIRED_COOKIES = ("qgqp_b_id", "st_si", "nid18")
_ENTRY_URL = "https://quote.eastmoney.com/"
_CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_SETTLE_SECONDS = 6.0


def _emit(message: str, quiet: bool) -> None:
    if not quiet:
        sys.stderr.write(f"{message}\n")
        sys.stderr.flush()


def _cookie_from(driver) -> str:
    jar = {c["name"]: c["value"] for c in driver.get_cookies()}
    if not all(jar.get(name) for name in _REQUIRED_COOKIES):
        return ""
    return "; ".join(f"{name}={value}" for name, value in jar.items() if name and value)


def collect_cookie(
    settle: float = _SETTLE_SECONDS, headless: bool = True, quiet: bool = False
) -> str:
    """Drive a browser through an Eastmoney page until the tracking cookies appear."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.binary_location = _CHROME_BINARY
    # Return at DOMContentLoaded: quote.eastmoney.com pulls enough ad and analytics
    # subresources that a full-load wait times out long after the cookies are set.
    options.page_load_strategy = "eager"
    for flag in (
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--lang=zh-CN",
    ):
        options.add_argument(flag)
    if not headless:
        options.add_argument("--window-size=1440,900")
        # `--headless=new` is what lets the page scripts run unattended; a visible
        # window is only useful when a human has to clear a verification slider.
        options.arguments.remove("--headless=new")

    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(40)
        _emit(f"visiting {_ENTRY_URL}", quiet)
        try:
            driver.get(_ENTRY_URL)
        except Exception as exc:  # noqa: BLE001 - a slow load still leaves the cookies set
            _emit(f"  navigation did not finish: {type(exc).__name__}", quiet)
        deadline = time.monotonic() + settle
        cookie = ""
        while time.monotonic() < deadline and not cookie:
            time.sleep(1)
            cookie = _cookie_from(driver)
        return cookie
    finally:
        driver.quit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print a fresh Eastmoney Cookie header value")
    ap.add_argument(
        "--settle", type=float, default=_SETTLE_SECONDS, help="seconds to wait for page scripts"
    )
    ap.add_argument(
        "--show-browser", action="store_true", help="run headed, for manual verification"
    )
    ap.add_argument("--quiet", action="store_true", help="suppress stderr diagnostics")
    args = ap.parse_args(argv)

    try:
        cookie = collect_cookie(
            settle=args.settle, headless=not args.show_browser, quiet=args.quiet
        )
    except Exception as exc:  # noqa: BLE001 - AkShare only reads the exit status and stdout
        sys.stderr.write(f"eastmoney cookie refresh failed: {exc}\n")
        return 1

    if not cookie:
        sys.stderr.write("eastmoney cookie refresh produced no usable cookie\n")
        return 1
    sys.stdout.write(f"{cookie}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

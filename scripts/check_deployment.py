"""Check that a deployed Hangman app works end to end.

Usage:
    python scripts/check_deployment.py https://your-app.onrender.com
    python scripts/check_deployment.py https://your-app.onrender.com --browser

Without ``--browser`` it uses only the standard library: it loads the web
page, then plays a complete game at every difficulty through the REST API and
checks error handling and that the word stays hidden while playing.

With ``--browser`` it also plays a complete game in headless Chromium by
pressing keys on the real page, like a player would (needs Playwright).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

# Most common English letters first, so games finish in a sensible number of guesses.
LETTERS = "etaoinshrdlucmfwypvbgkjqxz"
DIFFICULTIES = ("easy", "medium", "hard")


class CheckFailed(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)
    print(f"  ok  {message}")


def request(base: str, method: str, path: str, body: object = None, timeout: float = 30):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode()


def wait_until_up(base: str, timeout: float) -> None:
    """Free hosting tiers sleep when idle; the first request can take a minute."""
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, _, body = request(base, "GET", "/healthz", timeout=60)
            if status == 200 and json.loads(body).get("status") == "ok":
                return
            last_error = f"HTTP {status}"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
        time.sleep(5)
    raise CheckFailed(f"{base}/healthz did not respond within {timeout:.0f}s ({last_error})")


def check_web_page(base: str) -> None:
    print("Web interface")
    status, headers, html = request(base, "GET", "/")
    check(status == 200, "GET / returns 200")
    check("text/html" in headers.get("Content-Type", ""), "GET / is an HTML page")
    check("<title>Hangman</title>" in html, "page is the Hangman interface")
    for path in ("/static/app.js", "/static/style.css"):
        status, _, _ = request(base, "GET", path)
        check(status == 200, f"GET {path} returns 200")


def play_api_game(base: str, difficulty: str) -> dict:
    status, headers, body = request(base, "POST", "/api/games", {"difficulty": difficulty})
    check(status == 201, f"POST /api/games ({difficulty}) returns 201")
    state = json.loads(body)
    check("word" not in state, f"new {difficulty} game does not reveal the word")
    game_id = state["game_id"]

    status, _, body = request(base, "GET", f"/api/games/{game_id}")
    check(status == 200 and json.loads(body)["game_id"] == game_id, "GET /api/games/{id} returns the game")

    guesses = 0
    for letter in LETTERS:
        status, _, body = request(base, "POST", f"/api/games/{game_id}/guess", {"letter": letter})
        if status != 200:
            raise CheckFailed(f"guess {letter!r} returned HTTP {status}: {body}")
        guesses += 1
        state = json.loads(body)
        if state["status"] == "playing" and "word" in state:
            raise CheckFailed(f"word exposed during play: {body}")
        if state["status"] != "playing":
            break
    check(state["status"] in ("won", "lost"), f"{difficulty} game finished: {state['status']} after {guesses} guesses")
    word = state.get("word", "")
    shown = state["pattern"].split(" ")
    check(
        len(word) == len(shown) and all(c in ("_", w) for c, w in zip(shown, word)),
        f"word {word!r} revealed at the end and matches pattern {state['pattern']!r}",
    )
    status, _, _ = request(base, "POST", f"/api/games/{game_id}/guess", {"letter": "q"})
    check(status == 409, "guessing after the game ends returns 409")
    return state


def check_api(base: str) -> None:
    print("REST API")
    for difficulty in DIFFICULTIES:
        play_api_game(base, difficulty)

    _, _, body = request(base, "POST", "/api/games", {"difficulty": "easy"})
    game_id = json.loads(body)["game_id"]
    request(base, "POST", f"/api/games/{game_id}/guess", {"letter": "e"})
    status, _, _ = request(base, "POST", f"/api/games/{game_id}/guess", {"letter": "e"})
    check(status == 409, "duplicate guess returns 409")
    status, _, _ = request(base, "POST", f"/api/games/{game_id}/guess", {"letter": "7"})
    check(status == 400, "invalid letter returns 400")
    status, _, _ = request(base, "POST", "/api/games", {"difficulty": "impossible"})
    check(status == 400, "invalid difficulty returns 400")
    status, _, _ = request(base, "GET", "/api/games/does-not-exist")
    check(status == 404, "unknown game returns 404")
    status, headers, _ = request(base, "GET", f"/api/games/{game_id}")
    check(headers.get("Cache-Control") == "no-store", "API responses are not cached")


def check_browser(base: str, screenshot: str | None) -> None:
    print("Browser game")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CheckFailed("--browser needs Playwright: pip install playwright && python -m playwright install chromium") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(base, wait_until="networkidle")
        check(page.locator("#keyboard .key").count() == 26, "page shows the letter keyboard")

        page.select_option("#difficulty", "easy")
        with page.expect_response(lambda r: r.url.endswith("/api/games")):
            page.click("#new-game")
        idle = "() => !document.querySelector('#new-game').disabled"
        page.wait_for_function(idle)
        check(page.locator("#remaining").text_content() == "6", "new game shows 6 guesses left")

        for letter in LETTERS:
            message_class = page.locator("#message").get_attribute("class") or ""
            if "won" in message_class or "lost" in message_class:
                break
            with page.expect_response(lambda r: r.url.endswith("/guess")):
                page.keyboard.press(letter)
            page.wait_for_function(idle)
        message = page.locator("#message").text_content()
        check("You won" in message or "You lost" in message, f"game ended in the browser: {message!r}")
        check(page.locator(".key:not([disabled])").count() == 0, "keyboard is disabled after the game ends")
        if screenshot:
            page.screenshot(path=screenshot, full_page=True)
            print(f"  --  screenshot saved to {screenshot}")

        with page.expect_response(lambda r: r.url.endswith("/api/games")):
            page.keyboard.press("Enter")
        page.wait_for_function(idle)
        check(page.locator("#message").text_content() == "", "Enter starts another game without reloading")
        check(errors == [], "no JavaScript errors")
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="Base URL of the deployed app, e.g. https://hangman.onrender.com")
    parser.add_argument("--browser", action="store_true", help="also play a full game in headless Chromium")
    parser.add_argument("--screenshot", help="save a screenshot of the finished browser game here")
    parser.add_argument("--allow-http", action="store_true", help="allow a non-HTTPS URL (local testing)")
    parser.add_argument("--wait", type=float, default=180, help="seconds to wait for a sleeping app to wake")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    try:
        print(f"Checking {base}")
        if urlsplit(base).scheme == "https":
            check(True, "URL uses HTTPS")
        else:
            check(args.allow_http, "URL uses HTTPS (pass --allow-http to test a local server)")
            print("  --  HTTPS check skipped (--allow-http)")
        wait_until_up(base, args.wait)
        check(True, "GET /healthz responds")
        check_web_page(base)
        check_api(base)
        if args.browser:
            check_browser(base, args.screenshot)
    except CheckFailed as exc:
        print(f"FAIL {exc}")
        return 1
    print("All deployment checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

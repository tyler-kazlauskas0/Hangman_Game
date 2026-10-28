"""Browser tests: drive the real web client in headless Chromium.

A real Flask server runs in a background thread with one known word per
difficulty, so each test knows the answer and can check exactly what the
page shows after every guess.

Requires Playwright (``pip install -r requirements-dev.txt`` and
``python -m playwright install chromium``). The tests are skipped when it
isn't installed.
"""

import json
import threading
import unittest
import urllib.request

from werkzeug.serving import make_server

from server import GameStore, create_app
from words import WordManager

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the environment
    sync_playwright = None

WORDS = {"easy": ["zebra"], "medium": ["jukebox"], "hard": ["quixotic"]}


def setUpModule():
    global _server, _thread, _playwright, _browser, BASE_URL
    if sync_playwright is None:
        raise unittest.SkipTest("Playwright is not installed")
    app = create_app(word_manager=WordManager.from_lists(WORDS), store=GameStore())
    _server = make_server("127.0.0.1", 0, app, threaded=True)
    BASE_URL = f"http://127.0.0.1:{_server.server_port}"
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    _playwright = sync_playwright().start()
    try:
        _browser = _playwright.chromium.launch()
    except PlaywrightError as exc:
        _playwright.stop()
        _server.shutdown()
        raise unittest.SkipTest(f"Chromium is not available: {exc}") from exc


def tearDownModule():
    _browser.close()
    _playwright.stop()
    _server.shutdown()


class BrowserTestCase(unittest.TestCase):
    viewport = {"width": 1000, "height": 800}

    def setUp(self):
        self.context = _browser.new_context(viewport=self.viewport)
        self.page = self.context.new_page()
        self.api_calls = []      # (method, path, status, body) for every /api/ call
        self.page_errors = []
        self.page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        self.page.on("response", self._record_response)
        self.page.goto(BASE_URL)
        self.wait_for_status("playing")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.page_errors, [], "JavaScript errors on the page")

    def _record_response(self, response):
        if "/api/" in response.url:
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = None
            path = response.url.removeprefix(BASE_URL)
            self.api_calls.append((response.request.method, path, response.status, body))

    # --- helpers ---

    def state(self):
        """The latest game state the server sent the page."""
        for _, _, _, body in reversed(self.api_calls):
            if body is None:
                continue
            return body.get("game", body) if "error" in body else body
        self.fail("No API responses recorded")

    def wait_for_status(self, status):
        self.page.wait_for_function(
            "s => document.querySelectorAll('#keyboard .key').length === 26"
            " && document.querySelector('#remaining').textContent !== '–'"
            " && (s === 'playing' || document.querySelector('#message').classList.contains(s))",
            arg=status,
        )

    def settle(self):
        """Wait until the page has finished its request and redrawn."""
        self.page.wait_for_function("() => !document.querySelector('#new-game').disabled")

    def new_game(self, difficulty):
        self.page.select_option("#difficulty", difficulty)
        with self.page.expect_response(lambda r: r.url.endswith("/api/games")):
            self.page.click("#new-game")
        self.settle()
        self.assertEqual(self.state()["difficulty"], difficulty)

    def click_letter(self, letter):
        with self.page.expect_response(lambda r: r.url.endswith("/guess")):
            self.page.click(f'.key[data-letter="{letter}"]')
        self.settle()

    def type_letter(self, letter):
        with self.page.expect_response(lambda r: r.url.endswith("/guess")):
            self.page.keyboard.press(letter)
        self.settle()

    def slots(self):
        return self.page.locator("#pattern .slot").all_text_contents()

    def shown_parts(self):
        return self.page.locator("#gallows .part.shown").count()

    def text(self, selector):
        return self.page.locator(selector).text_content().strip()

    def key(self, letter):
        return self.page.locator(f'.key[data-letter="{letter}"]')

    def assert_board_matches_server(self):
        """Every visible piece of state must equal what the server reported."""
        state = self.state()
        pattern = [c if c != "_" else "" for c in state["pattern"].split(" ")]
        if state["status"] != "lost":
            self.assertEqual(self.slots(), pattern)
        self.assertEqual(self.text("#remaining"), str(state["remaining_guesses"]))
        self.assertEqual(self.text("#guessed"), " ".join(state["guessed_letters"]) or "–")
        self.assertEqual(self.text("#incorrect"), " ".join(state["incorrect_letters"]) or "–")
        self.assertEqual(self.shown_parts(), len(state["incorrect_letters"]))
        for letter in "abcdefghijklmnopqrstuvwxyz":
            key = self.key(letter)
            classes = key.get_attribute("class").split()
            self.assertEqual("correct" in classes, letter in state["correct_letters"], letter)
            self.assertEqual("incorrect" in classes, letter in state["incorrect_letters"], letter)
            should_disable = state["status"] != "playing" or letter in state["guessed_letters"]
            self.assertEqual(key.is_disabled(), should_disable, letter)

    def assert_word_not_in_page(self, word):
        self.assertNotIn(word, self.page.content().lower())
        self.assertNotIn(word, self.page.locator("body").inner_text().lower().replace("\n", ""))
        storage = self.page.evaluate(
            "() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])"
        )
        self.assertNotIn(word, storage.lower())


class StartGameTests(BrowserTestCase):
    def test_initial_page(self):
        self.assertEqual(self.page.title(), "Hangman")
        self.assertEqual(self.page.locator("#keyboard .key").count(), 26)
        self.assertEqual(self.text("#remaining"), "6")
        self.assertEqual(self.shown_parts(), 0)
        self.assertEqual(self.text("#message"), "")
        self.assert_board_matches_server()

    def test_start_each_difficulty(self):
        for difficulty, words in WORDS.items():
            with self.subTest(difficulty=difficulty):
                self.new_game(difficulty)
                self.assertEqual(self.slots(), [""] * len(words[0]))
                self.assertEqual(self.text("#remaining"), "6")
                self.assert_board_matches_server()
        # The browser sent exactly the chosen difficulty to the server.
        sent = [c for c in self.api_calls if c[0] == "POST" and c[1] == "/api/games"]
        self.assertEqual([c[3]["difficulty"] for c in sent[-3:]], ["easy", "medium", "hard"])


class GuessTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.new_game("easy")  # zebra

    def test_correct_guess_by_click(self):
        self.click_letter("e")
        self.assertEqual(self.slots(), ["", "e", "", "", ""])
        self.assertEqual(self.text("#remaining"), "6")
        self.assertTrue(self.key("e").is_disabled())
        self.assertIn("correct", self.key("e").get_attribute("class"))
        self.assert_board_matches_server()

    def test_incorrect_guess_by_keyboard(self):
        self.type_letter("o")
        self.assertEqual(self.text("#remaining"), "5")
        self.assertEqual(self.text("#incorrect"), "o")
        self.assertEqual(self.shown_parts(), 1)
        self.assertIn("incorrect", self.key("o").get_attribute("class"))
        self.assert_board_matches_server()

    def test_uppercase_keyboard_input(self):
        self.type_letter("Z")
        self.assertEqual(self.slots(), ["z", "", "", "", ""])

    def test_board_updates_after_every_guess(self):
        for letter in "eoz" "qbt" "r":
            if letter in "eozbr":
                self.type_letter(letter)
            else:
                self.click_letter(letter)
            with self.subTest(after=letter):
                self.assert_board_matches_server()
        self.assertEqual(self.slots(), ["z", "e", "b", "r", ""])
        self.assertEqual(self.text("#remaining"), "3")

    def test_repeated_guess_sends_no_request(self):
        self.type_letter("o")
        before = len(self.api_calls)
        self.page.keyboard.press("o")
        self.key("o").click(force=True)  # disabled button; click must do nothing
        self.page.wait_for_timeout(200)
        self.assertEqual(len(self.api_calls), before)
        self.assertEqual(self.text("#remaining"), "5")
        self.assertEqual(self.text("#incorrect"), "o")

    def test_invalid_keys_are_ignored(self):
        before = len(self.api_calls)
        for key in ["1", "!", "Space", "ArrowLeft", "Enter", "Control+a", "Meta+b"]:
            self.page.keyboard.press(key)
        # Non-ASCII letters can't be pressed through Playwright; dispatch them.
        self.page.evaluate(
            """() => ["é", "ß", "Ω"].forEach(key => document.dispatchEvent(
                 new KeyboardEvent("keydown", {key, bubbles: true})))"""
        )
        self.page.wait_for_timeout(200)
        self.assertEqual(len(self.api_calls), before)
        self.assert_board_matches_server()

    def test_server_rejection_is_shown(self):
        # Guess "z" behind the page's back, then try it in the page. The page
        # still thinks "z" is available, so it asks; the server says 409.
        game_id = self.state()["game_id"]
        request = urllib.request.Request(
            f"{BASE_URL}/api/games/{game_id}/guess",
            data=b'{"letter": "z"}',
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
        self.click_letter("z")
        self.assertEqual(self.api_calls[-1][2], 409)
        self.assertIn("already been guessed", self.text("#message"))
        self.assertIn("error", self.page.locator("#message").get_attribute("class"))
        self.assertEqual(self.slots(), ["z", "", "", "", ""])
        self.assert_board_matches_server()


class WinLossTests(BrowserTestCase):
    def test_win(self):
        self.new_game("easy")
        for letter in "zebr":
            self.type_letter(letter)
        self.assertEqual(self.text("#message"), "")
        self.type_letter("a")
        self.wait_for_status("won")
        self.assertIn("You won", self.text("#message"))
        self.assertIn("ZEBRA", self.text("#message"))
        self.assertEqual(self.slots(), list("zebra"))
        self.assertEqual(self.page.locator(".key:not([disabled])").count(), 0)
        self.assert_board_matches_server()

    def test_loss(self):
        self.new_game("easy")
        self.type_letter("e")
        for i, letter in enumerate("qwtyui", start=1):
            self.type_letter(letter)
            self.assertEqual(self.shown_parts(), i)
            self.assertEqual(self.text("#remaining"), str(6 - i))
        self.wait_for_status("lost")
        self.assertIn("You lost", self.text("#message"))
        self.assertIn("ZEBRA", self.text("#message"))
        # The word is revealed, with the letters the player missed marked.
        self.assertEqual(self.slots(), list("zebra"))
        missed = self.page.locator("#pattern .slot.missed").all_text_contents()
        self.assertEqual(missed, ["z", "b", "r", "a"])
        self.assertEqual(self.page.locator(".key:not([disabled])").count(), 0)
        self.assert_board_matches_server()

    def test_typing_after_game_over_sends_nothing(self):
        self.new_game("easy")
        for letter in "zebra":
            self.type_letter(letter)
        before = len(self.api_calls)
        self.page.keyboard.press("q")
        self.page.wait_for_timeout(200)
        self.assertEqual(len(self.api_calls), before)


class NewGameAfterFinishTests(BrowserTestCase):
    def finish_by_losing(self):
        self.new_game("easy")
        for letter in "qwtyui":
            self.type_letter(letter)
        self.wait_for_status("lost")

    def test_new_game_button_after_loss(self):
        self.finish_by_losing()
        navigations = []
        self.page.on("framenavigated", lambda frame: navigations.append(frame.url))
        self.new_game("hard")
        self.assertEqual(navigations, [])  # no page reload
        self.assertEqual(self.slots(), [""] * len("quixotic"))
        self.assertEqual(self.text("#message"), "")
        self.assertEqual(self.shown_parts(), 0)
        self.assert_board_matches_server()
        self.type_letter("q")
        self.assertEqual(self.slots()[0], "q")

    def test_enter_starts_new_game_after_win(self):
        self.new_game("medium")
        for letter in "jukebox":
            if letter not in self.state()["guessed_letters"]:
                self.type_letter(letter)
        self.wait_for_status("won")
        old_id = self.state()["game_id"]
        with self.page.expect_response(lambda r: r.url.endswith("/api/games")):
            self.page.keyboard.press("Enter")
        self.settle()
        state = self.state()
        self.assertNotEqual(state["game_id"], old_id)
        self.assertEqual(state["status"], "playing")
        self.assertEqual(state["difficulty"], "medium")
        self.assert_board_matches_server()

    def test_reload_resumes_current_game(self):
        self.new_game("easy")
        self.type_letter("e")
        game_id = self.state()["game_id"]
        self.page.reload()
        self.wait_for_status("playing")
        self.assertEqual(self.state()["game_id"], game_id)
        self.assertEqual(self.slots(), ["", "e", "", "", ""])


class HiddenWordTests(BrowserTestCase):
    def test_word_never_reaches_browser_while_playing(self):
        for difficulty, words in WORDS.items():
            word = words[0]
            with self.subTest(difficulty=difficulty):
                self.new_game(difficulty)
                letters = list(dict.fromkeys(word))
                for letter in letters[:-1] + list("ywv"):
                    if letter in self.state()["guessed_letters"]:
                        continue
                    self.type_letter(letter)
                    if self.state()["status"] != "playing":
                        break
                    self.assert_word_not_in_page(word)
                # Every response for this game while it was playing was word-free.
                game_id = self.state()["game_id"]
                for method, path, status, body in self.api_calls:
                    if body and game_id in json.dumps(body):
                        payload = body.get("game", body)
                        if payload.get("status") == "playing":
                            self.assertNotIn("word", payload)
                            self.assertNotIn(word, json.dumps(body))


class MobileLayoutTests(BrowserTestCase):
    viewport = {"width": 375, "height": 700}

    def test_playable_without_horizontal_scroll(self):
        self.new_game("hard")
        self.click_letter("q")
        self.click_letter("z")
        width = self.page.evaluate("() => document.documentElement.scrollWidth")
        self.assertLessEqual(width, 375)
        for letter in "az":
            self.assertTrue(self.key(letter).is_visible())
        self.assert_board_matches_server()


if __name__ == "__main__":
    unittest.main()

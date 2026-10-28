"""End-to-end API flows: full games, new games after finishing, request
validation edge cases, and making sure the hidden word never leaks."""

import json
import random
import unittest

from server import GameStore, create_app
from words import DIFFICULTIES, WordManager

# One distinctive word per difficulty so tests know the answer. Spaced-out
# patterns ("z e b r a") can never contain the word as a substring, so any
# appearance of it in a response body is a leak.
WORDS = {"easy": ["zebra"], "medium": ["jukebox"], "hard": ["quixotic"]}


class FlowTestCase(unittest.TestCase):
    words = WORDS

    def setUp(self):
        manager = WordManager.from_lists(self.words, rng=random.Random(0))
        self.app = create_app(word_manager=manager, store=GameStore())
        self.client = self.app.test_client()

    def create(self, difficulty=None):
        body = {} if difficulty is None else {"difficulty": difficulty}
        response = self.client.post("/api/games", json=body)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def guess(self, game_id, letter):
        return self.client.post(f"/api/games/{game_id}/guess", json={"letter": letter})

    def play(self, game_id, letters):
        data = None
        for letter in letters:
            response = self.guess(game_id, letter)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            data = response.get_json()
        return data


class DifficultyFlowTests(FlowTestCase):
    def test_start_game_at_each_difficulty(self):
        for difficulty in DIFFICULTIES:
            with self.subTest(difficulty=difficulty):
                data = self.create(difficulty)
                word = WORDS[difficulty][0]
                self.assertEqual(data["difficulty"], difficulty)
                self.assertEqual(data["word_length"], len(word))
                self.assertEqual(data["pattern"], " ".join("_" * len(word)))
                self.assertEqual(data["remaining_guesses"], 6)
                self.assertEqual(data["status"], "playing")

    def test_win_at_each_difficulty(self):
        for difficulty in DIFFICULTIES:
            with self.subTest(difficulty=difficulty):
                word = WORDS[difficulty][0]
                game_id = self.create(difficulty)["game_id"]
                data = self.play(game_id, dict.fromkeys(word))
                self.assertEqual(data["status"], "won")
                self.assertEqual(data["word"], word)
                self.assertEqual(data["remaining_guesses"], 6)


class BundledWordFlowTests(unittest.TestCase):
    """Uses the real word lists, as the deployed server does."""

    def test_finished_game_word_comes_from_requested_list(self):
        manager = WordManager(rng=random.Random(5))
        client = create_app(word_manager=manager).test_client()
        for difficulty in DIFFICULTIES:
            with self.subTest(difficulty=difficulty):
                game_id = client.post("/api/games", json={"difficulty": difficulty}).get_json()["game_id"]
                # Guess the whole alphabet; the game ends one way or another.
                data = None
                for letter in "abcdefghijklmnopqrstuvwxyz":
                    response = client.post(f"/api/games/{game_id}/guess", json={"letter": letter})
                    if response.status_code == 409:
                        break
                    data = response.get_json()
                    if data["status"] == "playing":
                        self.assertNotIn("word", data)
                self.assertIn(data["status"], ("won", "lost"))
                self.assertIn(data["word"], manager.words(difficulty))


class GuessFlowTests(FlowTestCase):
    def test_correct_then_incorrect_guesses(self):
        game_id = self.create("easy")["game_id"]  # zebra
        data = self.guess(game_id, "e").get_json()
        self.assertTrue(data["correct"])
        self.assertEqual(data["pattern"], "_ e _ _ _")
        self.assertEqual(data["remaining_guesses"], 6)

        data = self.guess(game_id, "o").get_json()
        self.assertFalse(data["correct"])
        self.assertEqual(data["pattern"], "_ e _ _ _")
        self.assertEqual(data["remaining_guesses"], 5)
        self.assertEqual(data["guessed_letters"], ["e", "o"])
        self.assertEqual(data["correct_letters"], ["e"])
        self.assertEqual(data["incorrect_letters"], ["o"])

    def test_repeated_and_invalid_guesses_do_not_change_state(self):
        game_id = self.create("easy")["game_id"]
        self.play(game_id, "eo")
        before = self.client.get(f"/api/games/{game_id}").get_json()
        for letter, status in [("e", 409), ("O", 409), ("ee", 400), ("3", 400), ("", 400), (" ", 400)]:
            with self.subTest(letter=letter):
                response = self.guess(game_id, letter)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["game"], before)
        self.assertEqual(self.client.get(f"/api/games/{game_id}").get_json(), before)

    def test_win(self):
        game_id = self.create("easy")["game_id"]
        data = self.play(game_id, "zxebra")
        self.assertEqual(data["status"], "won")
        self.assertEqual(data["pattern"], "z e b r a")
        self.assertEqual(data["remaining_guesses"], 5)
        self.assertEqual(data["word"], "zebra")

    def test_lose(self):
        game_id = self.create("easy")["game_id"]
        data = self.play(game_id, "zqwtyu")
        self.assertEqual(data["status"], "playing")
        self.assertEqual(data["remaining_guesses"], 1)
        data = self.play(game_id, "i")
        self.assertEqual(data["status"], "lost")
        self.assertEqual(data["remaining_guesses"], 0)
        self.assertEqual(data["pattern"], "z _ _ _ _")
        self.assertEqual(data["word"], "zebra")

    def test_new_game_after_completing_one(self):
        first = self.create("easy")["game_id"]
        self.play(first, "zebra")
        second = self.create("easy")
        self.assertNotEqual(second["game_id"], first)
        self.assertEqual(second["status"], "playing")
        self.assertEqual(second["guessed_letters"], [])
        self.assertEqual(second["remaining_guesses"], 6)
        self.assertNotIn("word", second)
        # The new game is playable, and the finished one stays finished.
        self.assertTrue(self.guess(second["game_id"], "z").get_json()["correct"])
        self.assertEqual(self.guess(first, "q").status_code, 409)
        self.assertEqual(self.client.get(f"/api/games/{first}").get_json()["status"], "won")

    def test_new_game_after_losing_at_another_difficulty(self):
        first = self.create("easy")["game_id"]
        self.play(first, "qwtyui")
        second = self.create("hard")
        self.assertEqual(second["difficulty"], "hard")
        self.assertEqual(second["word_length"], len("quixotic"))
        self.assertEqual(second["status"], "playing")


class InvalidRequestTests(FlowTestCase):
    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"]["message"], str)

    def test_create_game_bad_bodies(self):
        cases = [
            ("null", 400, "invalid_request"),
            ("42", 400, "invalid_request"),
            ('"easy"', 400, "invalid_request"),
            ("{", 400, "malformed_json"),
            ('{"difficulty": "nightmare"}', 400, "invalid_difficulty"),
            ('{"difficulty": {"level": "easy"}}', 400, "invalid_difficulty"),
            ('{"difficulty": "easy", "word": "cat"}', 400, "invalid_request"),
        ]
        for raw, status, code in cases:
            with self.subTest(body=raw):
                response = self.client.post("/api/games", data=raw, content_type="application/json")
                self.assert_error(response, status, code)

    def test_guess_bad_bodies(self):
        game_id = self.create("easy")["game_id"]
        cases = [
            ("{}", 400, "missing_letter"),
            ('{"guess": "a"}', 400, "invalid_request"),
            ('{"letter": null}', 400, "invalid_guess"),
            ('{"letter": true}', 400, "invalid_guess"),
            ('{"letter": "a" }extra', 400, "malformed_json"),
            ('["a"]', 400, "invalid_request"),
            ('{"letter": "%s"}' % ("a" * 1000), 400, "invalid_guess"),
        ]
        for raw, status, code in cases:
            with self.subTest(body=raw[:30]):
                response = self.client.post(
                    f"/api/games/{game_id}/guess", data=raw, content_type="application/json"
                )
                self.assert_error(response, status, code)
        self.assertEqual(self.client.get(f"/api/games/{game_id}").get_json()["guessed_letters"], [])

    def test_guess_requires_json_content_type(self):
        game_id = self.create("easy")["game_id"]
        response = self.client.post(f"/api/games/{game_id}/guess", data="letter=a")
        self.assert_error(response, 415, "unsupported_media_type")

    def test_unknown_game_ids(self):
        for game_id in ["0", "x" * 32, "%00", "ABC-def"]:
            with self.subTest(game_id=game_id):
                self.assert_error(self.client.get(f"/api/games/{game_id}"), 404, "game_not_found")
                self.assert_error(self.guess(game_id, "a"), 404, "game_not_found")

    def test_unknown_game_checked_before_body(self):
        response = self.client.post("/api/games/missing/guess", data="{", content_type="application/json")
        self.assert_error(response, 404, "game_not_found")

    def test_wrong_methods(self):
        game_id = self.create("easy")["game_id"]
        for method, path in [
            ("get", "/api/games"),
            ("put", f"/api/games/{game_id}"),
            ("delete", f"/api/games/{game_id}"),
            ("get", f"/api/games/{game_id}/guess"),
        ]:
            with self.subTest(method=method, path=path):
                self.assert_error(getattr(self.client, method)(path), 405, "method_not_allowed")


class UnexpectedErrorTests(unittest.TestCase):
    def test_unhandled_exception_returns_generic_json_500(self):
        app = create_app(word_manager=WordManager.from_lists(WORDS))

        @app.get("/api/boom")
        def boom():
            raise RuntimeError("secret internal detail")

        with self.assertLogs(app.logger, level="ERROR"):
            response = app.test_client().get("/api/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["code"], "internal_error")
        self.assertNotIn("secret internal detail", response.get_data(as_text=True))


class HiddenWordTests(FlowTestCase):
    """While a game is playing, the word must not appear in any response."""

    def assert_no_leak(self, response, word):
        text = response.get_data(as_text=True)
        self.assertNotIn(word, text.lower())
        body = json.loads(text)
        for state in (body, body.get("game") or {}):
            self.assertNotIn("word", state)
            self.assertNotIn("answer", state)

    def test_no_leak_in_any_response_while_playing(self):
        for difficulty in DIFFICULTIES:
            word = WORDS[difficulty][0]
            with self.subTest(difficulty=difficulty):
                created = self.client.post("/api/games", json={"difficulty": difficulty})
                self.assert_no_leak(created, word)
                game_id = created.get_json()["game_id"]
                # Reveal all but the last distinct letter, with errors in between.
                letters = list(dict.fromkeys(word))[:-1]
                for letter in letters:
                    self.assert_no_leak(self.guess(game_id, letter), word)
                    self.assert_no_leak(self.guess(game_id, letter), word)  # duplicate (409)
                    self.assert_no_leak(self.guess(game_id, "1"), word)  # invalid (400)
                    self.assert_no_leak(self.client.get(f"/api/games/{game_id}"), word)
                state = self.client.get(f"/api/games/{game_id}").get_json()
                self.assertEqual(state["status"], "playing")
                self.assertIn("_", state["pattern"])

    def test_no_leak_after_misses_until_loss(self):
        word = "zebra"
        game_id = self.create("easy")["game_id"]
        for letter in "qwtyu":
            self.assert_no_leak(self.guess(game_id, letter), word)
        self.assert_no_leak(self.client.get(f"/api/games/{game_id}"), word)
        final = self.guess(game_id, "i").get_json()
        self.assertEqual(final["status"], "lost")
        self.assertEqual(final["word"], word)

    def test_game_ids_do_not_encode_the_word(self):
        ids = {self.create("easy")["game_id"] for _ in range(20)}
        self.assertEqual(len(ids), 20)
        for game_id in ids:
            self.assertRegex(game_id, r"^[0-9a-f]{32}$")
            self.assertNotIn("zebra", game_id)


if __name__ == "__main__":
    unittest.main()

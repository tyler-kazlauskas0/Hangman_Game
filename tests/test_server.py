import random
import threading
import unittest

from game import HangmanGame
from server import GameStore, create_app
from words import WordManager

WORDS = {"easy": ["cat"], "medium": ["apple"], "hard": ["rhythm"]}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        manager = WordManager.from_lists(WORDS, rng=random.Random(0))
        self.store = GameStore()
        self.app = create_app(word_manager=manager, store=self.store)
        self.client = self.app.test_client()

    def create(self, **body):
        response = self.client.post("/api/games", json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def guess(self, game_id, letter):
        return self.client.post(f"/api/games/{game_id}/guess", json={"letter": letter})

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json()["error"]["code"], code)


class CreateGameTests(ApiTestCase):
    def test_create_game(self):
        response = self.client.post("/api/games", json={"difficulty": "easy"})
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(response.headers["Location"], f"/api/games/{data['game_id']}")
        self.assertEqual(data["pattern"], "_ _ _")
        self.assertEqual(data["difficulty"], "easy")
        self.assertEqual(data["remaining_guesses"], 6)
        self.assertEqual(data["status"], "playing")
        self.assertEqual(data["guessed_letters"], [])
        self.assertNotIn("word", data)

    def test_difficulty_is_case_insensitive(self):
        self.assertEqual(self.create(difficulty="HARD")["difficulty"], "hard")

    def test_default_difficulty_is_medium(self):
        self.assertEqual(self.create()["difficulty"], "medium")
        response = self.client.post("/api/games")  # no body at all
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["difficulty"], "medium")

    def test_game_ids_are_unique(self):
        ids = {self.create()["game_id"] for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_invalid_difficulty(self):
        for bad in ["expert", "", 3, None, ["easy"]]:
            with self.subTest(difficulty=bad):
                response = self.client.post("/api/games", json={"difficulty": bad})
                self.assert_error(response, 400, "invalid_difficulty")
        self.assertEqual(len(self.store), 0)

    def test_malformed_json(self):
        response = self.client.post(
            "/api/games", data="{not json", content_type="application/json"
        )
        self.assert_error(response, 400, "malformed_json")

    def test_body_must_be_object(self):
        response = self.client.post("/api/games", json=["easy"])
        self.assert_error(response, 400, "invalid_request")

    def test_unknown_fields_rejected(self):
        response = self.client.post("/api/games", json={"difficulty": "easy", "word": "cat"})
        self.assert_error(response, 400, "invalid_request")

    def test_non_json_content_type(self):
        response = self.client.post("/api/games", data="difficulty=easy", content_type="text/plain")
        self.assert_error(response, 415, "unsupported_media_type")


class GetGameTests(ApiTestCase):
    def test_get_game(self):
        game_id = self.create(difficulty="medium")["game_id"]
        self.guess(game_id, "p")
        response = self.client.get(f"/api/games/{game_id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["game_id"], game_id)
        self.assertEqual(data["pattern"], "_ p p _ _")
        self.assertEqual(data["guessed_letters"], ["p"])
        self.assertNotIn("word", data)

    def test_unknown_game(self):
        self.assert_error(self.client.get("/api/games/nope"), 404, "game_not_found")

    def test_games_are_independent(self):
        first = self.create(difficulty="easy")["game_id"]
        second = self.create(difficulty="easy")["game_id"]
        self.guess(first, "c")
        self.guess(first, "z")
        a = self.client.get(f"/api/games/{first}").get_json()
        b = self.client.get(f"/api/games/{second}").get_json()
        self.assertEqual(a["guessed_letters"], ["c", "z"])
        self.assertEqual(a["remaining_guesses"], 5)
        self.assertEqual(b["guessed_letters"], [])
        self.assertEqual(b["remaining_guesses"], 6)


class GuessTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.game_id = self.create(difficulty="medium")["game_id"]  # word: apple

    def test_correct_guess(self):
        response = self.guess(self.game_id, "P")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["correct"])
        self.assertEqual(data["pattern"], "_ p p _ _")
        self.assertEqual(data["guessed_letters"], ["p"])
        self.assertEqual(data["incorrect_letters"], [])
        self.assertEqual(data["remaining_guesses"], 6)
        self.assertEqual(data["status"], "playing")
        self.assertNotIn("word", data)

    def test_incorrect_guess(self):
        data = self.guess(self.game_id, "z").get_json()
        self.assertFalse(data["correct"])
        self.assertEqual(data["incorrect_letters"], ["z"])
        self.assertEqual(data["remaining_guesses"], 5)

    def test_invalid_letters(self):
        for bad in ["", "ab", "1", "!", None, 7, ["a"]]:
            with self.subTest(letter=bad):
                response = self.guess(self.game_id, bad)
                self.assert_error(response, 400, "invalid_guess")
                self.assertNotIn("word", response.get_json()["game"])
        state = self.client.get(f"/api/games/{self.game_id}").get_json()
        self.assertEqual(state["guessed_letters"], [])

    def test_missing_letter(self):
        response = self.client.post(f"/api/games/{self.game_id}/guess", json={})
        self.assert_error(response, 400, "missing_letter")
        response = self.client.post(f"/api/games/{self.game_id}/guess")
        self.assert_error(response, 400, "missing_letter")

    def test_unknown_fields_rejected(self):
        response = self.client.post(
            f"/api/games/{self.game_id}/guess", json={"letter": "a", "word": "apple"}
        )
        self.assert_error(response, 400, "invalid_request")

    def test_malformed_json(self):
        response = self.client.post(
            f"/api/games/{self.game_id}/guess", data="letter=a", content_type="application/json"
        )
        self.assert_error(response, 400, "malformed_json")

    def test_duplicate_guess(self):
        self.guess(self.game_id, "z")
        response = self.guess(self.game_id, "Z")
        self.assert_error(response, 409, "duplicate_guess")
        self.assertEqual(response.get_json()["game"]["remaining_guesses"], 5)

    def test_unknown_game(self):
        self.assert_error(self.guess("missing", "a"), 404, "game_not_found")

    def test_win_reveals_word_and_blocks_more_guesses(self):
        for letter in "aple":
            data = self.guess(self.game_id, letter).get_json()
        self.assertEqual(data["status"], "won")
        self.assertEqual(data["word"], "apple")
        self.assertEqual(data["pattern"], "a p p l e")
        response = self.guess(self.game_id, "z")
        self.assert_error(response, 409, "game_over")
        self.assertEqual(response.get_json()["game"]["guessed_letters"], list("aple"))

    def test_loss_reveals_word_only_at_the_end(self):
        for i, letter in enumerate("qzxjvk", start=1):
            data = self.guess(self.game_id, letter).get_json()
            if i < 6:
                self.assertEqual(data["status"], "playing")
                self.assertNotIn("word", data)
                self.assertNotIn("apple", str(data))
        self.assertEqual(data["status"], "lost")
        self.assertEqual(data["remaining_guesses"], 0)
        self.assertEqual(data["word"], "apple")
        self.assertEqual(self.client.get(f"/api/games/{self.game_id}").get_json()["word"], "apple")
        self.assert_error(self.guess(self.game_id, "a"), 409, "game_over")

    def test_concurrent_guesses_are_not_lost(self):
        letters = "bcdfghjkmn"  # all wrong for "apple"; only six can be accepted
        game_id = self.create(difficulty="medium")["game_id"]
        statuses = []

        def worker(letter):
            with self.app.test_client() as client:
                statuses.append(
                    client.post(f"/api/games/{game_id}/guess", json={"letter": letter}).status_code
                )

        threads = [threading.Thread(target=worker, args=(c,)) for c in letters]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(statuses.count(200), 6)
        self.assertEqual(statuses.count(409), 4)
        state = self.client.get(f"/api/games/{game_id}").get_json()
        self.assertEqual(len(state["incorrect_letters"]), 6)
        self.assertEqual(state["status"], "lost")


class RoutingTests(ApiTestCase):
    def test_unknown_route_returns_json(self):
        self.assert_error(self.client.get("/api/nothing"), 404, "not_found")

    def test_wrong_method_returns_json(self):
        response = self.client.delete("/api/games")
        self.assert_error(response, 405, "method_not_allowed")
        self.assertIn("POST", response.headers["Allow"])
        self.assert_error(self.client.get("/api/games/abc/guess"), 405, "method_not_allowed")


class GameStoreTests(unittest.TestCase):
    def test_oldest_games_evicted_past_limit(self):
        store = GameStore(max_games=3)
        ids = [store.add(HangmanGame("cat")) for _ in range(4)]
        self.assertEqual(len(store), 3)
        self.assertIsNone(store.get(ids[0]))
        self.assertIsNotNone(store.get(ids[3]))


if __name__ == "__main__":
    unittest.main()

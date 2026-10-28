import random
import unittest

from game import (
    LOST,
    MAX_INCORRECT_GUESSES,
    PLAYING,
    WON,
    DuplicateGuessError,
    GameOverError,
    HangmanGame,
    InvalidGuessError,
)
from words import InvalidDifficultyError, WordManager


def lose(game):
    """Make wrong guesses until the game is lost."""
    for letter in "qzxjvkwy":
        if game.is_over:
            break
        game.guess(letter)


class NewGameTests(unittest.TestCase):
    def test_initial_state(self):
        game = HangmanGame("apple", difficulty="easy")
        self.assertEqual(game.pattern, "_ _ _ _ _")
        self.assertEqual(game.status, PLAYING)
        self.assertEqual(game.remaining_guesses, MAX_INCORRECT_GUESSES)
        self.assertEqual(game.guessed_letters, [])
        self.assertEqual(game.incorrect_letters, [])
        self.assertIsNone(game.answer)

    def test_word_is_normalized(self):
        game = HangmanGame("  Apple ")
        game.guess("a")
        self.assertEqual(game.pattern, "a _ _ _ _")

    def test_rejects_invalid_word(self):
        for word in ["", "ice cream", "abc1", "café", None]:
            with self.subTest(word=word), self.assertRaises(ValueError):
                HangmanGame(word)

    def test_rejects_invalid_difficulty(self):
        with self.assertRaises(InvalidDifficultyError):
            HangmanGame("apple", difficulty="impossible")

    def test_rejects_invalid_max_incorrect(self):
        for bad in [0, -1]:
            with self.subTest(max_incorrect=bad), self.assertRaises(ValueError):
                HangmanGame("apple", max_incorrect=bad)

    def test_new_picks_word_from_difficulty_list(self):
        manager = WordManager.from_lists(
            {"easy": ["cat"], "medium": ["garden"], "hard": ["rhythm"]},
            rng=random.Random(0),
        )
        for difficulty, length in [("easy", 3), ("medium", 6), ("hard", 6)]:
            game = HangmanGame.new(difficulty, manager)
            self.assertEqual(game.difficulty, difficulty)
            self.assertEqual(game.word_length, length)

    def test_new_uses_bundled_word_lists(self):
        game = HangmanGame.new("Hard")
        self.assertEqual(game.difficulty, "hard")
        self.assertEqual(game.status, PLAYING)

    def test_new_rejects_invalid_difficulty(self):
        with self.assertRaises(InvalidDifficultyError):
            HangmanGame.new("expert")


class GuessTests(unittest.TestCase):
    def setUp(self):
        self.game = HangmanGame("apple")

    def test_correct_guess_reveals_every_occurrence(self):
        self.assertTrue(self.game.guess("p"))
        self.assertEqual(self.game.pattern, "_ p p _ _")
        self.assertEqual(self.game.correct_letters, ["p"])
        self.assertEqual(self.game.remaining_guesses, MAX_INCORRECT_GUESSES)

    def test_incorrect_guess_costs_a_life(self):
        self.assertFalse(self.game.guess("z"))
        self.assertEqual(self.game.incorrect_letters, ["z"])
        self.assertEqual(self.game.remaining_guesses, MAX_INCORRECT_GUESSES - 1)
        self.assertEqual(self.game.pattern, "_ _ _ _ _")

    def test_guesses_are_case_insensitive_and_ordered(self):
        self.game.guess("E")
        self.game.guess("x")
        self.game.guess(" A ")
        self.assertEqual(self.game.guessed_letters, ["e", "x", "a"])
        self.assertEqual(self.game.correct_letters, ["e", "a"])
        self.assertEqual(self.game.incorrect_letters, ["x"])

    def test_invalid_guesses_are_rejected_without_changing_state(self):
        for bad in ["", "ab", "1", "?", " ", "é", None, 5, ["a"]]:
            with self.subTest(guess=bad), self.assertRaises(InvalidGuessError):
                self.game.guess(bad)
        self.assertEqual(self.game.guessed_letters, [])
        self.assertEqual(self.game.remaining_guesses, MAX_INCORRECT_GUESSES)

    def test_duplicate_guesses_are_rejected_without_changing_state(self):
        self.game.guess("z")
        with self.assertRaises(DuplicateGuessError):
            self.game.guess("z")
        with self.assertRaises(DuplicateGuessError):
            self.game.guess("Z")
        self.assertEqual(self.game.guessed_letters, ["z"])
        self.assertEqual(self.game.remaining_guesses, MAX_INCORRECT_GUESSES - 1)

    def test_duplicate_correct_guess_is_rejected(self):
        self.game.guess("p")
        with self.assertRaises(DuplicateGuessError):
            self.game.guess("p")


class WinLossTests(unittest.TestCase):
    def test_win(self):
        game = HangmanGame("apple")
        for letter in "aple":
            self.assertEqual(game.status, PLAYING)
            game.guess(letter)
        self.assertEqual(game.status, WON)
        self.assertTrue(game.is_won and game.is_over)
        self.assertFalse(game.is_lost)
        self.assertEqual(game.pattern, "a p p l e")
        self.assertEqual(game.answer, "apple")

    def test_win_on_last_life(self):
        game = HangmanGame("cat")
        for letter in "qzxjv":
            game.guess(letter)
        self.assertEqual(game.remaining_guesses, 1)
        for letter in "cat":
            game.guess(letter)
        self.assertEqual(game.status, WON)
        self.assertEqual(game.remaining_guesses, 1)

    def test_loss_after_six_incorrect_guesses(self):
        game = HangmanGame("apple")
        for i, letter in enumerate("qzxjvk", start=1):
            game.guess(letter)
            self.assertEqual(game.remaining_guesses, MAX_INCORRECT_GUESSES - i)
            self.assertEqual(game.status, LOST if i == 6 else PLAYING)
        self.assertTrue(game.is_lost and game.is_over)
        self.assertEqual(game.remaining_guesses, 0)
        self.assertEqual(game.answer, "apple")

    def test_custom_max_incorrect(self):
        game = HangmanGame("apple", max_incorrect=2)
        game.guess("q")
        game.guess("z")
        self.assertEqual(game.status, LOST)

    def test_no_guesses_after_win(self):
        game = HangmanGame("cat")
        for letter in "cat":
            game.guess(letter)
        with self.assertRaises(GameOverError):
            game.guess("z")
        self.assertEqual(game.guessed_letters, ["c", "a", "t"])

    def test_no_guesses_after_loss(self):
        game = HangmanGame("apple")
        lose(game)
        before = game.to_dict()
        for letter in ["a", "q", "1"]:
            with self.subTest(guess=letter), self.assertRaises(GameOverError):
                game.guess(letter)
        self.assertEqual(game.to_dict(), before)


class SerializationTests(unittest.TestCase):
    def test_word_hidden_while_playing(self):
        game = HangmanGame("secret")
        game.guess("e")
        game.guess("z")
        state = game.to_dict()
        self.assertNotIn("word", state)
        self.assertNotIn("secret", repr(state))
        self.assertNotIn("secret", repr(game))
        self.assertEqual(
            state,
            {
                "difficulty": "medium",
                "pattern": "_ e _ _ e _",
                "word_length": 6,
                "guessed_letters": ["e", "z"],
                "correct_letters": ["e"],
                "incorrect_letters": ["z"],
                "max_incorrect": 6,
                "remaining_guesses": 5,
                "status": "playing",
            },
        )

    def test_word_revealed_after_win(self):
        game = HangmanGame("cat")
        for letter in "cat":
            game.guess(letter)
        self.assertEqual(game.to_dict()["word"], "cat")

    def test_word_revealed_after_loss(self):
        game = HangmanGame("apple")
        lose(game)
        state = game.to_dict()
        self.assertEqual(state["status"], LOST)
        self.assertEqual(state["word"], "apple")

    def test_to_dict_returns_copies(self):
        game = HangmanGame("apple")
        game.guess("a")
        game.to_dict()["guessed_letters"].append("z")
        game.guessed_letters.append("z")
        self.assertEqual(game.guessed_letters, ["a"])


class DifficultyTests(unittest.TestCase):
    def test_new_game_at_each_difficulty_uses_that_list(self):
        manager = WordManager(rng=random.Random(7))
        for difficulty in ("easy", "medium", "hard"):
            with self.subTest(difficulty=difficulty):
                words = set(manager.words(difficulty))
                for _ in range(20):
                    game = HangmanGame.new(difficulty, manager)
                    self.assertEqual(game.difficulty, difficulty)
                    self.assertEqual(game.status, PLAYING)
                    self.assertEqual(game.remaining_guesses, MAX_INCORRECT_GUESSES)
                    lose(game)
                    self.assertIn(game.answer, words)

    def test_random_selection_varies(self):
        manager = WordManager(rng=random.Random(3))
        seen = set()
        for _ in range(40):
            game = HangmanGame.new("easy", manager)
            lose(game)
            seen.add(game.answer)
        self.assertGreater(len(seen), 5)


class NewGameAfterFinishTests(unittest.TestCase):
    def test_new_game_starts_fresh_after_win_and_loss(self):
        manager = WordManager.from_lists({"easy": ["cat"], "medium": ["apple"], "hard": ["rhythm"]})
        won = HangmanGame.new("easy", manager)
        for letter in "cat":
            won.guess(letter)
        lost = HangmanGame.new("medium", manager)
        lose(lost)

        fresh = HangmanGame.new("easy", manager)
        self.assertEqual(fresh.status, PLAYING)
        self.assertEqual(fresh.guessed_letters, [])
        self.assertEqual(fresh.remaining_guesses, MAX_INCORRECT_GUESSES)
        self.assertEqual(fresh.pattern, "_ _ _")
        self.assertTrue(fresh.guess("c"))
        # Finished games are unaffected by the new one.
        self.assertEqual(won.status, WON)
        self.assertEqual(lost.status, LOST)


class SecrecyTests(unittest.TestCase):
    def test_word_hidden_at_every_step_until_the_end(self):
        for word, guesses, final in [
            ("zebra", "qzebxr" + "a", WON),
            ("zebra", "zqxjvkw", LOST),
        ]:
            with self.subTest(word=word, final=final):
                game = HangmanGame(word)
                for letter in guesses:
                    state = game.to_dict()
                    self.assertNotIn("word", state)
                    self.assertIsNone(game.answer)
                    self.assertNotIn(word, repr(state))
                    self.assertNotIn(word, repr(game))
                    if game.is_over:
                        break
                    game.guess(letter)
                self.assertEqual(game.status, final)
                self.assertEqual(game.to_dict()["word"], word)

    def test_rejected_guess_errors_do_not_mention_word(self):
        game = HangmanGame("zebra")
        game.guess("z")
        for bad in ["z", "1", ""]:
            try:
                game.guess(bad)
            except Exception as exc:  # noqa: BLE001 - checking every rejection
                self.assertNotIn("zebra", str(exc))


if __name__ == "__main__":
    unittest.main()

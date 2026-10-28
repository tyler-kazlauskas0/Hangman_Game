import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from words import (
    DIFFICULTIES,
    InvalidDifficultyError,
    WordListError,
    WordManager,
    load_word_file,
    normalize_difficulty,
)


class BundledWordListTests(unittest.TestCase):
    def test_every_difficulty_loads(self):
        manager = WordManager()
        for difficulty in DIFFICULTIES:
            with self.subTest(difficulty=difficulty):
                words = manager.words(difficulty)
                self.assertGreaterEqual(len(words), 20)
                self.assertEqual(len(words), len(set(words)))
                for word in words:
                    self.assertRegex(word, r"^[a-z]+$")

    def test_random_word_comes_from_requested_list(self):
        manager = WordManager(rng=random.Random(1))
        for difficulty in DIFFICULTIES:
            words = set(manager.words(difficulty))
            for _ in range(50):
                self.assertIn(manager.random_word(difficulty), words)


class DifficultyTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_difficulty(" Easy "), "easy")
        self.assertEqual(normalize_difficulty("HARD"), "hard")

    def test_invalid_difficulty(self):
        manager = WordManager()
        for bad in ["", "expert", "easy medium", None, 1]:
            with self.subTest(difficulty=bad):
                with self.assertRaises(InvalidDifficultyError):
                    manager.random_word(bad)
                with self.assertRaises(InvalidDifficultyError):
                    normalize_difficulty(bad)


class LoadWordFileTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_skips_comments_blanks_and_duplicates(self):
        path = self.write("# header\n\nCat\ndog\n  cat \nDOG\nbird\n")
        self.assertEqual(load_word_file(path), ["cat", "dog", "bird"])

    def test_rejects_non_alphabetic_word(self):
        for bad in ["ice cream", "abc1", "co-op", "naïve"]:
            with self.subTest(word=bad), self.assertRaises(WordListError):
                load_word_file(self.write(f"cat\n{bad}\n"))

    def test_rejects_empty_file(self):
        with self.assertRaises(WordListError):
            load_word_file(self.write("# nothing here\n\n"))

    def test_missing_file(self):
        with self.assertRaises(WordListError):
            load_word_file(Path("/nonexistent/easy.txt"))

    def test_missing_directory(self):
        with self.assertRaises(WordListError):
            WordManager("/nonexistent")


class FromListsTests(unittest.TestCase):
    def test_selection_is_random_across_list(self):
        manager = WordManager.from_lists(
            {"easy": ["cat", "dog", "sun"], "medium": ["garden"], "hard": ["rhythm"]},
            rng=random.Random(42),
        )
        counts = Counter(manager.random_word("easy") for _ in range(300))
        self.assertEqual(set(counts), {"cat", "dog", "sun"})

    def test_requires_every_difficulty(self):
        with self.assertRaises(WordListError):
            WordManager.from_lists({"easy": ["cat"], "medium": ["garden"]})

    def test_rejects_bad_word(self):
        with self.assertRaises(WordListError):
            WordManager.from_lists({"easy": ["c4t"], "medium": ["garden"], "hard": ["rhythm"]})


if __name__ == "__main__":
    unittest.main()

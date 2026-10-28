"""Word management for Hangman.

Loads the Easy, Medium, and Hard word lists and selects random words by
difficulty. This module has no dependency on any web framework or UI.
"""

from __future__ import annotations

import random
from pathlib import Path

DIFFICULTIES = ("easy", "medium", "hard")
DEFAULT_DIFFICULTY = "medium"
DEFAULT_WORDS_DIR = Path(__file__).resolve().parent / "words"


class InvalidDifficultyError(ValueError):
    """Raised when a difficulty other than easy, medium, or hard is requested."""


class WordListError(ValueError):
    """Raised when a word list file is missing, empty, or contains a bad entry."""


def normalize_difficulty(difficulty: object) -> str:
    """Return the canonical lowercase difficulty name, or raise InvalidDifficultyError."""
    if isinstance(difficulty, str):
        value = difficulty.strip().lower()
        if value in DIFFICULTIES:
            return value
    raise InvalidDifficultyError(
        f"Invalid difficulty {difficulty!r}; expected one of: {', '.join(DIFFICULTIES)}"
    )


def is_valid_word(word: str) -> bool:
    """A playable word is non-empty and made only of the ASCII letters a-z."""
    return bool(word) and word.isascii() and word.isalpha()


def load_word_file(path: Path) -> list[str]:
    """Read one word list.

    Blank lines and lines starting with ``#`` are ignored. Words are
    lowercased and duplicates are dropped (first occurrence wins). A line
    containing anything other than letters raises WordListError so a typo in
    a word list is caught instead of silently producing an unwinnable game.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WordListError(f"Cannot read word list {path}: {exc}") from exc

    words: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(lines, start=1):
        word = raw.strip().lower()
        if not word or word.startswith("#"):
            continue
        if not is_valid_word(word):
            raise WordListError(
                f"{path}:{line_number}: {raw.strip()!r} is not a single alphabetic word"
            )
        if word not in seen:
            seen.add(word)
            words.append(word)

    if not words:
        raise WordListError(f"Word list {path} contains no words")
    return words


class WordManager:
    """Holds the word list for each difficulty and picks random words."""

    def __init__(
        self,
        words_dir: str | Path = DEFAULT_WORDS_DIR,
        rng: random.Random | None = None,
    ) -> None:
        self._rng = rng or random.Random()
        directory = Path(words_dir)
        self._words = {
            difficulty: load_word_file(directory / f"{difficulty}.txt")
            for difficulty in DIFFICULTIES
        }

    @classmethod
    def from_lists(
        cls,
        lists: dict[str, list[str]],
        rng: random.Random | None = None,
    ) -> "WordManager":
        """Build a manager from in-memory lists (useful for tests)."""
        manager = cls.__new__(cls)
        manager._rng = rng or random.Random()
        manager._words = {}
        for difficulty in DIFFICULTIES:
            words: list[str] = []
            for word in lists.get(difficulty, []):
                word = word.strip().lower()
                if not is_valid_word(word):
                    raise WordListError(f"{word!r} is not a single alphabetic word")
                if word not in words:
                    words.append(word)
            if not words:
                raise WordListError(f"No words supplied for difficulty {difficulty!r}")
            manager._words[difficulty] = words
        return manager

    def words(self, difficulty: str) -> list[str]:
        """Return a copy of the word list for a difficulty."""
        return list(self._words[normalize_difficulty(difficulty)])

    def random_word(self, difficulty: str) -> str:
        """Return a random word from the given difficulty's list."""
        return self._rng.choice(self._words[normalize_difficulty(difficulty)])

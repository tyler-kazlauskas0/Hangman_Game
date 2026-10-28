"""Hangman game engine.

The engine is pure Python: it knows nothing about Flask, HTTP, or the
browser. A server wraps it to expose games over a REST API, and the browser
only ever sees the client-safe dictionary returned by ``to_dict()``.
"""

from __future__ import annotations

import string

from words import WordManager, is_valid_word, normalize_difficulty

MAX_INCORRECT_GUESSES = 6

PLAYING = "playing"
WON = "won"
LOST = "lost"

MASK_CHAR = "_"


class GuessError(ValueError):
    """Base class for guesses the engine rejects. A rejected guess never changes state."""


class InvalidGuessError(GuessError):
    """The guess is not exactly one letter a-z."""


class DuplicateGuessError(GuessError):
    """The letter has already been guessed in this game."""


class GameOverError(GuessError):
    """The game has already been won or lost."""


class HangmanGame:
    """A single game of Hangman.

    The hidden word is stored internally and is exposed through ``to_dict()``
    only once the game is over.
    """

    def __init__(
        self,
        word: str,
        difficulty: str = "medium",
        max_incorrect: int = MAX_INCORRECT_GUESSES,
    ) -> None:
        word = word.strip().lower() if isinstance(word, str) else ""
        if not is_valid_word(word):
            raise ValueError("The hidden word must contain only the letters a-z")
        if max_incorrect < 1:
            raise ValueError("max_incorrect must be at least 1")

        self._word = word
        self.difficulty = normalize_difficulty(difficulty)
        self.max_incorrect = max_incorrect
        self._guessed: list[str] = []  # every accepted guess, in order

    @classmethod
    def new(cls, difficulty: str, word_manager: WordManager | None = None) -> "HangmanGame":
        """Start a game with a random word of the given difficulty."""
        manager = word_manager or WordManager()
        difficulty = normalize_difficulty(difficulty)
        return cls(manager.random_word(difficulty), difficulty=difficulty)

    # ------------------------------------------------------------------
    # Guessing

    @staticmethod
    def validate_letter(letter: object) -> str:
        """Return the guess as a lowercase letter, or raise InvalidGuessError."""
        if not isinstance(letter, str):
            raise InvalidGuessError("A guess must be a single letter")
        letter = letter.strip().lower()
        if len(letter) != 1 or letter not in string.ascii_lowercase:
            raise InvalidGuessError("A guess must be a single letter from A to Z")
        return letter

    def guess(self, letter: object) -> bool:
        """Guess one letter. Returns True if it is in the word, False otherwise.

        Raises GameOverError, InvalidGuessError, or DuplicateGuessError without
        changing the game state.
        """
        if self.is_over:
            raise GameOverError(f"The game is already over ({self.status})")
        letter = self.validate_letter(letter)
        if letter in self._guessed:
            raise DuplicateGuessError(f"'{letter}' has already been guessed")
        self._guessed.append(letter)
        return letter in self._word

    # ------------------------------------------------------------------
    # State

    @property
    def guessed_letters(self) -> list[str]:
        """All accepted guesses, in the order they were made."""
        return list(self._guessed)

    @property
    def correct_letters(self) -> list[str]:
        return [letter for letter in self._guessed if letter in self._word]

    @property
    def incorrect_letters(self) -> list[str]:
        return [letter for letter in self._guessed if letter not in self._word]

    @property
    def incorrect_count(self) -> int:
        return len(self.incorrect_letters)

    @property
    def remaining_guesses(self) -> int:
        return max(self.max_incorrect - self.incorrect_count, 0)

    @property
    def pattern(self) -> str:
        """The word with unguessed letters masked, e.g. ``"_ e _ _ e"``."""
        return " ".join(c if c in self._guessed else MASK_CHAR for c in self._word)

    @property
    def word_length(self) -> int:
        return len(self._word)

    @property
    def is_won(self) -> bool:
        return all(c in self._guessed for c in self._word)

    @property
    def is_lost(self) -> bool:
        return not self.is_won and self.incorrect_count >= self.max_incorrect

    @property
    def is_over(self) -> bool:
        return self.is_won or self.is_lost

    @property
    def status(self) -> str:
        if self.is_won:
            return WON
        if self.is_lost:
            return LOST
        return PLAYING

    @property
    def answer(self) -> str | None:
        """The hidden word once the game is over; None while it is in progress."""
        return self._word if self.is_over else None

    def to_dict(self) -> dict:
        """A client-safe snapshot of the game.

        ``word`` is present only after the game has ended, so this is safe to
        send to any client at any time.
        """
        state = {
            "difficulty": self.difficulty,
            "pattern": self.pattern,
            "word_length": self.word_length,
            "guessed_letters": self.guessed_letters,
            "correct_letters": self.correct_letters,
            "incorrect_letters": self.incorrect_letters,
            "max_incorrect": self.max_incorrect,
            "remaining_guesses": self.remaining_guesses,
            "status": self.status,
        }
        if self.is_over:
            state["word"] = self._word
        return state

    def __repr__(self) -> str:
        # Deliberately omits the hidden word so it can't leak through logs.
        return (
            f"HangmanGame(difficulty={self.difficulty!r}, pattern={self.pattern!r}, "
            f"remaining_guesses={self.remaining_guesses}, status={self.status!r})"
        )

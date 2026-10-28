# Hangman

A web-based Hangman game: a Python server that owns all game logic, and a
browser client that talks to it over a REST API.

Scope for this assignment: **the Hangman server and browser client only**.
The terminal client, automated bots, evaluation mode, scoring, and leaderboard
described in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) are intentionally
out of scope.

## Status

| Part | Description | Status |
| ---- | ----------- | ------ |
| A | Game engine (`game.py`, `words.py`, `words/`) | Done |
| B | REST server | Not started |
| C | Browser client | Not started |

## Requirements

Python 3.10+. Part A uses only the standard library.

## Project layout

```
game.py          HangmanGame engine (no web/UI dependencies)
words.py         WordManager: loads word lists, picks random words
words/           easy.txt, medium.txt, hard.txt (one word per line, # comments)
tests/           unittest suites
docs/            Original specification and TODO (reference material)
```

## Game engine

```python
from game import HangmanGame, DuplicateGuessError, InvalidGuessError, GameOverError

game = HangmanGame.new("medium")   # random word from words/medium.txt
game.guess("e")                    # True if the letter is in the word
game.pattern                       # "_ e _ _ e _"
game.remaining_guesses             # 6 minus incorrect guesses
game.status                        # "playing", "won", or "lost"
game.to_dict()                     # client-safe state; "word" only once the game ends
```

Rules:

- Difficulties: `easy`, `medium`, `hard` (case-insensitive). Anything else
  raises `InvalidDifficultyError`. Difficulty selects the word list; every game
  allows six incorrect guesses.
- A guess must be exactly one letter A–Z (case-insensitive) or it raises
  `InvalidGuessError`.
- Repeating a letter raises `DuplicateGuessError`.
- Any guess after the game is won or lost raises `GameOverError`.
- Rejected guesses never change the game state or cost a life.
- The hidden word is never in `to_dict()` or `repr()` while the game is
  being played.

Word lists ignore blank lines and `#` comments, lowercase every word, drop
duplicates, and refuse to load if any entry isn't purely alphabetic.

## Running the tests

```bash
python3 -m unittest discover -s tests -t .
```

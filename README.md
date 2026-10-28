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
| B | Flask server and REST API (`server.py`) | Done |
| C | Browser client (`static/`) | Done |
| D | Automated tests: engine, API, and browser | Done |

## Requirements

Python 3.10+ and Flask.

```bash
pip install -r requirements.txt
```

## Running the server

```bash
python3 server.py
```

Then open `http://127.0.0.1:5000` in a browser to play. The server listens
on `http://127.0.0.1:5000` by default. Set `HOST`, `PORT`,
or `FLASK_DEBUG=1` to change that.

## Project layout

```
server.py        Flask app and REST API; serves the browser client at /
static/          Browser client: index.html, style.css, app.js
game.py          HangmanGame engine (no web/UI dependencies)
words.py         WordManager: loads word lists, picks random words
words/           easy.txt, medium.txt, hard.txt (one word per line, # comments)
tests/           unittest suites, including Playwright browser tests
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

## Browser client

- Pick Easy, Medium, or Hard and press **New game**.
- Guess by clicking a letter or typing it. Guessed keys turn green (hit) or
  red (miss) and are disabled.
- The page shows the word pattern, guessed letters, misses, incorrect guesses
  left, and an SVG gallows that gains a body part with every miss.
- When the game ends, a win or loss message shows the word. Press **Enter**
  or **New game** to play again without reloading.
- Reloading the tab resumes the current game.

The client has no game rules of its own. It sends each guess to
`POST /api/games/{id}/guess` with `fetch()` and redraws from the server's
response, so it never holds the hidden word while a game is in progress.

## REST API

All requests and responses are JSON. Games are kept in server memory (the
oldest are discarded past 10,000) and are lost when the server restarts.

| Method | Endpoint | Purpose | Success |
| ------ | -------- | ------- | ------- |
| POST | `/api/games` | Create a game | 201 |
| GET | `/api/games/{game_id}` | Current game state | 200 |
| POST | `/api/games/{game_id}/guess` | Guess one letter | 200 |

### Create a game

```bash
curl -X POST http://127.0.0.1:5000/api/games \
  -H 'Content-Type: application/json' -d '{"difficulty": "easy"}'
```

`difficulty` is `easy`, `medium`, or `hard` and defaults to `medium`.

```json
{
  "game_id": "8edbb01832e54423b4f13ce3a5f8bcda",
  "difficulty": "easy",
  "pattern": "_ _ _ _ _",
  "word_length": 5,
  "guessed_letters": [],
  "correct_letters": [],
  "incorrect_letters": [],
  "max_incorrect": 6,
  "remaining_guesses": 6,
  "status": "playing"
}
```

### Guess a letter

```bash
curl -X POST http://127.0.0.1:5000/api/games/GAME_ID/guess \
  -H 'Content-Type: application/json' -d '{"letter": "e"}'
```

Returns the game state plus `"correct": true|false`. When `status` becomes
`won` or `lost`, the state also contains `"word"`. While the game is
`playing`, the word is never sent.

### Errors

Errors use a consistent body. Guess errors also include the current game
state under `"game"`.

```json
{"error": {"code": "duplicate_guess", "message": "'e' has already been guessed"}}
```

| Status | Code | When |
| ------ | ---- | ---- |
| 400 | `invalid_difficulty` | Difficulty isn't easy, medium, or hard |
| 400 | `invalid_guess` | Letter isn't exactly one character A–Z |
| 400 | `missing_letter` | Guess body has no `letter` |
| 400 | `malformed_json` | Body isn't valid JSON |
| 400 | `invalid_request` | Body isn't an object, or has unknown fields |
| 404 | `game_not_found` | Unknown game ID |
| 404 | `not_found` | Unknown route |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `duplicate_guess` | Letter already guessed |
| 409 | `game_over` | Game already won or lost |
| 415 | `unsupported_media_type` | Body sent without `Content-Type: application/json` |

## Branches

Each part is developed on its own branch off `main`, named
`feature/part-<letter>-<short-description>`:

| Part | Branch |
| ---- | ------ |
| A | merged to `main` before this scheme was adopted |
| B | `feature/part-b-flask-rest-api` |
| C | `feature/part-c-browser-client` |
| D | `feature/part-d-testing` |

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -t . -v
```

The browser tests are skipped if Playwright isn't installed. See
[`docs/TESTING.md`](docs/TESTING.md) for what each suite covers, coverage
commands, and a manual browser checklist.

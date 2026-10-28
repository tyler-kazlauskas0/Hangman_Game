# Testing

The project has four automated test suites (Python `unittest`, no extra test
runner needed) plus a short manual checklist.

| Suite | What it covers | Needs |
| ----- | -------------- | ----- |
| `tests/test_game.py` | `HangmanGame` engine rules | stdlib |
| `tests/test_words.py` | Word list loading and random selection | stdlib |
| `tests/test_server.py` | Each REST endpoint, status codes, error bodies | Flask |
| `tests/test_api_flows.py` | Full games over the API, invalid requests, hidden-word leaks | Flask |
| `tests/test_browser.py` | The real web page in headless Chromium against a live server | Playwright |

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -t . -v
```

Without Playwright, the browser suite is skipped and everything else still runs.

Coverage:

```bash
python -m coverage run --include=game.py,words.py,server.py -m unittest discover -s tests -t .
python -m coverage report -m
```

GitHub Actions runs every suite, including the browser tests, on each push
and pull request (`.github/workflows/tests.yml`).

### How the browser tests work

`tests/test_browser.py` starts the Flask app on a random local port in a
background thread, using one known word per difficulty (`zebra`, `jukebox`,
`quixotic`) so each test knows the answer. Playwright drives Chromium like a
player would: choosing a difficulty, clicking letter buttons, typing on the
keyboard, and pressing Enter. It records every API response the page receives.

After each guess, `assert_board_matches_server()` compares everything on screen
with the server's latest response: the pattern slots, guesses left, guessed
letters, misses, how many body parts are drawn, and each key's colour and
disabled state.

## Requirement coverage

| Requirement | Engine | API | Browser |
| ----------- | ------ | --- | ------- |
| Start games at all three difficulty levels | `DifficultyTests` | `DifficultyFlowTests`, `BundledWordFlowTests` | `StartGameTests.test_start_each_difficulty` |
| Correct and incorrect guesses | `GuessTests` | `GuessFlowTests.test_correct_then_incorrect_guesses` | `GuessTests.test_correct_guess_by_click`, `test_incorrect_guess_by_keyboard` |
| Repeated or invalid guesses | `GuessTests.test_duplicate_*`, `test_invalid_*` | `GuessFlowTests.test_repeated_and_invalid_guesses_do_not_change_state` | `GuessTests.test_repeated_guess_sends_no_request`, `test_invalid_keys_are_ignored`, `test_server_rejection_is_shown` |
| Winning and losing | `WinLossTests` | `GuessFlowTests.test_win`, `test_lose`, `DifficultyFlowTests.test_win_at_each_difficulty` | `WinLossTests` |
| No guesses after the game ends | `WinLossTests.test_no_guesses_after_*` | `test_server.py` `test_win_reveals_word_and_blocks_more_guesses` | `WinLossTests.test_typing_after_game_over_sends_nothing` |
| New game after completing one | `NewGameAfterFinishTests` | `GuessFlowTests.test_new_game_after_*` | `NewGameAfterFinishTests` (button and Enter, no reload) |
| Invalid API requests | n/a | `InvalidRequestTests`, `UnexpectedErrorTests`, `test_server.py` | n/a |
| Hidden word not exposed while playing | `SecrecyTests`, `SerializationTests` | `HiddenWordTests` (every create, guess, GET, 400 and 409 response) | `HiddenWordTests` (page HTML, visible text, browser storage, every API response) |
| Browser updates correctly after each guess | n/a | n/a | `GuessTests.test_board_updates_after_every_guess`, plus `assert_board_matches_server()` in most tests |
| Mobile layout | n/a | n/a | `MobileLayoutTests` |

## Checking that the tests catch bugs

Each of these deliberate bugs was introduced temporarily to confirm the suites
fail, then reverted:

| Bug introduced | Result |
| -------------- | ------ |
| Drawing shows one body part too many (`app.js`) | 20 browser test failures |
| "Incorrect guesses left" never updates (`app.js`) | 11 browser test failures |
| `to_dict()` always includes the word (`game.py`) | 46 failures across engine, API, and browser suites |

Writing the API tests also found a real bug, which is now fixed: a request
body of JSON `null` was reported as `malformed_json` instead of
`invalid_request`.

## Manual browser checklist

The automated suite covers these, but they are worth a quick look by eye in
a real browser after visual changes. Run `python3 server.py` and open
`http://127.0.0.1:5000`.

- [ ] Each difficulty starts a game with a word of a fitting length.
- [ ] Clicking a correct letter fills every matching slot and turns the key green.
- [ ] Typing a wrong letter turns the key red, adds a body part, and lowers the count.
- [ ] Typing a used letter, a digit, or punctuation does nothing.
- [ ] Winning shows a green message with the word; all keys are disabled.
- [ ] Losing draws the full figure and shows the word with missed letters in red.
- [ ] Enter or **New game** starts a fresh game without reloading the page.
- [ ] Reloading mid-game resumes the same game.
- [ ] Narrow the window to phone width: no sideways scrolling, keyboard wraps.
- [ ] With the system set to dark mode, the page uses its dark colours.
- [ ] In DevTools → Network, no response contains `"word"` while a game is playing.

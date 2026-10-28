// Browser client for the Hangman REST API.
//
// This file contains no game rules. Every guess is sent to the Flask server,
// which decides whether it is correct and returns the new state. The hidden
// word only ever reaches the browser after the server reports the game over.

"use strict";

const ALPHABET = "abcdefghijklmnopqrstuvwxyz";
const GAME_KEY = "hangman.gameId";
const DIFFICULTY_KEY = "hangman.difficulty";

const els = {
  form: document.getElementById("new-game-form"),
  difficulty: document.getElementById("difficulty"),
  newGame: document.getElementById("new-game"),
  pattern: document.getElementById("pattern"),
  remaining: document.getElementById("remaining"),
  guessed: document.getElementById("guessed"),
  incorrect: document.getElementById("incorrect"),
  message: document.getElementById("message"),
  keyboard: document.getElementById("keyboard"),
  gallowsTitle: document.getElementById("gallows-title"),
  parts: Array.from(document.querySelectorAll("#gallows .part")),
};

let game = null;   // last state returned by the server
let busy = false;  // true while a request is in flight

// --- storage helpers (per-browser conveniences; failures are harmless) ---

function load(key) {
  try { return sessionStorage.getItem(key) || localStorage.getItem(key); } catch { return null; }
}
function save(storage, key, value) {
  try { value == null ? storage.removeItem(key) : storage.setItem(key, value); } catch { /* ignore */ }
}

// --- API ---

class ApiError extends Error {
  constructor(status, body) {
    super(body?.error?.message || `Request failed (${status})`);
    this.status = status;
    this.code = body?.error?.code;
    this.game = body?.game;
  }
}

async function api(method, path, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, { error: { message: "Can't reach the server. Is it running?" } });
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

async function run(task) {
  if (busy) return;
  busy = true;
  setControlsDisabled(true);
  try {
    await task();
  } catch (err) {
    if (err.game) render(err.game);
    showMessage(err.message, "error");
  } finally {
    busy = false;
    setControlsDisabled(false);
  }
}

function startGame() {
  return run(async () => {
    const difficulty = els.difficulty.value;
    save(localStorage, DIFFICULTY_KEY, difficulty);
    const state = await api("POST", "/api/games", { difficulty });
    save(sessionStorage, GAME_KEY, state.game_id);
    render(state);
  });
}

function guess(letter) {
  if (!game || game.status !== "playing" || game.guessed_letters.includes(letter)) return;
  return run(async () => {
    render(await api("POST", `/api/games/${encodeURIComponent(game.game_id)}/guess`, { letter }));
  });
}

// Resume the game from this tab after a reload, or start a fresh one.
async function resumeOrStart() {
  const id = load(GAME_KEY);
  if (id) {
    try {
      const state = await api("GET", `/api/games/${encodeURIComponent(id)}`);
      els.difficulty.value = state.difficulty;
      render(state);
      return;
    } catch {
      save(sessionStorage, GAME_KEY, null);
    }
  }
  await startGame();
}

// --- rendering ---

function render(state) {
  game = state;
  const over = state.status !== "playing";

  // Pattern: one slot per letter. After a loss the server sends the word,
  // and the letters the player missed are highlighted.
  const slots = state.pattern.split(" ");
  els.pattern.replaceChildren(...slots.map((ch, i) => {
    const slot = document.createElement("span");
    slot.className = "slot";
    if (ch === "_" && state.word) {
      slot.textContent = state.word[i];
      slot.classList.add("missed");
    } else {
      slot.textContent = ch === "_" ? "" : ch;
    }
    return slot;
  }));
  els.pattern.setAttribute(
    "aria-label",
    `Word pattern: ${slots.map((ch) => (ch === "_" ? "blank" : ch)).join(" ")}`,
  );

  els.remaining.textContent = state.remaining_guesses;
  els.guessed.textContent = state.guessed_letters.join(" ") || "–";
  els.incorrect.textContent = state.incorrect_letters.join(" ") || "–";

  // Drawing: scale misses onto the six body parts.
  const misses = state.incorrect_letters.length;
  const shown = Math.min(
    els.parts.length,
    Math.round((misses * els.parts.length) / state.max_incorrect),
  );
  els.parts.forEach((part, i) => part.classList.toggle("shown", i < shown));
  els.gallowsTitle.textContent = `Hangman drawing: ${shown} of ${els.parts.length} parts`;

  for (const key of els.keyboard.children) {
    const letter = key.dataset.letter;
    key.classList.toggle("correct", state.correct_letters.includes(letter));
    key.classList.toggle("incorrect", state.incorrect_letters.includes(letter));
  }
  updateKeys();

  if (state.status === "won") {
    showMessage(`You won! The word was "${state.word.toUpperCase()}". Press Enter to play again.`, "won");
  } else if (state.status === "lost") {
    showMessage(`You lost. The word was "${state.word.toUpperCase()}". Press Enter to play again.`, "lost");
  } else {
    showMessage("", "");
  }
  if (over) els.newGame.focus();
}

function updateKeys() {
  const playing = game && game.status === "playing";
  for (const key of els.keyboard.children) {
    key.disabled = busy || !playing || game.guessed_letters.includes(key.dataset.letter);
  }
}

function setControlsDisabled(disabled) {
  els.newGame.disabled = disabled;
  updateKeys();
}

function showMessage(text, kind) {
  els.message.textContent = text;
  els.message.className = `message ${kind}`.trim();
}

// --- setup ---

function buildKeyboard() {
  for (const letter of ALPHABET) {
    const key = document.createElement("button");
    key.type = "button";
    key.className = "key";
    key.textContent = letter;
    key.dataset.letter = letter;
    key.setAttribute("aria-label", `Guess ${letter.toUpperCase()}`);
    key.addEventListener("click", () => guess(letter));
    els.keyboard.append(key);
  }
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  startGame();
});

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target instanceof HTMLSelectElement) return;
  const key = event.key.toLowerCase();
  if (key.length === 1 && ALPHABET.includes(key)) {
    event.preventDefault();
    guess(key);
  } else if (key === "enter" && game && game.status !== "playing"
             && !(event.target instanceof HTMLButtonElement)) {
    event.preventDefault();
    startGame();
  }
});

const savedDifficulty = load(DIFFICULTY_KEY);
if (["easy", "medium", "hard"].includes(savedDifficulty)) els.difficulty.value = savedDifficulty;
buildKeyboard();
resumeOrStart();

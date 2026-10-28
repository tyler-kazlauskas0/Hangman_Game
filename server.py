"""Flask server exposing the Hangman engine through a JSON REST API.

Endpoints:
    POST /api/games                   create a game           -> 201
    GET  /api/games/<game_id>         current game state      -> 200
    POST /api/games/<game_id>/guess   guess one letter        -> 200

The browser client (static/index.html, style.css, app.js) is served at ``/``
and talks to the server only through these endpoints. ``GET /healthz`` is a
health check for the hosting platform.

In production the app runs under gunicorn with a single worker process,
because games are stored in that process's memory (see render.yaml).

The server is authoritative: games live only in server memory, and the
hidden word is sent to clients only once a game has ended.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict

from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException

from game import (
    DuplicateGuessError,
    GameOverError,
    HangmanGame,
    InvalidGuessError,
)
from words import DEFAULT_DIFFICULTY, InvalidDifficultyError, WordManager

MAX_STORED_GAMES = 10_000


class ApiError(Exception):
    """An error that is returned to the client as a JSON response."""

    def __init__(self, status: int, code: str, message: str, game: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.game = game


class GameStore:
    """Thread-safe in-memory storage for active games.

    Each game gets a random, unguessable ID. When more than ``max_games``
    games exist, the oldest are discarded so memory use stays bounded.
    """

    def __init__(self, max_games: int = MAX_STORED_GAMES) -> None:
        self._games: OrderedDict[str, HangmanGame] = OrderedDict()
        self._max_games = max_games
        self.lock = threading.Lock()

    def add(self, game: HangmanGame) -> str:
        with self.lock:
            game_id = uuid.uuid4().hex
            while game_id in self._games:  # practically impossible, but cheap to guard
                game_id = uuid.uuid4().hex
            self._games[game_id] = game
            while len(self._games) > self._max_games:
                self._games.popitem(last=False)
            return game_id

    def get(self, game_id: str) -> HangmanGame | None:
        with self.lock:
            return self._games.get(game_id)

    def __len__(self) -> int:
        with self.lock:
            return len(self._games)


def game_response(game_id: str, game: HangmanGame) -> dict:
    return {"game_id": game_id, **game.to_dict()}


def read_json_object(allowed_fields: set[str]) -> dict:
    """Parse the request body as a JSON object containing only ``allowed_fields``.

    An empty body is treated as ``{}``.
    """
    if not request.get_data(cache=True):
        return {}
    if not request.is_json:
        raise ApiError(415, "unsupported_media_type", "Request body must be JSON (Content-Type: application/json)")
    try:
        body = request.get_json()
    except BadRequest as exc:
        raise ApiError(400, "malformed_json", "Request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object")
    unknown = sorted(set(body) - allowed_fields)
    if unknown:
        raise ApiError(400, "invalid_request", f"Unknown field(s): {', '.join(unknown)}")
    return body


def create_app(word_manager: WordManager | None = None, store: GameStore | None = None) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    word_manager = word_manager or WordManager()
    store = store if store is not None else GameStore()
    app.config["GAME_STORE"] = store

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/healthz")
    def health():
        """Used by the hosting platform to check the app is up."""
        return jsonify({"status": "ok"})

    @app.after_request
    def add_headers(response):
        # The page loads only its own files, so lock everything else out.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/"):
            # Game state changes with every guess; never serve it from a cache.
            response.headers["Cache-Control"] = "no-store"
        return response

    def find_game(game_id: str) -> HangmanGame:
        game = store.get(game_id)
        if game is None:
            raise ApiError(404, "game_not_found", f"No game with id {game_id!r}")
        return game

    @app.post("/api/games")
    def create_game():
        body = read_json_object({"difficulty"})
        difficulty = body.get("difficulty", DEFAULT_DIFFICULTY)
        try:
            game = HangmanGame.new(difficulty, word_manager)
        except InvalidDifficultyError as exc:
            raise ApiError(400, "invalid_difficulty", str(exc)) from exc
        game_id = store.add(game)
        response = jsonify(game_response(game_id, game))
        response.status_code = 201
        response.headers["Location"] = f"/api/games/{game_id}"
        return response

    @app.get("/api/games/<game_id>")
    def get_game(game_id: str):
        game = find_game(game_id)
        with store.lock:
            return jsonify(game_response(game_id, game))

    @app.post("/api/games/<game_id>/guess")
    def guess(game_id: str):
        game = find_game(game_id)
        body = read_json_object({"letter"})
        if "letter" not in body:
            raise ApiError(400, "missing_letter", "Request body must include \"letter\"")
        # Hold the lock so two simultaneous guesses on one game can't interleave.
        with store.lock:
            try:
                correct = game.guess(body["letter"])
            except InvalidGuessError as exc:
                raise ApiError(400, "invalid_guess", str(exc), game_response(game_id, game)) from exc
            except DuplicateGuessError as exc:
                raise ApiError(409, "duplicate_guess", str(exc), game_response(game_id, game)) from exc
            except GameOverError as exc:
                raise ApiError(409, "game_over", str(exc), game_response(game_id, game)) from exc
            return jsonify({**game_response(game_id, game), "correct": correct})

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        payload = {"error": {"code": exc.code, "message": exc.message}}
        if exc.game is not None:
            payload["game"] = exc.game
        return jsonify(payload), exc.status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        # Unknown routes, wrong methods, etc. still get a JSON body.
        code = (exc.name or "error").lower().replace(" ", "_")
        response = jsonify({"error": {"code": code, "message": exc.description}})
        response.status_code = exc.code or 500
        if exc.code == 405 and hasattr(exc, "valid_methods") and exc.valid_methods:
            response.headers["Allow"] = ", ".join(exc.valid_methods)
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        app.logger.exception("Unhandled error")
        return jsonify({"error": {"code": "internal_error", "message": "Internal server error"}}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )

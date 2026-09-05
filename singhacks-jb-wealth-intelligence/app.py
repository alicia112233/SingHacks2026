"""Local application server for TESSERA wealth decision intelligence."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tessera.evaluation import evaluate_recommendation
from tessera.retrieval import retrieval_configuration_status
from tessera.services import (
    MAX_REQUEST_BYTES,
    DecisionStore,
    IntelligenceService,
    create_decision_record,
)


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RUNTIME = ROOT / "runtime"
DECISION_FILE = RUNTIME / "decisions.json"
INTELLIGENCE = IntelligenceService(ROOT / "data")
DECISIONS = DecisionStore(DECISION_FILE)


def load_local_environment(path: Path = ROOT / ".env.local") -> tuple[str, ...]:
    """Load simple KEY=VALUE settings for ``python app.py`` local runs.

    Existing process environment variables always win, matching common dotenv
    behaviour without adding another runtime dependency.
    """

    if not path.is_file():
        return ()

    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key[0].isdigit() or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key not in os.environ and value:
            os.environ[key] = value
            loaded.append(key)
    return tuple(loaded)


class TesseraHandler(SimpleHTTPRequestHandler):
    server_version = "Tessera/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_index(self) -> None:
        encoded = (WEB / "index.html").read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path == "/api/intelligence":
            self._send_json(INTELLIGENCE.get())
            return
        if path == "/api/decisions":
            self._send_json(DECISIONS.snapshot())
            return
        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "tessera",
                    "vector_search": retrieval_configuration_status()["status"],
                }
            )
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return

        requested = (WEB / path.lstrip("/")).resolve()
        try:
            requested.relative_to(WEB.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        # Known static files are served normally. All extensionless paths fall
        # back to the application shell so copied client/studio links work.
        if path == "/" or (not requested.exists() and requested.suffix == ""):
            self._send_index()
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path not in {"/api/decisions", "/api/evaluations"}:
            self._send_json({"error": "Endpoint not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send_json({"error": "Invalid request size"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            intelligence = INTELLIGENCE.get()
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/evaluations":
                if not isinstance(body, dict):
                    raise ValueError("Request body must be an object")
                evaluation = evaluate_recommendation(
                    intelligence,
                    str(body.get("client_id", "")),
                    int(body.get("recommendation_index", -1)),
                )
                self._send_json(evaluation)
            else:
                record = create_decision_record(body, intelligence)
                self._send_json(DECISIONS.append(record), HTTPStatus.CREATED)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format, *args):  # noqa: A003
        print(f"TESSERA • {self.address_string()} • {format % args}")


def main() -> None:
    loaded_settings = load_local_environment()
    parser = argparse.ArgumentParser(description="Run the TESSERA application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), TesseraHandler)
    if loaded_settings:
        print(f"Loaded {len(loaded_settings)} setting(s) from .env.local")
    print(f"TESSERA is ready at http://{args.host}:{args.port} (application API enabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TESSERA")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""Local application server for TESSERA wealth decision intelligence."""

from __future__ import annotations

import argparse
import json
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tessera import build_intelligence_payload


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RUNTIME = ROOT / "runtime"
DECISION_FILE = RUNTIME / "decisions.json"
MAX_REQUEST_BYTES = 8_192
ALLOWED_DECISIONS = {"approved", "dismissed", "edited", "pending"}


class IntelligenceService:
    """Cache analytics until one of the controlled source files changes."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._payload: dict[str, Any] | None = None

    def _source_signature(self) -> tuple[tuple[str, int, int], ...]:
        files = sorted((*self.data_dir.glob("*.csv"), *self.data_dir.glob("*.json")))
        return tuple(
            (path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in files
        )

    def get(self) -> dict[str, Any]:
        signature = self._source_signature()
        with self._lock:
            if self._payload is None or signature != self._signature:
                self._payload = build_intelligence_payload(self.data_dir)
                self._signature = signature
            return self._payload


class DecisionStore:
    """Thread-safe append-only decision ledger persisted as JSON."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError("Decision ledger must contain a JSON array")
        return payload

    @staticmethod
    def _effective(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {record["recommendation_id"]: record for record in records}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = self._read_unlocked()
        return {"records": records, "effective": self._effective(records)}

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            records = self._read_unlocked()
            records.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        return {"record": record, "records": records, "effective": self._effective(records)}


INTELLIGENCE = IntelligenceService(ROOT / "data")
DECISIONS = DecisionStore(DECISION_FILE)


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
            self._send_json({"status": "ok", "service": "tessera"})
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
        if path != "/api/decisions":
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
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            client_id = str(body.get("client_id", ""))
            recommendation_index = int(body.get("recommendation_index", -1))
            action = str(body.get("action", "")).lower()
            note = str(body.get("note", "")).strip()

            intelligence = INTELLIGENCE.get()
            client = intelligence["featured_clients"].get(client_id)
            if client is None:
                raise ValueError("Unknown client")
            if recommendation_index < 0 or recommendation_index >= len(client["recommendations"]):
                raise ValueError("Unknown recommendation")
            if action not in ALLOWED_DECISIONS:
                raise ValueError("Unsupported decision")
            if len(note) > 1_000:
                raise ValueError("Note must be 1,000 characters or fewer")

            recommendation = client["recommendations"][recommendation_index]
            record = {
                "id": str(uuid.uuid4()),
                "recommendation_id": f"{client_id}:{recommendation_index}",
                "client_id": client_id,
                "client_name": client["name"],
                "recommendation_index": recommendation_index,
                "recommendation_title": recommendation["title"],
                "action": action,
                "note": note,
                "actor": intelligence["meta"]["rm"],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            self._send_json(DECISIONS.append(record), HTTPStatus.CREATED)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format, *args):  # noqa: A003
        print(f"TESSERA • {self.address_string()} • {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TESSERA application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), TesseraHandler)
    print(f"TESSERA is ready at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TESSERA")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

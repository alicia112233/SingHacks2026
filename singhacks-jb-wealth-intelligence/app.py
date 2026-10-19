"""Local application server for TESSERA wealth decision intelligence."""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tessera.chat import answer_chat, chat_configuration_status
from tessera.market_news import refresh as refresh_market_news
from tessera.notifications import (
    TelegramNotificationError,
    TelegramNotifier,
    UrgencyAlertStore,
    acknowledge_urgency_alert,
    scan_urgency_alerts,
)
from tessera.retrieval import retrieval_configuration_status
from tessera.services import (
    MAX_REQUEST_BYTES,
    DecisionStore,
    IntelligenceService,
    record_alternative,
    record_decision,
    record_evaluation,
    reviewed_snapshot,
    reviewed_intelligence,
)


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RUNTIME = ROOT / "runtime"
DECISION_FILE = RUNTIME / "decisions.json"
INTELLIGENCE = IntelligenceService(ROOT / "data")
DECISIONS = DecisionStore(DECISION_FILE)
LIVE_EVENTS = RUNTIME / "live_events.json"
URGENCY_ALERTS = UrgencyAlertStore(RUNTIME / "telegram_urgency_alerts.json")
URGENCY_MONITOR_STOP = threading.Event()


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
            self._send_json(reviewed_intelligence(INTELLIGENCE.get(), DECISIONS.snapshot()))
            return
        if path == "/api/decisions":
            self._send_json(reviewed_snapshot(DECISIONS.snapshot(), INTELLIGENCE.get()))
            return
        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "tessera",
                    "vector_search": retrieval_configuration_status()["status"],
                    "chat": chat_configuration_status()["status"],
                    "telegram_notifications": TelegramNotifier().configuration_status(),
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
        if path not in {"/api/decisions", "/api/evaluations", "/api/chat", "/api/recommendations/alternate", "/api/market-news/refresh", "/api/notifications/urgency/scan", "/api/notifications/urgency/acknowledge"}:
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
            if path == "/api/market-news/refresh":
                try:
                    result = refresh_market_news(ROOT / "data", LIVE_EVENTS)
                    result["intelligence"] = reviewed_intelligence(INTELLIGENCE.get(), DECISIONS.snapshot())
                    result["urgency_alerts"] = scan_urgency_alerts(
                        result["intelligence"], URGENCY_ALERTS
                    )
                    self._send_json(result)
                except TelegramNotificationError as error:
                    self._send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
                except (OSError, RuntimeError):
                    self._send_json({"error": "Market news is temporarily unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            elif path == "/api/notifications/urgency/scan":
                self._send_json(scan_urgency_alerts(intelligence, URGENCY_ALERTS))
            elif path == "/api/notifications/urgency/acknowledge":
                if not isinstance(body, dict):
                    raise ValueError("Request body must be an object")
                client_id = str(body.get("client_id", "")).strip()
                if not client_id:
                    raise ValueError("client_id is required")
                state = acknowledge_urgency_alert(
                    URGENCY_ALERTS, client_id, str(body.get("note", "")).strip()
                )
                self._send_json({"status": "acknowledged", "alert": state})
            elif path == "/api/chat":
                self._send_json(answer_chat(intelligence, body))
            elif path == "/api/recommendations/alternate":
                self._send_json(
                    record_alternative(
                        body, intelligence, DECISIONS
                    )
                )
            elif path == "/api/evaluations":
                self._send_json(record_evaluation(body, intelligence, DECISIONS))
            else:
                self._send_json(record_decision(body, intelligence, DECISIONS), HTTPStatus.CREATED)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except (OSError, RuntimeError) as error:
            self._send_json({"error": "Review storage is unavailable; no action was approved."}, HTTPStatus.SERVICE_UNAVAILABLE)
        except TelegramNotificationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)

    def log_message(self, format, *args):  # noqa: A003
        print(f"TESSERA • {self.address_string()} • {format % args}")


def main() -> None:
    loaded_settings = load_local_environment()
    parser = argparse.ArgumentParser(description="Run the TESSERA application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer((args.host, args.port), TesseraHandler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(
                f"TESSERA could not start: port {args.port} is already in use. "
                f"Stop the existing process or run with --port {args.port + 1}.",
                file=sys.stderr,
            )
            return
        raise
    if loaded_settings:
        print(f"Loaded {len(loaded_settings)} setting(s) from .env.local")
    monitor_thread = _start_urgency_monitor()
    print(f"TESSERA is ready at http://{args.host}:{args.port} (application API enabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TESSERA")
    finally:
        URGENCY_MONITOR_STOP.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=1)
        server.server_close()


def _start_urgency_monitor() -> threading.Thread | None:
    """Check urgent cases hourly while the local demo server is running."""

    enabled = os.environ.get("TESSERA_URGENCY_MONITOR_ENABLED", "true").lower()
    if enabled not in {"1", "true", "yes", "on"} or TelegramNotifier().configuration_status() != "configured":
        return None
    try:
        interval = max(60, int(os.environ.get("TESSERA_URGENCY_SCAN_INTERVAL_SECONDS", "3600")))
    except ValueError:
        interval = 3600

    def monitor() -> None:
        while not URGENCY_MONITOR_STOP.is_set():
            try:
                result = scan_urgency_alerts(INTELLIGENCE.get(), URGENCY_ALERTS)
                sent = result["initial"] + result["reminded"] + result["escalated"]
                if sent:
                    print(f"TESSERA • sent urgency alerts for {', '.join(sent)}")
            except TelegramNotificationError as error:
                print(f"TESSERA • urgency monitor: {error}", file=sys.stderr)
            except Exception as error:  # Keep the web server running if a scan fails.
                print(f"TESSERA • urgency monitor failed: {error}", file=sys.stderr)
            URGENCY_MONITOR_STOP.wait(interval)

    thread = threading.Thread(target=monitor, name="tessera-urgency-monitor", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    main()

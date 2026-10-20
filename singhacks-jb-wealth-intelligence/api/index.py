"""WSGI entrypoint for TESSERA's Vercel-hosted API."""

from __future__ import annotations

import hmac
import os
import tempfile
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from tessera.chat import answer_chat, chat_configuration_status
from tessera.notifications import (
    TelegramNotificationError,
    TelegramNotifier,
    acknowledge_urgency_alert,
    production_urgency_alert_store,
    scan_urgency_alerts,
)
from tessera.retrieval import retrieval_configuration_status
from tessera.services import (
    MAX_REQUEST_BYTES,
    review_context,
    refresh_market_intelligence,
    IntelligenceService,
    record_alternative,
    record_decision,
    record_escalation_review,
    record_evaluation,
    reviewed_snapshot,
    reviewed_intelligence,
    production_decision_store,
)


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LIVE_EVENTS = Path(tempfile.gettempdir()) / f"tessera-live-events-{os.getpid()}.json"
INTELLIGENCE = IntelligenceService(ROOT / "data", LIVE_EVENTS)
app = Flask(__name__, static_folder=str(WEB), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


@lru_cache(maxsize=1)
def decision_store():
    return production_decision_store()


def current_intelligence():
    if not os.environ.get("DATABASE_URL"):
        try:
            store = decision_store()
        except RuntimeError:
            return INTELLIGENCE.get()
    else:
        store = decision_store()
    return reviewed_intelligence(INTELLIGENCE.get(), store.snapshot())


@lru_cache(maxsize=1)
def urgency_alert_store():
    return production_urgency_alert_store()


@app.after_request
def secure_json(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def application_shell():
    return send_from_directory(WEB, "index.html")


@app.get("/clients/<path:client_id>")
@app.get("/all-clients")
@app.get("/market-events")
@app.get("/scenario-studio")
@app.get("/evidence-ledger")
def application_route(client_id: str | None = None):
    del client_id
    return send_from_directory(WEB, "index.html")


@app.get("/favicon.ico")
def favicon():
    return "", HTTPStatus.NO_CONTENT


@app.get("/api/intelligence")
def intelligence():
    try:
        return jsonify(current_intelligence())
    except Exception:
        return jsonify(error="Current portfolio intelligence could not be prepared."), HTTPStatus.INTERNAL_SERVER_ERROR


@app.get("/api/review")
def get_review():
    try:
        return jsonify(review_context(INTELLIGENCE.get(), decision_store()))
    except Exception:
        return jsonify(error="The current review could not be loaded."), HTTPStatus.SERVICE_UNAVAILABLE


@app.get("/api/decisions")
def get_decisions():
    try:
        return jsonify(reviewed_snapshot(decision_store().snapshot(), INTELLIGENCE.get()))
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The decision ledger is temporarily unavailable."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/decisions")
def post_decision():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        intelligence = INTELLIGENCE.get()
        store = decision_store()
        return jsonify(record_decision(body, intelligence, store)), HTTPStatus.CREATED
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The decision could not be recorded."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/escalations/review")
def post_escalation_review():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        return jsonify(record_escalation_review(body, INTELLIGENCE.get(), decision_store())), HTTPStatus.CREATED
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The breach review could not be recorded."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/recommendations/alternate")
def post_alternate_recommendation():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        return jsonify(
            record_alternative(
                body, INTELLIGENCE.get(), decision_store()
            )
        )
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Alternative recommendation generation failed")
        return jsonify(error="A replacement recommendation could not be generated."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/evaluations")
def post_evaluation():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        if not isinstance(body, dict):
            raise ValueError("Request body must be an object")
        return jsonify(record_evaluation(body, INTELLIGENCE.get(), decision_store()))

    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Independent recommendation evaluation failed")
        return jsonify(error="The independent evaluation could not be completed."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/chat")
def post_chat():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        return jsonify(answer_chat(INTELLIGENCE.get(), body))
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Evidence assistant failed")
        return jsonify(error="The evidence assistant is temporarily unavailable."), HTTPStatus.SERVICE_UNAVAILABLE


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="tessera",
        decision_storage="configured" if os.environ.get("DATABASE_URL") else "not_configured",
        vector_search=retrieval_configuration_status()["status"],
        chat=chat_configuration_status()["status"],
        telegram_notifications=TelegramNotifier().configuration_status(),
    )


@app.post("/api/market-news/refresh")
def market_news_refresh():
    try:
        return jsonify(refresh_market_intelligence(ROOT / "data", LIVE_EVENTS, current_intelligence, urgency_alert_store))
    except Exception:
        app.logger.exception("Market-news refresh failed")
        return jsonify(error="The market-news refresh could not be completed."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/notifications/urgency/scan")
def urgency_notification_scan():
    """Run the score threshold check on demand or from a scheduler."""

    try:
        return jsonify(scan_urgency_alerts(INTELLIGENCE.get(), urgency_alert_store()))
    except TelegramNotificationError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Urgency-notification scan failed")
        return jsonify(error="Urgency notifications are temporarily unavailable."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/notifications/urgency/acknowledge")
def acknowledge_urgency_notification():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("Request body must be an object")
        client_id = str(body.get("client_id", "")).strip()
        if not client_id:
            raise ValueError("client_id is required")
        state = acknowledge_urgency_alert(
            urgency_alert_store(), client_id, str(body.get("note", "")).strip()
        )
        return jsonify(status="acknowledged", alert=state)
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Urgency acknowledgement failed")
        return jsonify(error="The urgency acknowledgement could not be saved."), HTTPStatus.SERVICE_UNAVAILABLE


@app.get("/api/cron/urgency-alerts")
def scheduled_urgency_scan():
    """Vercel Cron entrypoint: one daily reminder/escalation scan."""

    secret = os.environ.get("CRON_SECRET", "")
    expected = f"Bearer {secret}"
    if not secret or not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
        return jsonify(error="Unauthorized"), HTTPStatus.UNAUTHORIZED
    try:
        return jsonify(scan_urgency_alerts(INTELLIGENCE.get(), urgency_alert_store()))
    except TelegramNotificationError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        app.logger.exception("Scheduled urgency scan failed")
        return jsonify(error="Scheduled urgency scan is temporarily unavailable."), HTTPStatus.SERVICE_UNAVAILABLE

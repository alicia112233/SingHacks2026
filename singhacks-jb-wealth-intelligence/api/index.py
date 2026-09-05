"""WSGI entrypoint for TESSERA's Vercel-hosted API."""

from __future__ import annotations

import os
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from tessera.services import (
    MAX_REQUEST_BYTES,
    IntelligenceService,
    create_decision_record,
    production_decision_store,
)


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INTELLIGENCE = IntelligenceService(ROOT / "data")
app = Flask(__name__, static_folder=str(WEB), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


@lru_cache(maxsize=1)
def decision_store():
    return production_decision_store()


@app.after_request
def secure_json(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def application_shell():
    return send_from_directory(WEB, "index.html")


@app.get("/clients/<path:client_id>")
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
        return jsonify(INTELLIGENCE.get())
    except Exception:
        return jsonify(error="Current portfolio intelligence could not be prepared."), HTTPStatus.INTERNAL_SERVER_ERROR


@app.get("/api/decisions")
def get_decisions():
    try:
        return jsonify(decision_store().snapshot())
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The decision ledger is temporarily unavailable."), HTTPStatus.SERVICE_UNAVAILABLE


@app.post("/api/decisions")
def post_decision():
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    try:
        record = create_decision_record(request.get_json(), INTELLIGENCE.get())
        return jsonify(decision_store().append(record)), HTTPStatus.CREATED
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The decision could not be recorded."), HTTPStatus.SERVICE_UNAVAILABLE


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="tessera",
        decision_storage="configured" if os.environ.get("DATABASE_URL") else "not_configured",
    )
"""WSGI entrypoint for TESSERA's Vercel-hosted API."""

from __future__ import annotations

import os
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from tessera.evaluation import evaluate_recommendation
from tessera.retrieval import retrieval_configuration_status
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
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("Request body must be valid JSON")
        record = create_decision_record(body, INTELLIGENCE.get())
        return jsonify(decision_store().append(record)), HTTPStatus.CREATED
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except RuntimeError as error:
        return jsonify(error=str(error)), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception:
        return jsonify(error="The decision could not be recorded."), HTTPStatus.SERVICE_UNAVAILABLE


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
        client_id = str(body.get("client_id", ""))
        recommendation_index = int(body.get("recommendation_index", -1))
        return jsonify(
            evaluate_recommendation(
                INTELLIGENCE.get(), client_id, recommendation_index
            )
        )
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), HTTPStatus.BAD_REQUEST
    except Exception:
        app.logger.exception("Independent recommendation evaluation failed")
        return jsonify(error="The independent evaluation could not be completed."), HTTPStatus.SERVICE_UNAVAILABLE


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="tessera",
        decision_storage="configured" if os.environ.get("DATABASE_URL") else "not_configured",
        vector_search=retrieval_configuration_status()["status"],
    )

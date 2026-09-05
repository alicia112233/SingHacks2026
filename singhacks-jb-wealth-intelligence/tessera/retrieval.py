"""Purpose-limited semantic retrieval backed by Chroma Cloud.

Structured portfolio calculations remain in :mod:`tessera.engine`. This module
only retrieves short, source-labelled passages that can supplement the existing
evidence packet used by recommendation reviewers.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen


GATEWAY_EMBEDDINGS_URL = "https://ai-gateway.vercel.sh/v1/embeddings"
DEFAULT_COLLECTION = "tessera-knowledge-v1"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
CORPUS = "tessera-controlled-v1"
REQUIRED_CHROMA_SETTINGS = ("CHROMA_API_KEY", "CHROMA_TENANT", "CHROMA_DATABASE")


def _enabled() -> bool:
    return os.environ.get("TESSERA_RETRIEVAL_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _gateway_token() -> str:
    return (
        os.environ.get("AI_GATEWAY_API_KEY", "").strip()
        or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
    )


def retrieval_configuration_status() -> dict[str, Any]:
    """Describe configuration without making a network request or exposing secrets."""

    if not _enabled():
        return {
            "status": "disabled",
            "configured": False,
            "reason": "Set TESSERA_RETRIEVAL_ENABLED=true after adding Chroma credentials.",
        }
    missing = [name for name in REQUIRED_CHROMA_SETTINGS if not os.environ.get(name, "").strip()]
    if not _gateway_token():
        missing.append("AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN")
    if missing:
        return {
            "status": "not_configured",
            "configured": False,
            "reason": "Missing " + ", ".join(missing) + ".",
        }
    return {
        "status": "configured",
        "configured": True,
        "reason": "Chroma Cloud retrieval and embedding credentials are configured.",
    }


class GatewayEmbeddingClient:
    """Generate explicit embeddings through Vercel's OpenAI-compatible gateway."""

    def __init__(self, model: str | None = None, token: str | None = None):
        self.model = model or os.environ.get(
            "TESSERA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
        )
        self.token = token or _gateway_token()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.token:
            raise RuntimeError("AI Gateway authentication is not configured")
        request = Request(
            GATEWAY_EMBEDDINGS_URL,
            data=json.dumps({"model": self.model, "input": texts}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            payload = json.load(response)
        rows = sorted(payload.get("data", []), key=lambda item: int(item.get("index", 0)))
        embeddings = [row.get("embedding") for row in rows]
        if len(embeddings) != len(texts) or any(not isinstance(item, list) for item in embeddings):
            raise RuntimeError("Embedding provider returned an incomplete response")
        return embeddings


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    text: str
    metadata: dict[str, str | int | float | bool]


def _clean_metadata(values: dict[str, Any]) -> dict[str, str | int | float | bool]:
    return {
        str(key): value
        for key, value in values.items()
        if value is not None and value != "" and isinstance(value, (str, int, float, bool))
    }


def build_knowledge_documents(data_dir: str | Path) -> list[KnowledgeDocument]:
    """Convert controlled narrative sources into short, traceable search documents."""

    data_path = Path(data_dir)
    documents: list[KnowledgeDocument] = []

    with (data_path / "rm_notes.json").open(encoding="utf-8") as handle:
        notes = json.load(handle)
    for note in notes:
        source_ref = f"rm_notes.json • {note['note_id']}"
        documents.append(
            KnowledgeDocument(
                id=f"rm-note:{note['note_id']}",
                text=(
                    f"Relationship manager note dated {note['note_date']} via "
                    f"{note['channel']}. {note['note']}"
                ),
                metadata=_clean_metadata(
                    {
                        "corpus": CORPUS,
                        "source_type": "rm_note",
                        "source_ref": source_ref,
                        "source_date": note["note_date"],
                        "client_id": note["client_id"],
                        "sensitivity": "confidential",
                    }
                ),
            )
        )

    def rows(name: str) -> Iterable[dict[str, str]]:
        with (data_path / name).open(encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)

    for index, event in enumerate(rows("event_log.csv")):
        source_ref = f"event_log.csv • {event['event_date']} • row {index + 2}"
        documents.append(
            KnowledgeDocument(
                id=f"event:{event['event_date']}:{index}",
                text=(
                    f"Controlled {event['event_type']} event for {event['region']} dated "
                    f"{event['event_date']}. {event['description']} Transmission: "
                    f"{event['primary_transmission']}. Severity: {event['severity']}."
                ),
                metadata=_clean_metadata(
                    {
                        "corpus": CORPUS,
                        "source_type": "controlled_event",
                        "source_ref": source_ref,
                        "source_date": event["event_date"],
                        "client_id": "GLOBAL",
                        "region": event["region"],
                        "severity": event["severity"],
                        "sensitivity": "internal",
                    }
                ),
            )
        )

    for mandate in rows("mandates.csv"):
        key = f"{mandate['mandate_code']}:{mandate['asset_class']}"
        source_ref = f"mandates.csv • {key}"
        documents.append(
            KnowledgeDocument(
                id=f"mandate:{key}",
                text=(
                    f"{mandate['mandate_name']} mandate, {mandate['asset_class']}: "
                    f"minimum {mandate['min_pct']}%, target {mandate['target_pct']}%, "
                    f"maximum {mandate['max_pct']}%, maximum single position "
                    f"{mandate['max_single_position_pct']}%. {mandate['mandate_notes']}"
                ),
                metadata=_clean_metadata(
                    {
                        "corpus": CORPUS,
                        "source_type": "mandate_rule",
                        "source_ref": source_ref,
                        "client_id": "GLOBAL",
                        "mandate_code": mandate["mandate_code"],
                        "asset_class": mandate["asset_class"],
                        "sensitivity": "internal",
                    }
                ),
            )
        )

    for instrument in rows("instruments.csv"):
        source_ref = f"instruments.csv • {instrument['instrument_id']}"
        documents.append(
            KnowledgeDocument(
                id=f"instrument:{instrument['instrument_id']}",
                text=(
                    f"Instrument {instrument['instrument_name']}. Asset class "
                    f"{instrument['asset_class']}; sub-asset class "
                    f"{instrument['sub_asset_class']}; sector {instrument['sector']}; "
                    f"region {instrument['region']}; currency {instrument['currency']}; "
                    f"liquidity {instrument['liquidity_tier']}; underlying reference "
                    f"{instrument.get('underlying_reference') or 'none recorded'}; "
                    f"sustainability excluded {instrument['sustainability_excluded']}."
                ),
                metadata=_clean_metadata(
                    {
                        "corpus": CORPUS,
                        "source_type": "instrument_reference",
                        "source_ref": source_ref,
                        "client_id": "GLOBAL",
                        "instrument_id": instrument["instrument_id"],
                        "asset_class": instrument["asset_class"],
                        "region": instrument["region"],
                        "sensitivity": "internal",
                    }
                ),
            )
        )
    return documents


class ChromaKnowledgeService:
    """Small CloudClient wrapper with mandatory client-scope filtering."""

    def __init__(self, client: Any | None = None, embedder: GatewayEmbeddingClient | None = None):
        self._provided_client = client
        self.embedder = embedder or GatewayEmbeddingClient()

    def _client(self):
        if self._provided_client is not None:
            return self._provided_client
        try:
            import chromadb
        except ImportError as error:
            raise RuntimeError("The chromadb-client dependency is not installed") from error
        kwargs: dict[str, Any] = {
            "api_key": os.environ["CHROMA_API_KEY"],
            "tenant": os.environ["CHROMA_TENANT"],
            "database": os.environ["CHROMA_DATABASE"],
        }
        host = os.environ.get("CHROMA_HOST", "").strip()
        if host:
            kwargs["cloud_host"] = host
            kwargs["cloud_port"] = 443
        return chromadb.CloudClient(**kwargs)

    def _collection(self):
        return self._client().get_or_create_collection(
            name=os.environ.get("CHROMA_COLLECTION", DEFAULT_COLLECTION),
            embedding_function=None,
        )

    def index(self, documents: list[KnowledgeDocument], prune: bool = True) -> dict[str, int]:
        collection = self._collection()
        for start in range(0, len(documents), 32):
            batch = documents[start : start + 32]
            collection.upsert(
                ids=[item.id for item in batch],
                documents=[item.text for item in batch],
                metadatas=[item.metadata for item in batch],
                embeddings=self.embedder.embed([item.text for item in batch]),
            )
        removed = 0
        if prune:
            existing = collection.get(where={"corpus": CORPUS}, include=[]).get("ids", [])
            stale = sorted(set(existing) - {item.id for item in documents})
            if stale:
                collection.delete(ids=stale)
                removed = len(stale)
        return {"indexed": len(documents), "removed": removed}

    def search(
        self,
        query: str,
        client_id: str,
        as_of: str | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        collection = self._collection()
        response = collection.query(
            query_embeddings=self.embedder.embed([query]),
            n_results=max(limit * 3, limit),
            where={
                "$and": [
                    {"corpus": {"$eq": CORPUS}},
                    {
                        "$or": [
                            {"client_id": {"$eq": client_id}},
                            {"client_id": {"$eq": "GLOBAL"}},
                        ]
                    },
                ]
            },
            include=["documents", "metadatas", "distances"],
        )
        ids = (response.get("ids") or [[]])[0]
        texts = (response.get("documents") or [[]])[0]
        metadata = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]
        evidence: list[dict[str, Any]] = []
        for item_id, text, meta, distance in zip(ids, texts, metadata, distances):
            source_date = str((meta or {}).get("source_date", ""))
            if as_of and source_date and source_date > as_of:
                continue
            evidence.append(
                {
                    "id": item_id,
                    "source": (meta or {}).get("source_ref", item_id),
                    "source_type": (meta or {}).get("source_type", "controlled_source"),
                    "source_date": source_date or None,
                    "excerpt": str(text)[:500],
                    "distance": round(float(distance), 4),
                }
            )
            if len(evidence) >= limit:
                break
        return evidence


def recommendation_query(client: dict[str, Any], recommendation: dict[str, Any]) -> str:
    tension = client.get("tension") or {}
    return "\n".join(
        str(value)
        for value in (
            f"Risk profile: {client.get('risk_profile', '')}",
            f"Objectives: {client.get('objectives', '')}",
            f"Portfolio tension: {tension.get('portfolio_does', '')}",
            f"Upcoming constraint: {tension.get('future_demands', '')}",
            f"Recommendation: {recommendation.get('title', '')}. {recommendation.get('detail', '')}",
            f"Suitability condition: {recommendation.get('suitability', '')}",
        )
        if value
    )


def retrieve_recommendation_evidence(
    client: dict[str, Any], recommendation: dict[str, Any]
) -> dict[str, Any]:
    status = retrieval_configuration_status()
    if not status["configured"]:
        return {**status, "evidence": []}
    try:
        evidence = ChromaKnowledgeService().search(
            recommendation_query(client, recommendation),
            client_id=str(client.get("client_id", "")),
            as_of=str(client.get("snapshot_path", [{}])[-1].get("date", ""))
            if client.get("snapshot_path")
            else None,
        )
    except Exception:
        return {
            "status": "unavailable",
            "configured": True,
            "reason": "Chroma retrieval was temporarily unavailable; deterministic controls still ran.",
            "evidence": [],
        }
    return {
        "status": "ready" if evidence else "empty",
        "configured": True,
        "reason": (
            f"Retrieved {len(evidence)} purpose-limited passage(s) from Chroma Cloud."
            if evidence
            else "The collection is reachable but contains no matching indexed evidence."
        ),
        "evidence": evidence,
    }

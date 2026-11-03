"""Write the client vectors the explainer site's Book map reads.

The site is static, so it cannot call the app. Run this after the dataset or
the vector features change:  python scripts/export_book_map.py
"""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tessera.engine import build_intelligence_payload  # noqa: E402


def lane(card: dict) -> str:
    if card.get("escalation"):
        return "exposed"
    return "now" if card["score"] >= 70 else "week" if card["score"] >= 45 else "monitor"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="store_true", help="Read shared cloud news and save the exported vectors in cloud storage.")
    args = parser.parse_args()
    live = ROOT / "runtime" / "live_events.json"
    # Same live news the app uses, so scores and flags match what an RM sees.
    outputs = None
    if args.cloud:
        from app import load_local_environment
        from tessera.cloud_outputs import production_output_store
        from tessera.services import IntelligenceService
        load_local_environment()
        outputs = production_output_store()
        payload = IntelligenceService(ROOT / "data", output_store=outputs).get()
    else:
        payload = build_intelligence_payload(ROOT / "data", live if live.exists() else None)
    vectors = payload["client_vectors"]
    queue = {card["client_id"]: card for card in payload["book"]["priority_queue"]}
    for client_id, vector in vectors["clients"].items():
        card = queue[client_id]
        vector.update(name=card["client_name"], score=card["score"], lane=lane(card), tension=card.get("tension"))
    out = ROOT / "site" / "data" / "book-map.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vectors, indent=1, ensure_ascii=False), encoding="utf-8")
    if outputs is not None:
        outputs.upload_file("exports/book-map.json", out)
    print(f"Wrote {out.relative_to(ROOT)} for {len(vectors['clients'])} clients")


if __name__ == "__main__":
    main()

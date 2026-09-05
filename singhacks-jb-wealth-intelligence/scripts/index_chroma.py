"""Index TESSERA's controlled narrative sources into Chroma Cloud."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import load_local_environment  # noqa: E402
from tessera.retrieval import (  # noqa: E402
    ChromaKnowledgeService,
    build_knowledge_documents,
    retrieval_configuration_status,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Prepare documents without calling external services."
    )
    parser.add_argument(
        "--no-prune", action="store_true", help="Keep indexed records removed from the source data."
    )
    args = parser.parse_args()
    load_local_environment(ROOT / ".env.local")
    documents = build_knowledge_documents(ROOT / "data")
    if args.dry_run:
        by_type: dict[str, int] = {}
        for document in documents:
            source_type = str(document.metadata["source_type"])
            by_type[source_type] = by_type.get(source_type, 0) + 1
        print(f"Prepared {len(documents)} controlled document(s): {by_type}")
        return

    status = retrieval_configuration_status()
    if not status["configured"]:
        raise SystemExit(status["reason"])
    result = ChromaKnowledgeService().index(documents, prune=not args.no_prune)
    print(
        f"Indexed {result['indexed']} document(s) into "
        f"{os.environ.get('CHROMA_COLLECTION', 'tessera-knowledge-v1')}; "
        f"removed {result['removed']} stale document(s)."
    )


if __name__ == "__main__":
    main()
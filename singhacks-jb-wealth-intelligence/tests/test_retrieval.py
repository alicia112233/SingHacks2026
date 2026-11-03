import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tessera.retrieval import (
    CORPUS,
    ChromaKnowledgeService,
    GatewayEmbeddingClient,
    build_knowledge_documents,
    retrieval_configuration_status,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Collection:
    def __init__(self):
        self.query_kwargs = None

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
            "ids": [["client-note", "future-event"]],
            "documents": [["Relevant client note", "Event after the snapshot"]],
            "metadatas": [[
                {
                    "source_ref": "rm_notes.json • N-1",
                    "source_type": "rm_note",
                    "source_date": "2026-06-01",
                    "client_id": "CL-0012",
                    "corpus": CORPUS,
                },
                {
                    "source_ref": "event_log.csv • future",
                    "source_type": "controlled_event",
                    "source_date": "2027-01-01",
                    "client_id": "GLOBAL",
                    "corpus": CORPUS,
                },
            ]],
            "distances": [[0.1, 0.2]],
        }


class _Client:
    def __init__(self, collection):
        self.collection = collection

    def get_or_create_collection(self, **_kwargs):
        return self.collection


class _Embedder:
    def embed(self, texts):
        return [[0.2, 0.8] for _ in texts]


class RetrievalTests(unittest.TestCase):
    def test_retrieval_requires_explicit_opt_in_and_credentials(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(retrieval_configuration_status()["status"], "disabled")
        with mock.patch.dict(
            "os.environ", {"TESSERA_RETRIEVAL_ENABLED": "true"}, clear=True
        ):
            status = retrieval_configuration_status()
        self.assertEqual(status["status"], "not_configured")
        self.assertIn("CHROMA_API_KEY", status["reason"])

    def test_gateway_embedding_request_preserves_input_order(self):
        captured = {}
        payload = {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 25)
            captured.update(json.loads(request.data.decode("utf-8")))
            return _Response(json.dumps(payload).encode("utf-8"))

        with mock.patch("tessera.retrieval.urlopen", side_effect=fake_urlopen):
            vectors = GatewayEmbeddingClient(model="test/model", token="token").embed(
                ["first", "second"]
            )
        self.assertEqual(captured, {"model": "test/model", "input": ["first", "second"]})
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])

    def test_search_enforces_client_scope_and_excludes_future_sources(self):
        collection = _Collection()
        service = ChromaKnowledgeService(_Client(collection), _Embedder())
        evidence = service.search("query", "CL-0012", as_of="2026-08-26", limit=3)
        self.assertEqual([item["id"] for item in evidence], ["client-note"])
        where = collection.query_kwargs["where"]
        self.assertEqual(where["$and"][0], {"corpus": {"$eq": CORPUS}})
        self.assertIn({"client_id": {"$eq": "CL-0012"}}, where["$and"][1]["$or"])

    def test_controlled_corpus_has_traceable_client_and_global_documents(self):
        project_data = Path(__file__).resolve().parents[1] / "data"
        documents = build_knowledge_documents(project_data)
        self.assertGreater(len(documents), 20)
        self.assertTrue(any(item.metadata["client_id"] == "CL-0012" for item in documents))
        self.assertTrue(any(item.metadata["client_id"] == "GLOBAL" for item in documents))
        self.assertTrue(all(item.metadata.get("source_ref") for item in documents))

    def test_returned_rows_are_revalidated_even_if_database_ignores_filter(self):
        collection = _Collection()
        rows = [
            {"client_id": "CL-OTHER", "corpus": CORPUS, "source_type": "rm_note", "source_date": "2026-01-01"},
            {"client_id": "CL-0012", "corpus": "foreign", "source_type": "rm_note", "source_date": "2026-01-01"},
            {"client_id": "GLOBAL", "corpus": CORPUS, "source_type": "rm_note", "source_date": "2026-01-01"},
            {"client_id": "CL-0012", "corpus": CORPUS, "source_type": "rm_note", "source_date": "invalid"},
            {"client_id": "CL-0012", "corpus": CORPUS, "source_type": "rm_note"},
            {"client_id": "CL-0012", "corpus": CORPUS, "source_type": "invented"},
            {"client_id": "GLOBAL", "corpus": CORPUS, "source_type": "mandate_rule", "source_ref": "mandates.csv"},
        ]
        collection.query = mock.Mock(return_value={
            "ids": [[str(index) for index in range(len(rows))]],
            "documents": [["Secret" for _ in rows]], "metadatas": [rows],
            "distances": [[0.1 for _ in rows]],
        })
        evidence = ChromaKnowledgeService(_Client(collection), _Embedder()).search(
            "query", "CL-0012", as_of="2026-08-26",
        )
        self.assertEqual([item["id"] for item in evidence], ["6"])


if __name__ == "__main__":
    unittest.main()

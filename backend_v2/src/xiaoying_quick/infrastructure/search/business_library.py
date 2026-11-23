"""Shared Markdown knowledge. PostgreSQL controls visibility and versions; vectors rank current passages."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

import httpx

from ...modules.knowledge.library import passages, published_documents, ranked_sections
from ..monthly_quota import QuotaUnavailable, capacity
from ..persistence.repositories.knowledge import SqlAlchemyKnowledgeRepository

_log = logging.getLogger(__name__)


class BusinessLibrary:
    def __init__(self, session, settings):
        self.session = session
        self.settings = settings

    def documents(self):
        now = datetime.now(timezone.utc)
        return published_documents(SqlAlchemyKnowledgeRepository(self.session).effective_entries(now))

    def search(self, query, limit=8, *, include_references=False):
        docs = [doc for doc in self.documents().values() if include_references or not doc.reference]
        chunks = list(passages(docs))
        scores = {}
        if chunks and self.settings.knowledge_search_url and self.settings.knowledge_embedding_url:
            try:
                with capacity(len(query.encode("utf-8")) + 8):
                    with httpx.Client(timeout=httpx.Timeout(12.0, connect=3.0), trust_env=False) as client:
                        scores = VectorSearch(self.settings, client).search(query, chunks, limit)
            except QuotaUnavailable:
                pass
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
                _log.warning("Shared knowledge vector search unavailable (%s); using text matches", type(error).__name__)
        return ranked_sections(query, chunks, scores, limit)


class VectorSearch:
    def __init__(self, settings, client):
        self.settings = settings
        self.client = client
        url = settings.knowledge_search_url.rstrip("/")
        identity = f"{settings.knowledge_embedding_url}|{settings.knowledge_embedding_model}|{settings.knowledge_embedding_dimensions}"
        self.index = url + "/gilead-app-knowledge-v1-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        self.auth = (settings.knowledge_search_user, settings.knowledge_search_password.get_secret_value()) if settings.knowledge_search_user else None

    def request(self, method, suffix="", **options):
        response = self.client.request(method, self.index + suffix, auth=self.auth, **options)
        response.raise_for_status()
        return response

    def ensure_index(self):
        response = self.client.head(self.index, auth=self.auth)
        if response.status_code != 404:
            response.raise_for_status()
            return
        mapping = {"settings": {"index.knn": True, "number_of_shards": 1, "number_of_replicas": 0},
                   "mappings": {"properties": {"vector": {"type": "knn_vector",
                    "dimension": self.settings.knowledge_embedding_dimensions,
                    "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"}}}}}
        created = self.client.put(self.index, auth=self.auth, json=mapping)
        if created.status_code == 400 and created.json().get("error", {}).get("type") == "resource_already_exists_exception":
            return
        created.raise_for_status()

    def embeddings(self, texts, *, query=False):
        settings = self.settings
        response = self.client.post(settings.knowledge_embedding_url,
            headers={"Authorization": "Bearer " + settings.knowledge_embedding_key.get_secret_value()},
            json={"model": settings.knowledge_embedding_model, "input": texts, "dimensions": settings.knowledge_embedding_dimensions})
        response.raise_for_status()
        payload = response.json()
        points = sorted(payload["data"], key=lambda point: point["index"])
        if [point["index"] for point in points] != list(range(len(texts))) or any(
                len(point["embedding"]) != settings.knowledge_embedding_dimensions for point in points):
            raise ValueError("Unexpected knowledge embedding shape")
        if query and payload.get("usage"):
            from ...modules.usage import record_llm_usage
            record_llm_usage(purpose="knowledge.search", model_id=settings.knowledge_embedding_model, usage=payload["usage"])
        return [point["embedding"] for point in points]

    def index_missing(self, chunks, max_batches=None):
        self.ensure_index()
        texts = {p.key: p.embedding_text for p in chunks}
        keys = list(texts)
        count = 0
        for start in range(0, len(keys), 280):
            docs = self.request("POST", "/_mget?_source=false", json={"ids": keys[start:start+280]}).json()["docs"]
            missing = [doc["_id"] for doc in docs if not doc.get("found")]
            for i in range(0, len(missing), 10):
                if max_batches is not None and count >= max_batches:
                    return
                ids = missing[i:i+10]
                vectors = self.embeddings([texts[k] for k in ids])
                records = []
                for key, vector in zip(ids, vectors, strict=True):
                    records.extend([json.dumps({"index": {"_id": key}}), json.dumps({"vector": vector})])
                body = "\n".join(records) + "\n"
                reply = self.request("POST", "/_bulk?refresh=wait_for", content=body.encode(),
                                     headers={"Content-Type": "application/x-ndjson"}).json()
                if reply.get("errors"):
                    raise ValueError("Knowledge index rejected a passage")
                count += 1

    def search(self, query, chunks, limit):
        self.index_missing(chunks, max_batches=1)
        vector = self.embeddings([query], query=True)[0]
        # Only score passages permitted by the current PostgreSQL publication snapshot.
        keys = list(dict.fromkeys(p.key for p in chunks))
        scores = {}
        for start in range(0, len(keys), 2000):
            body = {"size": min(limit*4, 100), "_source": False, "query": {"script_score": {
                "query": {"ids": {"values": keys[start:start+2000]}},
                "script": {"source": "knn_score", "lang": "knn", "params": {
                    "field": "vector", "query_value": vector, "space_type": "cosinesimil"}}}}}
            hits = self.request("POST", "/_search", json=body).json()["hits"]["hits"]
            # OpenSearch 3 maps cosine similarity to a positive score of (1 + cosine) / 2.
            scores.update({hit["_id"]: 2 * float(hit["_score"]) - 1 for hit in hits})
        return scores


def index_published_document(factory, settings, doc_id):
    if not settings.knowledge_search_url or not settings.knowledge_embedding_url:
        return
    try:
        with factory() as session:
            document = BusinessLibrary(session, settings).documents().get(doc_id)
        if document and not document.reference:
            with httpx.Client(timeout=20.0, trust_env=False) as client:
                VectorSearch(settings, client).index_missing(list(passages([document])))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
        _log.warning("Knowledge indexing deferred (%s)", type(error).__name__)

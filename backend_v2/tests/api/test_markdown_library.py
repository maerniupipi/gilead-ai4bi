import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from xiaoying_quick.application.agent_run.business_knowledge import business_knowledge_tools
from xiaoying_quick.infrastructure.search.business_library import VectorSearch
from xiaoying_quick.modules.agent.contracts import AgentToolContext
from xiaoying_quick.modules.identity.contracts import Role


def test_uploaded_markdown_review_search_read_and_replace(client, app, seed_user, auth_headers):
    seed_user("kbowner", role=Role.KNOWLEDGE_REVIEWER)
    seed_user("reader")
    reviewer, reader = auth_headers("kbowner"), auth_headers("reader")
    base = "/api/v2/knowledge"
    content = "# 指标手册\n\n## 月内规则\n\n  唯一业务词 amberquartz，参照月初口径。\n\n```text\n## 示例标题\n```\n"
    def upload(raw, headers):
        response = client.post(base+"/documents", headers=headers, files={"file": ("手册.md", raw, "text/markdown")})
        assert response.status_code == 200, response.text
        return response.json()
    submitted = upload(content.encode(), reader)
    assert submitted["state"] == "pending_review"
    assert not client.get(base+"/search", params={"q": "amberquartz"}, headers=reader).json()
    decision = client.post("/api/v2/admin/knowledge/reviews/"+submitted["candidate_id"]+"/approve", headers=reviewer, json={})
    assert decision.status_code == 200, decision.text
    hits = client.get(base+"/search", params={"q": "amberquartz"}, headers=reader).json()
    hit = next(h for h in hits if h["filename"] == "手册.md")
    assert hit["heading"] == "月内规则"
    doc_id = hit["document_id"]
    doc = client.get(base+"/documents/"+doc_id, headers=reader).json()
    assert "".join(s["content"] for s in doc["sections"]) == content
    assert len(doc["sections"]) == 2
    assert upload(content.encode(), reviewer)["version"] == 1
    updated = "# 调整\n\n## 口径\n\n替换为 cobaltquartz。  \n"
    assert upload(updated.encode(), reviewer) == {"state":"published", "document_id":doc_id, "version":2}
    assert not client.get(base+"/search", params={"q":"amberquartz"}, headers=reader).json()
    search, read = business_knowledge_tools()
    ctx = AgentToolContext(run_id="run", session_id="s", actor_id="reader", emit=lambda *_:None,
                           extras={"knowledge_session_factory": app.state.session_factory, "knowledge_settings": app.state.settings})
    results = asyncio.run(search.executor(ctx, {"query":"cobaltquartz"}))
    assert results.ok and results.payload["hits"][0]["document_id"] == doc_id
    section = asyncio.run(read.executor(ctx, {"document_id":doc_id, "section":1}))
    assert section.ok and section.payload["content"] in updated and section.payload["version"]==2
    assert client.get(base+"/documents").status_code == 401


@pytest.mark.parametrize(("name","data"), [("example.pdf",b"hello"),("doc.md",b"\xff"),("../doc.md",b"hello"),
                                           ("doc.md",b"password=confidential"),("doc.md",b"a"*1048577)])
def test_invalid_upload_is_not_published(client, seed_user, auth_headers, name, data):
    seed_user("admin", role=Role.ADMIN)
    response=client.post("/api/v2/knowledge/documents",headers=auth_headers("admin"),files={"file":(name,data)})
    assert response.status_code == 422


def test_application_vector_index_uses_platform_lucene_engine(app):
    settings = app.state.settings.model_copy(update={"knowledge_search_url": "http://search.local",
        "knowledge_embedding_url": "http://embeddings.local/vector", "knowledge_embedding_dimensions": 2})
    passage = SimpleNamespace(key="published", embedding_text="有效口径")

    def respond(request):
        if request.method == "HEAD":
            return httpx.Response(404)
        body = json.loads(request.content)
        if request.method == "PUT":
            vector = body["mappings"]["properties"]["vector"]
            assert vector["dimension"] == 2 and vector["method"]["engine"] == "lucene"
            return httpx.Response(200, json={"acknowledged": True})
        if request.url.path.endswith("/_mget"):
            return httpx.Response(200, json={"docs": [{"_id": "published", "found": True}]})
        if request.url.host == "embeddings.local":
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1., 0.]}]})
        assert request.url.path.endswith("/_search")
        assert body["query"]["script_score"]["query"]["ids"]["values"] == ["published"]
        return httpx.Response(200, json={"hits": {"hits": [{"_id": "published", "_score": 0.75}]}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert VectorSearch(settings, client).search("口径", [passage], 3) == {"published": 0.5}

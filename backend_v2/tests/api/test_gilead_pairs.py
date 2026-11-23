from xiaoying_quick.application.lab_connection import LabConnectionService
from xiaoying_quick.modules.identity.contracts import Role


def test_chatbot_can_bind_two_complete_pairs(client, seed_user, auth_headers, monkeypatch):
    seed_user("pairs-admin", role=Role.ADMIN)
    headers = auth_headers("pairs-admin")
    monkeypatch.setattr(LabConnectionService, "_verify_projects", staticmethod(lambda *_: None))
    body = {
        "endpoint_url": "http://127.0.0.1:8000/api/autobi/gateway/v2/lab",
        "authorization": "unit-test",
        "pairs": [
            {"id": "actual", "name": "DDI", "recall": "abcdefghij", "sql": "1234567890"},
            {"id": "second", "name": "第二套", "recall": "ABCDEFGHIJ", "sql": "0987654321"},
        ],
    }
    base = "/api/v2/admin/lab-connection/pairs"
    saved = client.put(base, headers=headers, json=body)
    assert saved.status_code == 200 and saved.json()["pairs"] == body["pairs"]
    assert "unit-test" not in saved.text
    result = client.post(
        "/api/v2/admin/chatbots",
        headers=headers,
        json={"name": "双实验室助手", "lab_ids": ["actual", "second"]},
    )
    assert result.status_code == 201, result.text
    assert result.json()["lab_ids"] == ["actual", "second"]
    assert (
        client.put(base, headers=headers, json={**body, "pairs": body["pairs"][:1]}).status_code
        == 422
    )
    duplicate = {**body["pairs"][1], "recall": body["pairs"][0]["recall"]}
    assert (
        client.put(
            base, headers=headers, json={**body, "pairs": [body["pairs"][0], duplicate]}
        ).status_code
        == 422
    )

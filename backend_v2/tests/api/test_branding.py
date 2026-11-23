"""Workspace branding API tests."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from xiaoying_quick.modules.identity.contracts import Role, UserRecord

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
    b"\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_public_branding_defaults_to_enterprise_identity(client: TestClient) -> None:
    response = client.get("/api/v2/branding")
    assert response.status_code == 200
    body = response.json()
    assert body["character_name"] == "Gilead BI"
    assert body["company_intro"] == "商业智能分析平台"
    assert body["theme_id"] == "gilead"
    assert body["logo_kind"] == "preset"
    assert body["logo_url"] == "/brand/gilead-bi.svg"
    assert len(body["themes"]) == 6
    assert len(body["logos"]) == 3
    assert body["tokens"]["accent"] == "#c5203f"


def test_only_admin_can_update_branding(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("brand-admin", role=Role.ADMIN)
    seed_user("brand-user")
    payload = {
        "character_name": "小柯",
        "company_intro": "示例药企业务助手",
        "theme_id": "harbor",
        "logo_preset_id": "enterprise",
    }
    denied = client.put("/api/v2/admin/branding", json=payload, headers=auth_headers("brand-user"))
    assert denied.status_code == 403

    updated = client.put(
        "/api/v2/admin/branding", json=payload, headers=auth_headers("brand-admin")
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["character_name"] == "小柯"
    assert body["company_intro"] == "示例药企业务助手"
    assert body["theme_id"] == "harbor"
    assert body["logo_preset_id"] == "enterprise"
    assert body["logo_url"] == "/brand/enterprise.svg"
    assert body["tokens"]["accent"] == "#1a5f7a"

    public = client.get("/api/v2/branding")
    assert public.json()["character_name"] == "小柯"


def test_unknown_theme_is_rejected(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("theme-admin", role=Role.ADMIN)
    response = client.put(
        "/api/v2/admin/branding",
        headers=auth_headers("theme-admin"),
        json={
            "character_name": "小吉",
            "company_intro": "吉利德业务助手",
            "theme_id": "rainbow",
        },
    )
    assert response.status_code == 422


def test_admin_can_upload_logo_and_public_endpoint_serves_it(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("logo-admin", role=Role.ADMIN)
    seed_user("logo-user")
    denied = client.post(
        "/api/v2/admin/branding/logo",
        headers=auth_headers("logo-user"),
        files={"file": ("mark.png", _MIN_PNG, "image/png")},
    )
    assert denied.status_code == 403

    uploaded = client.post(
        "/api/v2/admin/branding/logo",
        headers=auth_headers("logo-admin"),
        files={"file": ("mark.png", _MIN_PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["logo_kind"] == "upload"
    assert body["logo_url"].startswith("/api/v2/branding/logo")

    served = client.get("/api/v2/branding/logo")
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")
    assert served.headers["content-type"].startswith("image/png")

    junk = client.post(
        "/api/v2/admin/branding/logo",
        headers=auth_headers("logo-admin"),
        files={"file": ("note.txt", b"not-an-image", "text/plain")},
    )
    assert junk.status_code == 422

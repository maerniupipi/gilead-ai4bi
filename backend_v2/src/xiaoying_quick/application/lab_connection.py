"""Persist, resolve and safely preview laboratory connection profiles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.models import SourceLabModel
from xiaoying_quick.infrastructure.persistence.models.lab_connection import LabConnectionModel
from xiaoying_quick.modules.data_sources.ports import SecretStore
from xiaoying_quick.shared.errors import ValidationFailed

LAB_NAMES = {
    "actual": "实际销售",
    "demand": "销售需求",
    "ext_simple": "外部市场（简单）",
    "ext_complex": "外部市场（复杂）",
}
PROVIDERS = ("bailian", "bootcamp")
BOOTCAMP_ENDPOINT = "http://127.0.0.1:8000/api/autobi/gateway/v2/lab"


@dataclass(frozen=True)
class ResolvedLabConnection:
    provider: str
    mock_enabled: bool
    persisted: bool
    endpoint_url: str
    timeout_seconds: float
    authorization: str = field(repr=False)
    lab_credentials: dict[str, str] = field(repr=False)
    user_id: int = 1
    space_id: int = 1
    recall_ids: dict[str, str] = field(default_factory=dict)
    pair_names: dict[str, str] = field(default_factory=dict)


class LabConnectionService:
    def __init__(self, session: Session, settings: Settings, secrets: SecretStore) -> None:
        self._session = session
        self._settings = settings
        self._secrets = secrets

    def has_saved_config(self) -> bool:
        return self._row() is not None

    def _row(self) -> LabConnectionModel | None:
        return self._session.get(LabConnectionModel, "workspace")

    def _profiles(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "bailian": {
                "endpoint_url": self._settings.lab_endpoint_url or "",
                "timeout_seconds": self._settings.lab_timeout_seconds,
                "user_id": 1,
                "space_id": 1,
                "labs": {},
            },
            "bootcamp": {
                "endpoint_url": self._settings.lab_bootcamp_endpoint_url or BOOTCAMP_ENDPOINT,
                "timeout_seconds": 120.0,
                "user_id": 1,
                "space_id": 1,
                "labs": {},
            },
        }
        row = self._row()
        if row:
            for provider in PROVIDERS:
                defaults[provider].update(deepcopy(row.profiles.get(provider, {})))
        return defaults

    def _legacy_tokens(self) -> dict[str, str]:
        tokens = {
            lab_id: secret.get_secret_value()
            for lab_id, secret in (
                ("actual", self._settings.lab_actual_token),
                ("demand", self._settings.lab_demand_token),
                ("ext_simple", self._settings.lab_ext_simple_token),
                ("ext_complex", self._settings.lab_ext_complex_token),
            )
            if secret is not None
        }
        for source in self._session.scalars(select(SourceLabModel)).all():
            try:
                tokens[source.lab_id] = self._read_secret(source.token_secret_ref)
            except ValidationFailed:
                # Preserve the legacy behavior: one removed source credential
                # must not prevent switching to another laboratory provider.
                continue
        return tokens

    def _read_secret(self, ref: str | None) -> str:
        if not ref:
            return ""
        try:
            return self._secrets.get(ref)
        except Exception:
            raise ValidationFailed("保存的实验室密钥无法读取，请重新填写并保存。") from None

    def resolve(
        self, provider: str | None = None, *, allow_unavailable_mock: bool = False
    ) -> ResolvedLabConnection:
        row = self._row()
        if (
            row
            and row.mock_enabled
            and self._settings.environment == "production"
            and not allow_unavailable_mock
        ):
            raise ValidationFailed("生产环境禁止使用演示数据，请在实验室连接页关闭演示模式")
        selected = provider or (row.active_provider if row else self._settings.lab_default_provider)
        if selected not in PROVIDERS:
            raise ValidationFailed("请选择百炼或 Bootcamp")
        profile = self._profiles()[selected]
        credentials = self._legacy_tokens() if selected == "bailian" else {}
        for lab_id, lab in profile.get("labs", {}).items():
            if selected == "bailian" and lab.get("token_secret_ref"):
                credentials[lab_id] = self._read_secret(lab["token_secret_ref"])
            elif selected == "bootcamp" and lab.get("api_access_id"):
                credentials[lab_id] = lab["api_access_id"]
        return ResolvedLabConnection(
            provider=selected,
            recall_ids={k:v['recall_api_access_id'] for k,v in profile.get('labs', {}).items() if v.get('recall_api_access_id')},
            pair_names={k:v.get('name', k) for k,v in profile.get('labs', {}).items() if v.get('recall_api_access_id')},
            mock_enabled=bool(row and row.mock_enabled),
            persisted=row is not None,
            endpoint_url=profile["endpoint_url"],
            timeout_seconds=profile["timeout_seconds"],
            authorization=self._read_secret(profile.get("authorization_secret_ref")),
            lab_credentials=credentials,
            user_id=profile.get("user_id", 1),
            space_id=profile.get("space_id", 1),
        )

    def pairs(self):
        profile = self._profiles()["bootcamp"]
        return {"name": "吉利德AI平台", "endpoint_url": profile["endpoint_url"],
                "configured": bool(profile.get("authorization_secret_ref")),
                "pairs": [{"id": key, "name": value.get("name", key),
                           "recall": value["recall_api_access_id"], "sql": value["api_access_id"]}
                          for key, value in profile["labs"].items() if value.get("recall_api_access_id")]}

    def save_pairs(self, payload, actor_id):
        from urllib.parse import urlsplit
        endpoint = payload["endpoint_url"].strip().rstrip("/")
        url = urlsplit(endpoint)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path != "/api/autobi/gateway/v2/lab"
                or not (url.scheme == "https" or (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")))):
            raise ValidationFailed("请使用 HTTPS 平台网关地址，部署在本机的平台也可填写回环地址")
        profiles = self._profiles()
        profile = profiles["bootcamp"]
        token = payload.get("authorization")
        if not token and (endpoint != profile["endpoint_url"] or not profile.get("authorization_secret_ref")):
            raise ValidationFailed("首次配置或更换地址时请填写平台服务密钥")
        pairs = payload["pairs"]
        ids = [p["id"] for p in pairs]
        projects = [p[k] for p in pairs for k in ("recall", "sql")]
        if not pairs or len(set(ids)) != len(ids) or len(set(projects)) != len(projects):
            raise ValidationFailed("每套实验室需要独立的编号、召回实验室和 SQL 实验室")
        key = token or self._read_secret(profile.get("authorization_secret_ref"))
        self._verify_projects(endpoint, key, pairs)
        profile.update(endpoint_url=endpoint, timeout_seconds=190.0, labs={
            p["id"]: {"name": p["name"], "recall_api_access_id": p["recall"], "api_access_id": p["sql"]}
            for p in pairs})
        if token:
            profile["authorization_secret_ref"] = self._secrets.put(token)
        row = self._row()
        if row is None:
            row = LabConnectionModel(id="workspace")
            self._session.add(row)
        row.profiles = profiles
        row.active_provider = "bootcamp"
        row.mock_enabled = False
        row.updated_by = actor_id
        self._session.flush()
        return self.pairs()

    @staticmethod
    def _verify_projects(endpoint, key, pairs):
        import httpx
        import json
        with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
            for pair in pairs:
                for mode in ("recall", "sql"):
                    try:
                        response = client.post(endpoint, headers={"X-Internal-Token":key, "X-User-Id":"1","X-Space-Id":"1"},
                            json={"id":pair[mode], "content":"连接校验", "features":{"capability_check":True, "lab_output":mode}})
                        response.raise_for_status()
                        events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
                        if not any(e.get("kind") == "capability" and e.get("configured") and e.get("mode") == mode for e in events):
                            raise ValueError("type")
                    except (ValueError,httpx.HTTPError):
                        raise ValidationFailed("无法验证组合 "+pair["name"]+" 的"+("召回" if mode=="recall" else "SQL")+"实验室，请核对类型、知识库、模型和密钥") from None

    def public_payload(self) -> dict[str, Any]:
        row = self._row()
        profiles = {}
        for provider in PROVIDERS:
            resolved = self.resolve(provider, allow_unavailable_mock=True)
            profiles[provider] = {
                "endpoint_url": resolved.endpoint_url,
                "timeout_seconds": resolved.timeout_seconds,
                "token_configured": bool(resolved.authorization),
                "user_id": resolved.user_id,
                "space_id": resolved.space_id,
                "labs": [
                    {
                        "lab_id": lab_id,
                        "name": name,
                        "credential_configured": bool(resolved.lab_credentials.get(lab_id)),
                        "api_access_id": (
                            resolved.lab_credentials.get(lab_id, "")
                            if provider == "bootcamp"
                            else ""
                        ),
                    }
                    for lab_id, name in LAB_NAMES.items()
                ],
            }
        return {
            "active_provider": row.active_provider if row else self._settings.lab_default_provider,
            "mock_enabled": bool(row and row.mock_enabled),
            "mock_available": self._settings.environment in {"development", "test"},
            "profiles": profiles,
        }

    def preview(self, payload: dict[str, Any]) -> ResolvedLabConnection:
        self._validate(payload)
        profile = payload["profile"]
        provider = profile["provider"]
        current = self.resolve(provider, allow_unavailable_mock=True)
        credentials = dict(current.lab_credentials)
        for lab in profile.get("labs", []):
            key = "token" if provider == "bailian" else "api_access_id"
            value = lab.get(key)
            if value:
                credentials[lab["lab_id"]] = value.strip()
            elif provider == "bootcamp" and value is not None:
                credentials.pop(lab["lab_id"], None)
        return ResolvedLabConnection(
            provider=provider,
            mock_enabled=payload["mock_enabled"],
            persisted=current.persisted,
            endpoint_url=profile["endpoint_url"].strip().rstrip("/"),
            timeout_seconds=profile["timeout_seconds"],
            authorization=profile.get("authorization") or current.authorization,
            lab_credentials=credentials,
            user_id=profile.get("user_id", current.user_id),
            space_id=profile.get("space_id", current.space_id),
        )

    def save(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        resolved = self.preview(payload)
        if payload["active_provider"] != resolved.provider:
            raise ValidationFailed("保存的平台必须与当前选择的平台一致")
        if not resolved.mock_enabled:
            self._validate_live_connection(resolved)
        profile = payload["profile"]
        provider = profile["provider"]
        profiles = self._profiles()
        saved = profiles[provider]
        saved.update(
            {
                key: profile[key]
                for key in ("endpoint_url", "timeout_seconds", "user_id", "space_id")
                if key in profile
            }
        )
        saved["endpoint_url"] = saved["endpoint_url"].strip().rstrip("/")
        authorization = profile.get("authorization")
        if authorization:
            saved["authorization_secret_ref"] = self._secrets.put(authorization)
        labs = saved.setdefault("labs", {})
        for lab in profile.get("labs", []):
            entry = labs.setdefault(lab["lab_id"], {})
            if provider == "bailian" and lab.get("token"):
                entry["token_secret_ref"] = self._secrets.put(lab["token"])
            elif provider == "bootcamp" and "api_access_id" in lab:
                entry["api_access_id"] = (lab["api_access_id"] or "").strip()
        row = self._row()
        if row is None:
            row = LabConnectionModel(id="workspace")
            self._session.add(row)
        row.active_provider = payload["active_provider"]
        row.mock_enabled = payload["mock_enabled"]
        row.profiles = profiles
        row.updated_by = actor_id
        self._session.flush()
        return self.public_payload()

    def _validate_live_connection(self, resolved: ResolvedLabConnection) -> None:
        from xiaoying_quick.infrastructure.lab_http.bootcamp import BootcampLabConfig
        from xiaoying_quick.infrastructure.lab_http.config import LabHttpConfig

        if not resolved.endpoint_url:
            raise ValidationFailed("请填写实验室服务地址")
        if not resolved.lab_credentials:
            raise ValidationFailed("请至少配置一个实验室的访问凭据或 API 调用 ID")
        try:
            if resolved.provider == "bootcamp":
                BootcampLabConfig(
                    endpoint_url=resolved.endpoint_url,
                    authorization=resolved.authorization,
                    lab_ids=resolved.lab_credentials,
                    timeout_seconds=resolved.timeout_seconds,
                    user_id=resolved.user_id,
                    space_id=resolved.space_id,
                    allow_insecure_http=self._settings.environment != "production",
                )
            else:
                LabHttpConfig(
                    endpoint_url=resolved.endpoint_url,
                    lab_tokens=resolved.lab_credentials,
                    timeout_seconds=resolved.timeout_seconds,
                    allow_insecure_http=self._settings.environment != "production",
                )
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from None

    def _validate(self, payload: dict[str, Any]) -> None:
        provider = payload["profile"]["provider"]
        if provider not in PROVIDERS or payload["active_provider"] not in PROVIDERS:
            raise ValidationFailed("请选择百炼或 Bootcamp")
        if payload["mock_enabled"] and self._settings.environment not in {"development", "test"}:
            raise ValidationFailed("演示数据仅允许在开发或测试环境开启")
        profile = payload["profile"]
        endpoint = profile["endpoint_url"].strip().rstrip("/")
        if endpoint:
            try:
                url = urlsplit(endpoint)
                hostname = url.hostname
                _ = url.port
            except ValueError:
                raise ValidationFailed("服务地址无效") from None
            if url.scheme not in {"http", "https"} or not hostname:
                raise ValidationFailed("服务地址必须为完整 HTTP(S) 地址")
            if url.username or url.password or url.query or url.fragment:
                raise ValidationFailed("服务地址不能包含密钥、查询参数或片段")
            path = (
                "/internal/lab/sql-evidence"
                if provider == "bootcamp"
                else "/opentrek-chat/v2/completions"
            )
            if not url.path.endswith(path) and not (
                provider == "bootcamp" and url.path.endswith("/api/autobi/gateway/v2/lab")
            ):
                raise ValidationFailed(f"服务地址必须以 {path} 结尾")
            if self._settings.environment == "production" and url.scheme != "https":
                raise ValidationFailed("生产环境服务地址必须使用 HTTPS")
        ids = [lab["lab_id"] for lab in profile.get("labs", [])]
        if len(ids) != len(set(ids)) or any(lab_id not in LAB_NAMES for lab_id in ids):
            raise ValidationFailed("实验室映射不能重复，且必须是四个已知业务领域")
        for secret in [
            profile.get("authorization"),
            *(lab.get("token") for lab in profile.get("labs", [])),
        ]:
            if secret and (
                secret != secret.strip() or not all(0x21 <= ord(c) <= 0x7E for c in secret)
            ):
                raise ValidationFailed("密钥包含无效字符")

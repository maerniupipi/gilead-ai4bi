"""Use cases for the selectable model registry.

The active configuration is what the agent loop runs against. Shape validation
lives here; transport-level validation (the strict endpoint and header rules)
happens when the infrastructure layer builds the actual client, and a broken
configuration then fails the run loudly instead of silently.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from xiaoying_quick.shared.errors import Conflict, NotFound, ValidationFailed
from xiaoying_quick.shared.model_endpoint import chat_completion_endpoint

from .contracts import REASONING_MODES, ModelConfigRecord
from .ports import ModelConfigRepository, ModelSecretStore


class ModelConfigService:
    def __init__(
        self,
        repository: ModelConfigRepository,
        secrets: ModelSecretStore,
        *,
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._secrets = secrets
        self._id_factory = id_factory

    def list_configs(self) -> tuple[ModelConfigRecord, ...]:
        return self._repository.list_all()

    def get(self, config_id: str) -> ModelConfigRecord:
        record = self._repository.get(config_id)
        if record is None:
            raise NotFound("model config not found")
        return record

    def active(self) -> ModelConfigRecord | None:
        return self._repository.active()

    def create(
        self,
        *,
        name: str,
        endpoint_url: str,
        model_id: str,
        api_key: str,
        temperature: float = 0.2,
        max_tokens: int = 16_384,
        reasoning: str = "auto",
        timeout_seconds: float = 180.0,
        activate: bool = False,
    ) -> ModelConfigRecord:
        clean_name = _clean_name(name)
        if self._repository.get_by_name(clean_name) is not None:
            raise Conflict("a model config with this name already exists")
        _validate_shape(
            endpoint_url=endpoint_url,
            api_key=api_key,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            timeout_seconds=timeout_seconds,
        )
        now = datetime.now(timezone.utc)
        record = ModelConfigRecord(
            id=self._id_factory(),
            name=clean_name,
            endpoint_url=chat_completion_endpoint(endpoint_url),
            model_id=model_id.strip(),
            secret_ref=self._secrets.put(api_key.strip()),
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            reasoning=reasoning,
            timeout_seconds=float(timeout_seconds),
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        created = self._repository.add(record)
        if activate or self._repository.active() is None:
            created = self.activate(created.id)
        return created

    def update(
        self,
        config_id: str,
        *,
        name: str | None = None,
        endpoint_url: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ModelConfigRecord:
        record = self.get(config_id)
        new_name = record.name
        if name is not None:
            new_name = _clean_name(name)
            existing = self._repository.get_by_name(new_name)
            if existing is not None and existing.id != record.id:
                raise Conflict("a model config with this name already exists")
        candidate = replace(
            record,
            name=new_name,
            endpoint_url=(endpoint_url or record.endpoint_url).strip(),
            model_id=(model_id or record.model_id).strip(),
            temperature=record.temperature if temperature is None else float(temperature),
            max_tokens=record.max_tokens if max_tokens is None else int(max_tokens),
            reasoning=record.reasoning if reasoning is None else reasoning,
            timeout_seconds=(
                record.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
            ),
        )
        current_key = api_key if api_key is not None else self._secrets.get(record.secret_ref)
        _validate_shape(
            endpoint_url=candidate.endpoint_url,
            api_key=current_key,
            model_id=candidate.model_id,
            temperature=candidate.temperature,
            max_tokens=candidate.max_tokens,
            reasoning=candidate.reasoning,
            timeout_seconds=candidate.timeout_seconds,
        )
        candidate = replace(
            candidate, endpoint_url=chat_completion_endpoint(candidate.endpoint_url)
        )
        if api_key is not None:
            candidate = replace(
                candidate,
                secret_ref=self._secrets.put(api_key.strip(), current_ref=record.secret_ref),
            )
        return self._repository.save(candidate)

    def delete(self, config_id: str) -> None:
        record = self.get(config_id)
        # Active configs may be removed; the registry simply has no active
        # model until another is activated (agent runs fail loudly then).
        self._repository.delete(config_id)
        try:
            self._secrets.delete(record.secret_ref)
        except Exception:
            # Losing the ciphertext only costs storage; the row is already gone.
            pass

    def activate(self, config_id: str) -> ModelConfigRecord:
        record = self.get(config_id)
        self._repository.clear_active()
        return self._repository.save(replace(record, is_active=True))


def _clean_name(name: str) -> str:
    clean = " ".join(name.strip().split())
    if not 1 <= len(clean) <= 160:
        raise ValidationFailed("model config name must contain 1-160 characters")
    return clean


def _validate_shape(
    *,
    endpoint_url: str,
    api_key: str,
    model_id: str,
    temperature: float,
    max_tokens: int,
    reasoning: str,
    timeout_seconds: float,
) -> None:
    if not 1 <= len(model_id.strip()) <= 160:
        raise ValidationFailed("model id must contain 1-160 characters")
    if not api_key or not api_key.strip():
        raise ValidationFailed("api key is required")
    if not all(0x21 <= ord(character) <= 0x7E for character in api_key.strip()):
        raise ValidationFailed("模型密钥包含无效字符，请重新填写")
    if reasoning not in REASONING_MODES:
        raise ValidationFailed("reasoning mode must be auto, on, or off")
    if not 0.0 <= float(temperature) <= 2.0:
        raise ValidationFailed("temperature must be within [0, 2]")
    if int(max_tokens) < 2_048:
        raise ValidationFailed("max tokens must be at least 2048")
    if not 0.0 < float(timeout_seconds) <= 300.0:
        raise ValidationFailed("timeout must be within (0, 300] seconds")
    try:
        chat_completion_endpoint(endpoint_url)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from None

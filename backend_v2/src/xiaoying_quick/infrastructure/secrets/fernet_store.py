from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken


class SecretStoreError(RuntimeError):
    pass


class LocalFernetSecretStore:
    """Small local encrypted store for Quick/dev deployments.

    Production can replace this adapter with Vault/KMS without changing the
    data-source module. The key and ciphertext file are always mode 0600.
    """

    def __init__(
        self, *, store_path: Path, key_path: Path, key_from_env: str | None = None
    ) -> None:
        self._store_path = store_path
        self._key_path = key_path
        self._lock = threading.RLock()
        self._fernet = Fernet(self._load_key(key_from_env))

    def put(self, value: str, *, current_ref: str | None = None) -> str:
        if not value:
            raise SecretStoreError("secret value cannot be empty")
        with self._lock:
            payload = self._load_payload()
            secret_ref = current_ref or f"secret_{uuid4().hex}"
            payload[secret_ref] = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
            self._save_payload(payload)
            return secret_ref

    def get(self, secret_ref: str) -> str:
        with self._lock:
            payload = self._load_payload()
            token = payload.get(secret_ref)
            if token is None:
                raise SecretStoreError("secret reference not found")
            try:
                return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
            except InvalidToken as exc:
                raise SecretStoreError(
                    "secret cannot be decrypted with the configured key"
                ) from exc

    def delete(self, secret_ref: str) -> None:
        with self._lock:
            payload = self._load_payload()
            if secret_ref in payload:
                del payload[secret_ref]
                self._save_payload(payload)

    def _load_key(self, configured: str | None) -> bytes:
        if configured:
            try:
                key = configured.encode("ascii")
                Fernet(key)
                return key
            except (ValueError, TypeError) as exc:
                raise SecretStoreError("XIAOYING_MASTER_KEY is not a valid Fernet key") from exc
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        self._atomic_write(self._key_path, key)
        return key

    def _load_payload(self) -> dict[str, str]:
        if not self._store_path.exists():
            return {}
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError("encrypted secret store is unreadable") from exc
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()
        ):
            raise SecretStoreError("encrypted secret store has an invalid format")
        return data

    def _save_payload(self, payload: dict[str, str]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._atomic_write(self._store_path, body)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            os.chmod(path, 0o600)
        finally:
            if temp.exists():
                temp.unlink()

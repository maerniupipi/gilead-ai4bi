from __future__ import annotations

import json

from xiaoying_quick.infrastructure.secrets.fernet_store import LocalFernetSecretStore


def test_secret_is_encrypted_and_rotatable(tmp_path) -> None:
    store_path = tmp_path / "secrets.json"
    key_path = tmp_path / "master.key"
    store = LocalFernetSecretStore(store_path=store_path, key_path=key_path)
    ref = store.put("never-store-plain-text")

    assert store.get(ref) == "never-store-plain-text"
    assert "never-store-plain-text" not in store_path.read_text(encoding="utf-8")
    assert ref in json.loads(store_path.read_text(encoding="utf-8"))
    assert oct(store_path.stat().st_mode & 0o777) == "0o600"

    same_ref = store.put("rotated", current_ref=ref)
    assert same_ref == ref
    assert store.get(ref) == "rotated"

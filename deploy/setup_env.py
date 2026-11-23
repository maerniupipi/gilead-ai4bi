"""Create a private environment file for a fresh checkout without overwriting existing keys."""

from __future__ import annotations

import argparse
import base64
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "backend_v2/.env")
    parser.add_argument("--environment", choices=("development", "production"), default="development")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("配置文件已存在，已保留原有密钥。请直接编辑需要调整的配置项。")
    production = args.environment == "production"
    database_url = os.environ.get(
        "XIAOYING_DATABASE_URL", "sqlite:///./var/control.sqlite3"
    )
    if production and "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS" not in os.environ:
        raise SystemExit("生产配置需要通过 XIAOYING_DATA_SOURCE_ALLOWED_HOSTS 指定业务数据库主机。")
    values = {
        "XIAOYING_ENVIRONMENT": args.environment,
        "XIAOYING_CHATBOT_MODE": "dual",
        "XIAOYING_DATABASE_URL": database_url,
        "XIAOYING_DB_AUTO_CREATE": "false",
        "XIAOYING_AUTH_HMAC_SECRET": secrets.token_urlsafe(48),
        "XIAOYING_SQL_APPROVAL_HMAC_SECRET": secrets.token_urlsafe(48),
        "XIAOYING_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "XIAOYING_PROVISION_TOKEN": secrets.token_urlsafe(32),
        "XIAOYING_AUTH_TOKEN_TTL_SECONDS": "28800",
        "XIAOYING_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "XIAOYING_BOOTSTRAP_ADMIN_PASSWORD": os.environ.get(
            "GILEAD_ADMIN_PASSWORD", secrets.token_urlsafe(18)
        ),
        "XIAOYING_SECRET_STORE_PATH": "var/secrets.json",
        "XIAOYING_SECRET_KEY_PATH": "var/master.key",
        "XIAOYING_BRANDING_ASSETS_PATH": "var/branding",
        "XIAOYING_KNOWLEDGE_ROOT": "../knowledge_gilead",
        "XIAOYING_JOB_MAX_WORKERS": "2",
        "XIAOYING_DATABASE_POOL_SIZE": "5",
        "XIAOYING_DATABASE_MAX_OVERFLOW": "5",
        "XIAOYING_LAB_FALLBACK": "off",
        "XIAOYING_LAB_FALLBACK_ON_ERROR": "false",
        "XIAOYING_ALLOW_SQLITE_DATA_SOURCES": "false",
        "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS": os.environ.get(
            "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS", "127.0.0.1,localhost"
        ),
        "XIAOYING_CORS_ALLOWED_ORIGINS": "http://127.0.0.1:15173,http://localhost:15173",
        "XIAOYING_STATIC_ROOT": "../frontend/dist" if production else "",
        "XIAOYING_MODEL_ENDPOINT_URL": "",
        "XIAOYING_MODEL_API_KEY": "",
        "XIAOYING_MODEL_ID": "",
        "XIAOYING_MODEL_MAX_TOKENS": "16384",
        "XIAOYING_MODEL_TIMEOUT_SECONDS": "180",
    }
    if not 8 <= len(values["XIAOYING_BOOTSTRAP_ADMIN_PASSWORD"].encode("utf-8")) <= 1024:
        raise SystemExit("管理员密码必须包含 8 至 1024 个 UTF-8 字节。")
    if any("\n" in value or "\r" in value for value in values.values()):
        raise SystemExit("配置项不能包含换行符。")
    # JSON quoting is accepted by python-dotenv and protects URL/password characters.
    import json

    content = "# Generated private configuration. Keep and back up the master key.\n" + "\n".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}" for name, value in values.items()
    ) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)
    print(f"已生成 {args.output}（权限 0600）。管理员密码见配置中的 BOOTSTRAP_ADMIN_PASSWORD。")
    print("默认开放数据库与 XLSX 两个助手；登录后在模型管理中填写并启用模型。")


if __name__ == "__main__":
    main()

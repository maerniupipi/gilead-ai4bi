"""Provision the five independent Gilead demo users and their private board copies."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.infrastructure.persistence.provision import apply_schema
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.workspace import WorkspaceStore
from xiaoying_quick.modules.identity.contracts import Role
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.shared.errors import Conflict, ValidationFailed

USERNAMES = tuple(f"Gilead{index:03d}" for index in range(1, 6))


def provision(data_dir: Path, password: str, template: dict) -> list[dict]:
    if not 8 <= len(password) <= 1024:
        raise ValidationFailed("请通过 GILEAD_DEMO_PASSWORD 提供有效密码")
    if (
        template.get("id") != "pharma-moc-2026-demo-v1"
        or len(template.get("items", [])) != 4
    ):
        raise ValidationFailed("请提供包含四项内容的医药 MOC 默认看板模板")
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{data_dir / 'control.sqlite3'}"
    engine = build_engine(database_url)
    hasher = PasswordHasher()
    token_service = HMACTokenService(
        secret=secrets.token_urlsafe(48), issuer="gilead-provision", ttl_seconds=3600
    )
    try:
        apply_schema(engine, database_url)
        factory = build_session_factory(engine)
        users = []
        with session_scope(factory) as database:
            identity = IdentityService(
                SqlAlchemyUserRepository(database), hasher, token_service
            )
            for username in USERNAMES:
                user = identity.get_by_username(username)
                if user is None:
                    user = identity.create_user(username=username, password=password)
                elif (
                    user.role is not Role.USER
                    or not user.is_active
                    or not hasher.verify(password, user.password_digest)
                ):
                    raise Conflict(
                        f"{username} 已存在且账号配置不同，请先核对部署数据目录"
                    )
                users.append(user)
        ChatbotStore(data_dir / "chatbots.sqlite3", xlsx_only=True)
        boards = WorkspaceStore(data_dir / "workspaces.sqlite3")
        return [
            {
                "username": user.username,
                "user_id": user.id,
                "default_board_id": boards.seed_default(user.id, template)["id"],
            }
            for user in users
        ]
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).with_name("pharma-moc-board.json"),
    )
    args = parser.parse_args()
    template = json.loads(args.template.read_text(encoding="utf-8"))
    result = provision(
        args.data_dir, os.environ.get("GILEAD_DEMO_PASSWORD", ""), template
    )
    print(json.dumps({"accounts": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import pytest

from xiaoying_quick.modules.knowledge.content_guard import (
    KnowledgeContentGuard,
    UnsafeKnowledgeContent,
)


@pytest.mark.parametrize(
    "content",
    [
        "password = super-secret",
        "api_key: sk-thisshouldneverpersist1234",
        "mysql+pymysql://root:secret@db.internal/sales",
        "postgresql://db.internal:5432/analytics",
        "sqlite:////srv/data/sales.db",
        "jdbc:mysql://db.internal:3306/sales",
        "Server=db.internal;Database=sales;Uid=reader",
        "db_username = readonly_sales",
        "ＡＰＩ＿ＫＥＹ：sk-thisshouldneverpersist1234",
        "Authorization: Bearer abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY----- secret",
    ],
)
def test_credentials_cannot_become_knowledge(content: str) -> None:
    with pytest.raises(UnsafeKnowledgeContent):
        KnowledgeContentGuard().validate(content)


def test_normal_domain_correction_is_allowed() -> None:
    assert KnowledgeContentGuard().validate("提到 demand 时优先路由到 Demand 实验室")

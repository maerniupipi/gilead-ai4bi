from __future__ import annotations

import re
import unicodedata


class UnsafeKnowledgeContent(ValueError):
    pass


class KnowledgeContentGuard:
    """Fail closed on common credentials and connection strings before persistence."""

    _PATTERNS = (
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret|password|"
            r"passwd|private[_-]?key|authorization)\s*[:=]\s*\S+"
        ),
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mssql|oracle|sqlite|"
            r"mongodb(?:\+srv)?|redis)(?:\+[a-z0-9_]+)?://\S+"
        ),
        re.compile(r"(?i)\bjdbc:[a-z0-9_]+://\S+"),
        re.compile(
            r"(?i)\b(?:server|host)\s*=\s*[^;,\s]+\s*;[^\n]{0,500}"
            r"\b(?:database|dbname|uid|user(?:name)?|pwd|password)\s*="
        ),
        re.compile(r"(?i)\b(?:db[_-]?user(?:name)?|db[_-]?account)\s*[:=]\s*\S+"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )

    def validate(self, content: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", content).strip().split())
        if not normalized:
            raise UnsafeKnowledgeContent("知识内容不能为空")
        if len(normalized) > 8_000:
            raise UnsafeKnowledgeContent("单条知识内容过长")
        if any(pattern.search(normalized) for pattern in self._PATTERNS):
            raise UnsafeKnowledgeContent("内容疑似包含凭据或连接密钥，禁止沉淀")
        return normalized

    def validate_markdown(self, content: str) -> str:
        from .library import MAX_MARKDOWN_BYTES

        if not content.strip() or "\0" in content:
            raise UnsafeKnowledgeContent("请选择非空的 UTF-8 Markdown 文档")
        if len(content.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            raise UnsafeKnowledgeContent("Markdown 文件最大为 1 MiB")
        normalized = " ".join(unicodedata.normalize("NFKC", content).split())
        if any(pattern.search(normalized) for pattern in self._PATTERNS):
            raise UnsafeKnowledgeContent("内容疑似包含凭据或连接密钥，禁止沉淀")
        return content

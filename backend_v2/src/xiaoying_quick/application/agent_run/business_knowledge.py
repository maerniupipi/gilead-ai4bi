"""The paired assistant and the application's reader use the same published documents."""
import asyncio
import json

from xiaoying_quick.infrastructure.search.business_library import BusinessLibrary
from xiaoying_quick.modules.agent.contracts import ToolCallResult, ToolSpec
from xiaoying_quick.modules.knowledge.library import MAX_READ_CHARS


def business_knowledge_tools():
    def run(ctx, operation):
        with ctx.dependency("knowledge_session_factory")() as db:
            return operation(BusinessLibrary(db, ctx.dependency("knowledge_settings")))

    async def search(ctx, args):
        phrase = str(args.get("query") or "").strip()
        if not phrase:
            return ToolCallResult(False, "请输入业务术语或问题。")
        hits = await asyncio.to_thread(run, ctx, lambda library: library.search(phrase[:1000], limit=5))
        if not hits:
            return ToolCallResult(True, "已发布的业务知识中没有匹配章节。", {"hits": []})
        return ToolCallResult(True, json.dumps(hits, ensure_ascii=False), {"hits": hits})

    async def read(ctx, args):
        key = str(args.get("document_id") or "")
        section, offset = args.get("section", 0), args.get("offset", 0)
        if any(type(n) is not int or n < 0 for n in (section, offset)):
            return ToolCallResult(False, "章节和偏移量必须为非负整数。")
        doc = await asyncio.to_thread(run, ctx, lambda library: library.documents().get(key))
        if doc is None or doc.reference or section >= len(doc.sections):
            return ToolCallResult(False, "找不到该业务文档或章节，请重新检索。")
        heading, content = doc.sections[section]
        if offset > len(content):
            return ToolCallResult(False, "偏移量超过章节长度。")
        end = min(len(content), offset + MAX_READ_CHARS)
        data = {"document_id": key, "filename": doc.filename, "version": doc.version, "section": section,
                "heading": heading, "content": content[offset:end], "url": doc.link(section),
                "next_offset": end if end < len(content) else None, "total_sections": len(doc.sections)}
        return ToolCallResult(True, json.dumps(data, ensure_ascii=False), data)

    return (
        ToolSpec("knowledge_search", "在应用知识库检索已发布的业务术语、规则和指标口径，返回文件、章节、原文摘录和链接。",
                 {"type": "object", "properties": {"query": {"type": "string", "description": "要检索的术语或业务问题"}},
                  "required": ["query"], "additionalProperties": False}, search),
        ToolSpec("knowledge_read", "按知识检索返回的文档编号和章节阅读原文，长章节通过偏移量续读。",
                 {"type": "object", "properties": {
                     "document_id": {"type": "string", "description": "知识检索返回的 document_id"},
                     "section": {"type": "integer", "minimum": 0, "description": "知识检索返回的章节序号"},
                     "offset": {"type": "integer", "minimum": 0, "description": "长章节续读位置，首次为 0"}},
                  "required": ["document_id", "section"], "additionalProperties": False}, read),
    )

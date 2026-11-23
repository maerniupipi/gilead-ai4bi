"""Inspect the bound workbook without treating field profiles as business results."""

from __future__ import annotations

import json

from xiaoying_quick.modules.agent import ToolCallResult, ToolSpec
from xiaoying_quick.shared.errors import ValidationFailed


def build_inspect_workbook_tool() -> ToolSpec:
    async def execute(context, arguments):
        try:
            profile = context.dependency("workbook_inspect")(
                str(arguments.get("table") or ""), arguments.get("columns")
            )
            return ToolCallResult(
                ok=True, output=json.dumps(profile, ensure_ascii=False), payload=profile,
            )
        except ValidationFailed as error:
            return ToolCallResult(ok=False, output=str(error))

    return ToolSpec(
        name="inspect_workbook",
        description=(
            "检查本轮已绑定Excel中一个sheet的相关字段，返回全部行的类型、空值、取值数量、"
            "数值范围、少量示例与可用的Excel格式提示。字段或单位含义不清时先检查，再决定是否澄清。"
            "每次最多10列，省略columns时检查前10列，可以分批检查。"
            "此结果仅用于理解文件，不能当作经营结果画图。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "工作簿结构中的完整wb_表名"},
                "columns": {
                    "type": "array", "minItems": 1, "maxItems": 10,
                    "items": {"type": "string"}, "description": "当前问题需要核验的真实字段名",
                },
            },
            "required": ["table"], "additionalProperties": False,
        },
        executor=execute,
    )

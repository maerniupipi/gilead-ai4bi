"""Connect a chart design to verified query tables without accepting invented data."""

from __future__ import annotations

import json

from xiaoying_quick.application.agent_run.tools import snapshot_query_table
from xiaoying_quick.application.charts.analysis import build_analysis_bundle
from xiaoying_quick.modules.agent import ToolCallResult, ToolSpec
from xiaoying_quick.shared.errors import ValidationFailed


def build_present_chart_tool(*, require_units: bool = False) -> ToolSpec:
    async def execute(context, arguments):
        def selected(key, required=False):
            reference = arguments.get(key)
            if reference is None and not required:
                return None
            if not isinstance(reference, str) or not reference:
                raise ValidationFailed(f"{key} 必须指向本轮已核验的查询结果")
            artifact = context.dependency("artifacts").get(reference)
            if (
                not artifact
                or artifact.get("run_id") != context.run_id
                or artifact.get("kind") != "tool_result"
            ):
                raise ValidationFailed(f"{key} 必须指向本轮已核验的查询结果")
            body = artifact.get("payload", {})
            payload = body.get("payload", {})
            if (
                body.get("name") != "query_db"
                or not body.get("ok")
                or payload.get("sql_review", {}).get("ok") is False
            ):
                raise ValidationFailed(f"{key} 必须指向本轮已核验的查询结果")
            table = snapshot_query_table(payload)
            if table is None:
                raise ValidationFailed("查询结果缺少可用数据")
            return table

        try:
            table = selected("query_ref", required=True)
            summary = selected("summary_ref")
            requested = arguments.get("metrics")
            if requested is not None and (
                not isinstance(requested, list)
                or any(not isinstance(item, dict) for item in requested)
            ):
                raise ValidationFailed("metrics 必须是指标配置列表")
            if require_units and (
                not requested or any(not str(item.get("unit") or "").strip() for item in requested)
            ):
                raise ValidationFailed(
                    "请先根据文件或用户确认各指标的单位，并在metrics中逐项填写column和unit。"
                    "单位不明确时先澄清，不默认金额为元或销量为盒。"
                )
            payload = build_analysis_bundle(
                table,
                summary=summary,
                title=str(arguments.get("title") or "医药经营分析"),
                dimension=arguments.get("dimension"),
                metrics=requested,
                default_type=str(arguments.get("default_type") or "combo"),
                scope=str(arguments.get("scope") or ""),
            )
            payload["query_ref"] = arguments["query_ref"]
            artifacts = context.dependency("artifacts")
            artifacts.append(run_id=context.run_id, kind="analysis_chart", payload=payload)
            context.emit("chart.ready", payload)
            values = [
                {"指标": item["label"], "值": item["value"], "单位": item["unit"]}
                for item in payload["kpis"]
            ]
            return ToolCallResult(
                ok=True,
                output="已生成关键数字、复合图与可分页数据表，支持切换图表和加入看板。"
                "下列百分比以小数表示，回答时按百分数呈现。\n"
                + json.dumps(values, ensure_ascii=False),
                payload={
                    "chart_types": [item["type"] for item in payload["charts"]],
                    "kpis": payload["kpis"],
                    "row_count": payload["data"]["row_count"],
                },
            )
        except (ValidationFailed, TypeError, ValueError) as error:
            return ToolCallResult(ok=False, output=str(error))

    return ToolSpec(
        name="present_chart",
        description=(
            "把已核验 query_db 结果呈现为顶部关键数字、可切换复合图和数据表。"
            "不接受行数据或手填数字。主查询应保留金额、目标、数量、比率及对应分子分母。"
            "总体去重机构数等来自单独的一行汇总，使用summary_ref指定。"
            "一张图可有多根柱、多条线和最多三类单位，按字段自动推荐适合的图表。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query_ref": {
                    "type": "string",
                    "description": "主要图表query_db返回的固定query_ref，原样复制artifact_编号",
                },
                "summary_ref": {
                    "type": "string",
                    "description": "同范围一行总体汇总返回的固定query_ref，可省略",
                },
                "title": {"type": "string", "description": "简明业务标题"},
                "scope": {"type": "string", "description": "本次查询已确认的期间、范围和单位"},
                "dimension": {"type": "string", "description": "分组列名，例如月份或城市"},
                "default_type": {
                    "type": "string",
                    "enum": [
                        "combo",
                        "grouped_bar",
                        "line",
                        "horizontal_bar",
                        "area",
                        "pie",
                        "donut",
                        "pareto",
                        "scatter",
                        "bubble",
                        "heatmap",
                        "stacked_bar",
                        "stacked_area",
                        "radar",
                    ],
                },
                "metrics": {
                    "type": "array",
                    "maxItems": 8,
                    "description": (
                        "column取自主查询query_ref，按已确认口径填写单位。"
                        "比率须保留分子分母，总体去重数和记录数由summary_ref自动补充。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "unit": {
                                "type": "string",
                                "description": "已确认的原值单位，例如元、万元、USD、盒、支、条或%",
                            },
                            "chart": {
                                "type": "string",
                                "enum": ["bar", "line", "kpi"],
                                "description": "kpi表示只放在顶部数字区",
                            },
                            "aggregate": {
                                "type": "string",
                                "enum": ["sum", "ratio", "growth", "distinct"],
                            },
                            "numerator": {"type": "string"},
                            "denominator": {"type": "string"},
                            "scale": {
                                "type": "string",
                                "enum": ["fraction", "percent"],
                                "description": "默认fraction，0.9表示90%",
                            },
                        },
                        "required": ["column", "unit"] if require_units else ["column"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": (
                ["query_ref", "title", "metrics"] if require_units else ["query_ref", "title"]
            ),
            "additionalProperties": False,
        },
        executor=execute,
    )

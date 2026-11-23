"""Download formats preserve scoped data, permissions and the current chart view."""

from __future__ import annotations

import base64
import io
import zipfile
from urllib.parse import unquote

import pytest
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader
from test_workspace import case as workspace_case
from test_workspace import create

from xiaoying_quick.application.charts.analysis import build_analysis_bundle
from xiaoying_quick.infrastructure.persistence.models.chat import ChatMessageModel, ChatSessionModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunModel
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.modules.runs.service import RunService

URL = "/api/v2/exports"
case = workspace_case


def png():
    output = io.BytesIO()
    Image.new("RGB", (1600, 680), "white").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def prepared(client, case, source, **extra):
    response = client.post(
        f"{URL}/prepare", headers=case["headers"]["owner"], json={"source": source, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def download(client, case, source, format_name, **extra):
    ready = prepared(client, case, source, **extra)
    response = client.post(
        f"{URL}/download",
        headers=case["headers"]["owner"],
        json={
            "source": source,
            "format": format_name,
            "document_key": ready["document_key"],
            "images": {chart["id"]: png() for chart in ready["charts"]},
            **extra,
        },
    )
    assert response.status_code == 200, response.text[:500]
    assert "private, no-store" in response.headers["cache-control"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    return response


@pytest.mark.parametrize("format_name", ["pptx", "xlsx", "pdf"])
def test_chart_downloads_are_real_files_with_data(client, case, format_name):
    source = {"kind": "answer_chart", "run_id": case["run_id"], "chart_type": "bar"}
    response = download(client, case, source, format_name)
    data = response.content
    if format_name == "pptx":
        assert "presentationml" in response.headers["content-type"]
        presentation = Presentation(io.BytesIO(data))
        assert len(presentation.slides) >= 2
        texts = [
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.has_text_frame
        ]
        assert any("问答图表" in text or "区域销售" in text for text in texts)
        assert any(shape.has_table for slide in presentation.slides for shape in slide.shapes)
        assert any(
            name.startswith("ppt/media/") for name in zipfile.ZipFile(io.BytesIO(data)).namelist()
        )
    elif format_name == "xlsx":
        assert "spreadsheetml" in response.headers["content-type"]
        book = load_workbook(io.BytesIO(data))
        rows = [list(row) for sheet in book for row in sheet.values]
        assert any(row[:2] == ["华南", 150] for row in rows)
        assert any(row[:2] == ["华东", 500] for row in rows)
        assert any(sheet.freeze_panes for sheet in book)
        assert any(
            name.startswith("xl/media/") for name in zipfile.ZipFile(io.BytesIO(data)).namelist()
        )
    else:
        assert response.headers["content-type"] == "application/pdf"
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "华南" in text and "500" in text
        assert b"/FontFile2" in data


def test_whole_answer_export_uses_all_saved_chart_events_and_selected_view(client, case, app):
    payload = build_analysis_bundle(
        {
            "columns": ["月份", "销售金额", "目标金额", "达成率"],
            "rows": [["2026-10", 100, 200, 0.5]],
        },
        title="月度经营",
        scope="2026年10月，元",
    )
    owner = case["users"]["owner"]
    with app.state.session_factory() as db:
        db.get(RunModel, case["run_id"]).question = "请按月份分析城市产品销售与目标达成情况" * 10
        db.add(ChatSessionModel(id="answer-session", owner_id=owner.id, title="经营分析"))
        db.flush()
        db.add(
            ChatMessageModel(
                id="answer-message",
                session_id="answer-session",
                run_id=case["run_id"],
                role="assistant",
                content="销售已核验。\n\n| 指标 | 数值 |\n|---|---|\n| 金额 | 100 |",
            )
        )
        runs = RunService(SqlAlchemyRunRepository(db))
        first = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=payload)
        second = runs.append_event(
            run_id=case["run_id"],
            event_type="chart.ready",
            payload={
                **payload,
                "title": "城市下钻",
            },
        )
        # This fixture also owns a report; omit it to exercise the chart-card answer path.
        from sqlalchemy import delete

        from xiaoying_quick.infrastructure.persistence.models.artifacts import RunArtifactModel

        db.execute(delete(RunArtifactModel).where(RunArtifactModel.run_id == case["run_id"]))
        db.commit()
    source = {
        "kind": "answer",
        "run_id": case["run_id"],
        "views": {str(first.cursor): {"chart_type": "line", "show_values": True}},
    }
    ready = prepared(client, case, source)
    assert [item["id"] for item in ready["charts"]] == [
        f"chart-{first.cursor}",
        f"chart-{second.cursor}",
    ]
    assert ready["charts"][0]["option"]["series"][0]["type"] == "line"
    assert ready["charts"][0]["show_values"] is True
    response = download(client, case, source, "xlsx")
    filename = unquote(response.headers["content-disposition"].split("filename*=UTF-8''")[1])
    assert len(filename.encode("utf-8")) < 200 and filename.endswith(".xlsx")
    workbook = load_workbook(io.BytesIO(response.content))
    values = [
        str(value)
        for sheet in workbook
        for row in sheet.values
        for value in row
        if value is not None
    ]
    assert "销售已核验。" in values and "月份" in values and "金额" in values


def test_board_exports_obey_snapshot_scope_and_read_only_sharing(client, case):
    board = create(client, case, pin={**case["source"], "section": "report"})
    source = {"kind": "board", "board_id": board["id"], "version": board["version"]}
    response = download(client, case, source, "xlsx")
    book = load_workbook(io.BytesIO(response.content))
    text = "\n".join(str(value) for sheet in book for row in sheet.values for value in row)
    assert "华南" in text and "华东" not in text and "PRIVATE SQL" not in text
    ready = prepared(client, case, source)
    denied = client.post(
        f"{URL}/prepare", headers=case["headers"]["outside"], json={"source": source}
    )
    assert denied.status_code == 404
    stale = client.post(
        f"{URL}/prepare",
        headers=case["headers"]["owner"],
        json={"source": {**source, "version": board["version"] + 1}},
    )
    assert stale.status_code == 409
    mismatch = client.post(
        f"{URL}/download",
        headers=case["headers"]["owner"],
        json={
            "source": source,
            "format": "xlsx",
            "document_key": "0" * 64,
            "images": {chart["id"]: png() for chart in ready["charts"]},
        },
    )
    assert mismatch.status_code == 409
    shared = client.put(
        f"/api/v2/workspace/boards/{board['id']}/access",
        headers=case["headers"]["owner"],
        json={
            "version": board["version"],
            "members": [{"user_id": case["users"]["viewer"].id, "role": "viewer"}],
        },
    )
    assert shared.status_code == 200, shared.text
    source["version"] = shared.json()["version"]
    viewer_ready = client.post(
        f"{URL}/prepare", headers=case["headers"]["viewer"], json={"source": source}
    )
    assert viewer_ready.status_code == 200, viewer_ready.text
    viewer_file = client.post(
        f"{URL}/download",
        headers=case["headers"]["viewer"],
        json={
            "source": source,
            "format": "xlsx",
            "document_key": viewer_ready.json()["document_key"],
            "images": {chart["id"]: png() for chart in viewer_ready.json()["charts"]},
        },
    )
    assert viewer_file.status_code == 200, viewer_file.text[:500]
    book = load_workbook(io.BytesIO(viewer_file.content))
    text = "\n".join(str(value) for sheet in book for row in sheet.values for value in row)
    assert "华南" in text and "华东" not in text and "PRIVATE SQL" not in text


@pytest.mark.parametrize("legacy_event", [False, True])
def test_chart_excel_recovers_saved_query_rows_beyond_the_chart_preview(
    client, case, app, legacy_event
):
    table = {
        "columns": ["终端", "销售金额"],
        "rows": [[f"终端{index}", index + 1] for index in range(1100)],
    }
    payload = build_analysis_bundle(table, title="终端销售", scope="全部终端，元")
    with app.state.session_factory() as db:
        query_ref = SqlAlchemyArtifactRepository(db).append(
            run_id=case["run_id"],
            kind="tool_result",
            payload={"name": "query_db", "ok": True, "payload": table},
        )
        runs = RunService(SqlAlchemyRunRepository(db))
        if legacy_event:
            runs.append_event(
                run_id=case["run_id"],
                event_type="tool.call",
                payload={"name": "present_chart", "arguments": {"query_ref": query_ref}},
            )
        else:
            payload["query_ref"] = query_ref
        event = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=payload)
        db.commit()
    source = {
        "kind": "answer_analysis",
        "run_id": case["run_id"],
        "chart_cursor": event.cursor,
        "chart_type": payload["default_type"],
    }
    response = download(client, case, source, "xlsx")
    book = load_workbook(io.BytesIO(response.content))
    assert any(row[:2] == ("终端1099", 1100) for sheet in book for row in sheet.values)


def test_download_rejects_forged_data_images_and_cross_account_sources(client, case):
    source = {"kind": "answer_chart", "run_id": case["run_id"], "chart_type": "bar"}
    assert client.post(f"{URL}/prepare", json={"source": source}).status_code == 401
    assert client.post(
        f"{URL}/prepare", headers=case["headers"]["outside"], json={"source": source}
    ).status_code in (403, 404)
    ready = prepared(client, case, source)
    body = {"source": source, "format": "pdf", "document_key": ready["document_key"], "images": {}}
    assert (
        client.post(f"{URL}/download", headers=case["headers"]["owner"], json=body).status_code
        == 422
    )
    body["images"] = {ready["charts"][0]["id"]: "https://example.com/image.png"}
    assert (
        client.post(f"{URL}/download", headers=case["headers"]["owner"], json=body).status_code
        == 422
    )
    body["images"] = {ready["charts"][0]["id"]: "data:image/png;base64,bm90LXBuZw=="}
    assert (
        client.post(f"{URL}/download", headers=case["headers"]["owner"], json=body).status_code
        == 422
    )
    assert (
        client.post(
            f"{URL}/prepare",
            headers=case["headers"]["owner"],
            json={"source": source, "rows": [["伪造", 1]]},
        ).status_code
        == 422
    )

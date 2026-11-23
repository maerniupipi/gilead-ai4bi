"""Dashboard workspace with per-board owner, editor and viewer authorization."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xiaoying_quick.api.dependencies import CurrentPrincipal, DbSession, RunServiceDep, get_settings
from xiaoying_quick.application.workspace_assets import resolve_asset
from xiaoying_quick.infrastructure.persistence.repositories.identity import SqlAlchemyUserRepository
from xiaoying_quick.infrastructure.workspace import WorkspaceStore
from xiaoying_quick.shared.errors import Forbidden, ValidationFailed

from .chatbots import get_chatbot_store

router = APIRouter(prefix="/api/v2/workspace", tags=["dashboard-workspace"])


def get_workspace(request: Request) -> WorkspaceStore:
    settings = get_settings(request)
    return WorkspaceStore(settings.secret_store_path.parent / "workspaces.sqlite3", database_url=settings.database_url)


Store = Annotated[WorkspaceStore, Depends(get_workspace)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PinSource(Strict):
    run_id: str = Field(min_length=1, max_length=64)
    kind: Literal["answer_analysis", "answer_chart", "chart_table", "answer_table", "report"]
    title: str = Field(default="", max_length=120)
    chart_type: str | None = Field(default=None, max_length=32)
    chart_cursor: int | None = Field(default=None, ge=1)
    table_index: int | None = Field(default=None, ge=0)
    table_view: Literal["chart", "details"] = "chart"
    report_id: str | None = Field(default=None, max_length=64)
    report_revision: int | None = Field(default=None, ge=1)
    section: Literal["report", "trend", "contribution", "kpis"] = "report"
    state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bound_source(self):
        if self.kind == "report" and not (self.report_id and self.report_revision):
            raise ValueError("请提供报告及其版本")
        if self.kind in {"answer_analysis", "answer_chart", "chart_table"} and not self.chart_type:
            raise ValueError("请选择要收藏的图表样式")
        if self.kind == "answer_table" and self.table_index is None:
            raise ValueError("请选择要收藏的数据表")
        if len(json.dumps(self.state)) > 8000:
            raise ValueError("报告筛选过大")
        self.state = {
            key: value
            for key, value in self.state.items()
            if key
            in {
                "filters",
                "current_period",
                "window",
                "period",
                "metric",
                "dimension",
                "visible_columns",
                "chart_type",
            }
        }
        filters = self.state.get("filters", {})
        if (
            not isinstance(filters, dict)
            or len(filters) > 30
            or any(not isinstance(value, str) or len(value) > 500 for value in filters.values())
        ):
            raise ValueError("报告筛选格式无效")
        for key in ("period", "window", "metric", "dimension", "chart_type", "current_period"):
            if key in self.state and (
                not isinstance(self.state[key], str) or len(self.state[key]) > 100
            ):
                raise ValueError("报告视图字段必须为有效文本")
        if "visible_columns" in self.state:
            visible = self.state["visible_columns"]
            if (
                not isinstance(visible, list)
                or len(visible) > 150
                or any(not isinstance(value, str) or len(value) > 100 for value in visible)
            ):
                raise ValueError("显示字段格式无效")
        return self


class BoardFields(Strict):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1000)
    theme: Literal["commercial", "behavior", "general"] = "commercial"

    @model_validator(mode="after")
    def nonblank_name(self):
        if not self.name.strip():
            raise ValueError("请填写看板名称")
        return self


class CreateBoard(BoardFields):
    pin: PinSource | None = None


class UpdateBoard(BoardFields):
    version: int = Field(ge=1)


class LayoutItem(Strict):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    width: Literal["half", "full"] = "half"


class Layout(Strict):
    version: int = Field(ge=1)
    items: list[LayoutItem] = Field(max_length=40)


class Member(Strict):
    user_id: str = Field(min_length=1, max_length=64)
    role: Literal["viewer", "editor"]


class Access(Strict):
    version: int = Field(ge=1)
    members: list[Member] = Field(max_length=100)


def public_user(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_active": user.is_active,
    }


def with_owner(payload: dict, database) -> dict:
    owner = SqlAlchemyUserRepository(database).get_by_id(payload["owner_id"])
    return {
        **payload,
        "owner_name": (owner.display_name or owner.username) if owner else "原创建者",
    }


@router.get("/people")
def people(
    database: DbSession,
    principal: CurrentPrincipal,
    search: Annotated[str, Query(max_length=100)] = "",
) -> dict:
    del principal
    needle = search.strip().casefold()
    users = SqlAlchemyUserRepository(database).list_all()
    return {
        "items": [
            public_user(user)
            for user in users
            if user.is_active
            and (not needle or needle in (user.username + user.display_name).casefold())
        ][:50]
    }


@router.get("/boards")
def list_boards(store: Store, principal: CurrentPrincipal, database: DbSession) -> dict:
    return {"items": [with_owner(board, database) for board in store.list(principal.user_id)]}


@router.post("/boards", status_code=201)
def create_board(
    body: CreateBoard,
    request: Request,
    store: Store,
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
) -> dict:
    asset = (
        resolve_asset(
            body.pin.model_dump(),
            principal=principal,
            database=database,
            runs=runs,
            bot_store=get_chatbot_store(request),
        )
        if body.pin
        else None
    )
    board = store.create(principal.user_id, body.model_dump(exclude={"pin"}), asset)
    return with_owner(board, database)


@router.get("/boards/{board_id}")
def board_detail(
    board_id: str, store: Store, principal: CurrentPrincipal, database: DbSession
) -> dict:
    return with_owner(store.get(board_id, principal.user_id), database)


@router.put("/boards/{board_id}")
def update_board(
    board_id: str,
    body: UpdateBoard,
    store: Store,
    principal: CurrentPrincipal,
    database: DbSession,
) -> dict:
    return with_owner(
        store.update(
            board_id, principal.user_id, body.model_dump(exclude={"version"}), body.version
        ),
        database,
    )


@router.delete("/boards/{board_id}", status_code=204)
def delete_board(board_id: str, store: Store, principal: CurrentPrincipal) -> Response:
    store.delete(board_id, principal.user_id)
    return Response(status_code=204)


@router.post("/boards/{board_id}/items")
def add_item(
    board_id: str,
    body: PinSource,
    request: Request,
    store: Store,
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
) -> dict:
    board = store.get(board_id, principal.user_id)
    if board["my_role"] not in ("owner", "editor"):
        raise Forbidden("此看板为只读，请联系创建者授予编辑权限")
    asset = resolve_asset(
        body.model_dump(),
        principal=principal,
        database=database,
        runs=runs,
        bot_store=get_chatbot_store(request),
    )
    result = store.add(board_id, principal.user_id, asset)
    result["board"] = with_owner(result["board"], database)
    return result


@router.put("/boards/{board_id}/layout")
def update_layout(
    board_id: str,
    body: Layout,
    store: Store,
    principal: CurrentPrincipal,
    database: DbSession,
) -> dict:
    return with_owner(
        store.layout(
            board_id, principal.user_id, [item.model_dump() for item in body.items], body.version
        ),
        database,
    )


@router.get("/boards/{board_id}/access")
def get_access(
    board_id: str, store: Store, principal: CurrentPrincipal, database: DbSession
) -> dict:
    access = store.access(board_id, principal.user_id)
    users = SqlAlchemyUserRepository(database)
    members = []
    for member in access["members"]:
        user = users.get_by_id(member["user_id"])
        members.append({**member, "user": public_user(user) if user else None})
    owner = users.get_by_id(access["owner_id"])
    return {**access, "members": members, "owner": public_user(owner) if owner else None}


@router.put("/boards/{board_id}/access")
def set_access(
    board_id: str,
    body: Access,
    store: Store,
    principal: CurrentPrincipal,
    database: DbSession,
) -> dict:
    store.access(board_id, principal.user_id)
    users = SqlAlchemyUserRepository(database)
    for member in body.members:
        user = users.get_by_id(member.user_id)
        if user is None or not user.is_active:
            raise ValidationFailed("成员账号不存在或已停用，请刷新名单后重新选择")
    return with_owner(
        store.set_access(
            board_id, principal.user_id, [m.model_dump() for m in body.members], body.version
        ),
        database,
    )

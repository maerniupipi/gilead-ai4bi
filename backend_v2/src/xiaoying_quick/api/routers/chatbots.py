"""Chatbot directory, administrator configuration and workbook upload."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from xiaoying_quick.api.dependencies import (
    CurrentPrincipal,
    DbSession,
    get_settings,
    require_roles,
)
from xiaoying_quick.infrastructure.chatbots import (
    MAX_UPLOAD_BYTES,
    MAX_WORKBOOKS,
    ChatbotStore,
    can_use_chatbot,
)
from xiaoying_quick.infrastructure.persistence.repositories.identity import SqlAlchemyUserRepository
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.knowledge.lab_catalog import list_lab_documents
from xiaoying_quick.shared.errors import ValidationFailed

router = APIRouter(prefix="/api/v2", tags=["chatbots"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


def get_chatbot_store(request: Request) -> ChatbotStore:
    settings = get_settings(request)
    return ChatbotStore(
        settings.secret_store_path.parent / "chatbots.sqlite3",
        mode=settings.chatbot_mode,
        database_url=settings.database_url,
    )


StoreDep = Annotated[ChatbotStore, Depends(get_chatbot_store)]


class ChatbotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=48)
    description: str = Field(default="", max_length=280)
    category: Literal["ddi", "behavior", "general"] = "general"
    enabled: bool = True
    access: Literal["all", "roles", "users"] = "all"
    roles: list[Literal["user", "admin", "knowledge_reviewer", "data_source_admin"]] = Field(
        default_factory=list, max_length=4
    )
    user_ids: list[str] = Field(default_factory=list, max_length=200)
    lab_ids: list[str] = Field(default_factory=list, max_length=12)
    workbook_ids: list[str] = Field(default_factory=list, max_length=MAX_WORKBOOKS)
    sample: bool = False

    @model_validator(mode="after")
    def validate_configuration(self) -> ChatbotRequest:
        if not self.name.strip():
            raise ValueError("请填写 Chatbot 名称")
        if self.access == "roles" and not self.roles:
            raise ValueError("请选择至少一个开放角色")
        if self.access == "users" and not self.user_ids:
            raise ValueError("请选择至少一个开放账号")
        if self.enabled and not (self.lab_ids or self.workbook_ids):
            raise ValueError("请至少选择一个实验室或上传一个 XLSX 工作簿")
        self.lab_ids = list(dict.fromkeys(self.lab_ids))
        self.workbook_ids = list(dict.fromkeys(self.workbook_ids))
        return self


def validate_bindings(body: ChatbotRequest, request: Request, database: DbSession) -> None:
    known_labs = {item.lab_id for item in list_lab_documents(get_settings(request).knowledge_root)}
    from xiaoying_quick.infrastructure.persistence.models.lab_connection import LabConnectionModel
    row = database.get(LabConnectionModel, "workspace")
    pairs = ((row.profiles.get("bootcamp") or {}).get("labs") or {}) if row else {}
    configured = {key for key, pair in pairs.items() if pair.get("recall_api_access_id") and pair.get("api_access_id")}
    known_labs = configured or known_labs | {"actual"}
    if not set(body.lab_ids) <= known_labs:
        raise ValidationFailed("所选实验室不存在，请刷新实验室目录后重新选择")
    users = SqlAlchemyUserRepository(database)
    for user_id in body.user_ids:
        user = users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise ValidationFailed("所选账号不存在或已停用，请刷新账号列表后重新选择")


@router.get("/chatbots/entrances")
def entrances(store: StoreDep) -> list[dict]:
    # Before authentication disclose entry descriptions, never uploaded data.
    return [
        {
            **{key: bot[key] for key in ("id", "name", "description", "category", "sample")},
            "lab_count": len(bot["lab_ids"]),
            "workbook_count": len(bot["workbook_ids"]),
            "personal_uploads": bool(bot.get("personal_uploads")),
        }
        for bot in store.list()
        if bot["id"] in ("ddi", "behavior", "xlsx") and bot["enabled"]
    ]


@router.get("/chatbots")
def available_chatbots(store: StoreDep, principal: CurrentPrincipal) -> list[dict]:
    return [
        store.payload(bot, principal=principal)
        for bot in store.list() if can_use_chatbot(bot, principal)
    ]


@router.get("/admin/chatbots")
def all_chatbots(store: StoreDep, admin: AdminPrincipal) -> list[dict]:
    return [store.payload(bot, admin=True) for bot in store.list()]


@router.post("/admin/chatbots", status_code=201)
def create_chatbot(
    body: ChatbotRequest,
    request: Request,
    database: DbSession,
    store: StoreDep,
    admin: AdminPrincipal,
) -> dict:
    validate_bindings(body, request, database)
    return store.payload(store.save(body.model_dump()), admin=True)


@router.put("/admin/chatbots/{bot_id}")
def update_chatbot(
    bot_id: str,
    body: ChatbotRequest,
    request: Request,
    database: DbSession,
    store: StoreDep,
    admin: AdminPrincipal,
) -> dict:
    validate_bindings(body, request, database)
    return store.payload(store.save(body.model_dump(), bot_id), admin=True)


@router.post("/admin/chatbot-workbooks", status_code=201)
async def upload_workbook(
    store: StoreDep,
    admin: AdminPrincipal,
    file: Annotated[UploadFile, File()],
) -> dict:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationFailed("文件不能超过 10 MB")
    return await run_in_threadpool(store.save_workbook, file.filename or "", content)


@router.get("/chatbots/{bot_id}/workbooks")
def personal_workbooks(bot_id: str, store: StoreDep, principal: CurrentPrincipal) -> dict:
    bot = store.require(bot_id, principal)
    return {"items": store.payload(bot, principal=principal).get("workbooks", [])}


@router.post("/chatbots/{bot_id}/workbooks", status_code=201)
async def upload_personal_workbook(
    bot_id: str,
    store: StoreDep,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
) -> dict:
    store.require(bot_id, principal)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationFailed("文件不能超过 10 MB")
    return await run_in_threadpool(
        store.upload_personal_workbook,
        bot_id, principal.user_id, file.filename or "", content,
    )


@router.post("/chatbots/{bot_id}/workbook-uploads", status_code=202)
async def begin_personal_workbook_upload(
    bot_id: str,
    store: StoreDep,
    principal: CurrentPrincipal,
    background: BackgroundTasks,
    response: Response,
    file: Annotated[UploadFile, File()],
    upload_id: Annotated[str, Form(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")],
) -> dict:
    store.require(bot_id, principal)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    upload = await run_in_threadpool(
        store.begin_workbook_upload,
        bot_id, principal.user_id, upload_id, file.filename or "", content,
    )
    background.add_task(store.process_workbook_uploads)
    response.headers["Cache-Control"] = "no-store"
    return upload


@router.get("/chatbots/{bot_id}/workbook-uploads")
def pending_personal_workbook_uploads(
    bot_id: str, store: StoreDep, principal: CurrentPrincipal, background: BackgroundTasks,
    response: Response,
) -> dict:
    store.require(bot_id, principal)
    uploads = store.pending_workbook_uploads(bot_id, principal.user_id)
    if uploads:
        background.add_task(store.process_workbook_uploads)
    response.headers["Cache-Control"] = "no-store"
    return {"items": uploads}


@router.get("/chatbots/{bot_id}/workbook-uploads/{upload_id}")
def personal_workbook_upload_status(
    bot_id: str, upload_id: str, store: StoreDep, principal: CurrentPrincipal,
    background: BackgroundTasks, response: Response,
) -> dict:
    store.require(bot_id, principal)
    upload = store.workbook_upload(bot_id, principal.user_id, upload_id)
    if upload["status"] in ("queued", "processing"):
        background.add_task(store.process_workbook_uploads)
    response.headers["Cache-Control"] = "no-store"
    return upload


@router.delete("/chatbots/{bot_id}/workbooks/{workbook_id}", status_code=204)
def remove_personal_workbook(
    bot_id: str, workbook_id: str, store: StoreDep, principal: CurrentPrincipal,
) -> Response:
    store.require(bot_id, principal)
    store.remove_personal_workbook(bot_id, principal.user_id, workbook_id)
    return Response(status_code=204)

"""Per-account admission shared by workers, API processes and paired laboratories."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from .persistence.models.identity import IdentityUserModel
from .persistence.models.usage import QuotaHoldModel, QuotaResetModel, UsageEventModel
from xiaoying_quick.modules.usage.meter import current_attribution

MONTHLY_LIMIT = 10_000_000
SHANGHAI = ZoneInfo("Asia/Shanghai")
_factory = None
_started_at = ContextVar("quota_request_time", default=None)


def configure(factory):
    global _factory
    _factory = factory


def call_started():
    return _started_at.get()


def month_window(now):
    local = now.astimezone(SHANGHAI)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def balance(db, user_id, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = month_window(now)
    period = start.strftime("%Y-%m")
    reset = db.get(QuotaResetModel, (user_id, period))
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEventModel.total_tokens), 0)).where(
            UsageEventModel.user_id == user_id,
            UsageEventModel.created_at >= start.astimezone(timezone.utc),
            UsageEventModel.created_at < end.astimezone(timezone.utc),
        )
    )
    held = db.scalar(
        select(func.coalesce(func.sum(QuotaHoldModel.amount), 0)).where(
            QuotaHoldModel.user_id == user_id,
            QuotaHoldModel.expires_at > now,
            QuotaHoldModel.created_at >= start.astimezone(timezone.utc),
        )
    )
    used = max(0, int(total) - (reset.baseline if reset else 0))
    return {
        "user_id": user_id,
        "period": period,
        "used": used,
        "limit": MONTHLY_LIMIT,
        "remaining": max(0, MONTHLY_LIMIT - used),
        "reserved": int(held),
        "resets_at": end.isoformat(),
        "exhausted": used >= MONTHLY_LIMIT
        or db.get(QuotaHoldModel, exhausted_id(user_id, period)) is not None,
    }


def exhausted_id(user_id, period):
    from hashlib import sha256

    return "low_" + sha256((user_id + "/" + period).encode()).hexdigest()[:52]


def lock_user(db, uid):
    return db.scalar(select(IdentityUserModel).where(IdentityUserModel.id == uid).with_for_update())


class QuotaUnavailable(ValueError):
    pass


@contextmanager
def capacity(input_cost, output_cost=0):
    attr = current_attribution()
    if not attr or _factory is None:
        yield output_cost
        return
    now = datetime.now(timezone.utc)
    uid = attr.user_id
    hold = uuid4().hex
    with _factory() as db:
        if lock_user(db, uid) is None:
            yield output_cost
            return
        db.execute(
            delete(QuotaHoldModel).where(
                QuotaHoldModel.user_id == uid, QuotaHoldModel.expires_at <= now
            )
        )
        state = balance(db, uid, now)
        remaining = state["remaining"] - state["reserved"]
        if remaining < input_cost + int(output_cost > 0):
            if state["remaining"] < input_cost + int(output_cost > 0):
                db.merge(
                    QuotaHoldModel(
                        id=exhausted_id(uid, state["period"]),
                        user_id=uid,
                        created_at=now,
                        expires_at=month_window(now)[1],
                        amount=0,
                    )
                )
                db.commit()
            raise QuotaUnavailable("本月可用 Token 不足以完成本次请求，请缩短问题或联系管理员")
        permitted = min(output_cost, remaining - input_cost)
        db.add(
            QuotaHoldModel(
                id=hold,
                user_id=uid,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
                amount=input_cost + permitted,
            )
        )
        db.commit()
    mark = _started_at.set(now)
    try:
        yield permitted
    finally:
        _started_at.reset(mark)
        with _factory() as db:
            db.execute(delete(QuotaHoldModel).where(QuotaHoldModel.id == hold))
            db.commit()

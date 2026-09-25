"""报警中心接口：维护报警事件，覆盖确认报警、处置报警、忽略报警等动作。

列表与统计共用同一套过滤参数（报警编号 / 报警等级 / 触发时间段 / 状态），
保证统计口径与列表一致；置顶排序在服务端固定，前端刷新后顺序不丢。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.alarm import DISPOSE_SLA_HOURS, normalize_level
from app.services.alarm import AlarmService

router = APIRouter(prefix="/api/alarm", tags=["报警中心"])

service = AlarmService()

LIST_FIELDS = ["报警编号", "报警类型", "报警等级", "触发点位", "触发时间", "确认人员", "处置措施", "报警状态", "处置时效"]
STATUSES = ["待确认", "已确认", "已处置", "已忽略"]


def _validate_range(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    """校验触发时间段：日期格式与先后顺序非法时直接 400，避免静默返回空。"""
    start_day: date | None = None
    end_day: date | None = None
    try:
        if start:
            start_day = date.fromisoformat(start)
        if end:
            end_day = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="触发时间段格式非法，请使用 YYYY-MM-DD")
    if start_day and end_day and start_day > end_day:
        raise HTTPException(status_code=400, detail="触发时间段非法：开始时间不能晚于结束时间")
    return start_day, end_day


def _validate_status(status: str | None) -> str | None:
    if status and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"报警状态「{status}」不支持，可选：{'、'.join(STATUSES)}",
        )
    return status


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报警编号检索"),
    level: str | None = Query(default=None, description="按报警等级过滤，如 高 / 中 / 低；高=只看高等级"),
    status: str | None = Query(default=None, description="待确认、已确认、已处置、已忽略"),
    start: str | None = Query(default=None, description="触发时间起，YYYY-MM-DD"),
    end: str | None = Query(default=None, description="触发时间止，YYYY-MM-DD"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报警编号、等级、状态与触发时间段过滤；待确认与超时未处置置顶。

    没有数据时返回空页而不是报错，由前端给出无结果兜底提示。
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    _validate_range(start, end)
    _validate_status(status)
    items, total = service.list_entries(
        keyword=keyword,
        level=normalize_level(level),
        status=status,
        start=start,
        end=end,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def statistics(
    keyword: str | None = Query(default=None, description="按报警编号检索"),
    level: str | None = Query(default=None, description="按报警等级过滤"),
    status: str | None = Query(default=None, description="按报警状态过滤"),
    start: str | None = Query(default=None, description="触发时间起，YYYY-MM-DD"),
    end: str | None = Query(default=None, description="触发时间止，YYYY-MM-DD"),
) -> dict[str, Any]:
    """等级分布与处置时效统计；口径与列表接口完全一致。"""
    _validate_range(start, end)
    _validate_status(status)
    return {
        "slaHours": DISPOSE_SLA_HOURS,
        **service.statistics(
            keyword=keyword,
            level=normalize_level(level),
            status=status,
            start=start,
            end=end,
        ),
    }


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    level: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """导出报警中心清单：沿用当前过滤条件下的全量数据与置顶排序。"""
    _validate_range(start, end)
    _validate_status(status)
    items, total = service.list_entries(
        keyword=keyword,
        level=normalize_level(level),
        status=status,
        start=start,
        end=end,
        page=1,
        size=10000,
    )
    return {"module": "alarm", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条报警事件明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"报警事件 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条报警事件，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="报警事件已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条报警事件执行确认报警、处置报警、忽略报警；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

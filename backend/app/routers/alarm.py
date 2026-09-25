"""报警中心接口：维护报警事件，覆盖确认报警、处置报警、忽略报警等动作。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.alarm import AlarmService, resolve_time_range

router = APIRouter(prefix="/api/alarm", tags=["报警中心"])

service = AlarmService()

LIST_FIELDS = ["报警编号", "报警类型", "报警等级", "触发点位", "触发时间", "确认人员", "处置措施", "报警状态"]
STATUSES = ["待确认", "已确认", "已处置", "已忽略"]
LEVELS = ["高", "中", "低"]


def _resolve_range(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    """把触发时间段参数转成时间点；非法时段直接给出可读的 400 说明。"""
    try:
        return resolve_time_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报警编号检索"),
    level: str | None = Query(default=None, description="按报警等级过滤，如：高、中、低"),
    status: str | None = Query(default=None, description="待确认、已确认、已处置、已忽略"),
    start: str | None = Query(default=None, description="触发时间起点，如 2026-09-01 或 2026-09-01 08:00"),
    end: str | None = Query(default=None, description="触发时间终点，只到日时包含当天全天"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报警编号、报警等级与触发时间段定位报警；待确认与超时未处置的置顶，没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    start_at, end_at = _resolve_range(start, end)
    items, total = service.list_entries(
        keyword=keyword, level=level, status=status, start_at=start_at, end_at=end_at, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats_entries(
    keyword: str | None = Query(default=None, description="按报警编号检索"),
    level: str | None = Query(default=None, description="按报警等级过滤，如：高、中、低"),
    status: str | None = Query(default=None, description="待确认、已确认、已处置、已忽略"),
    start: str | None = Query(default=None, description="触发时间起点，如 2026-09-01 或 2026-09-01 08:00"),
    end: str | None = Query(default=None, description="触发时间终点，只到日时包含当天全天"),
) -> dict[str, Any]:
    """等级分布与处置时效统计：过滤口径与列表接口完全一致，数字随筛选条件联动。"""
    start_at, end_at = _resolve_range(start, end)
    return service.stats(keyword=keyword, level=level, status=status, start_at=start_at, end_at=end_at)


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按报警编号检索"),
    level: str | None = Query(default=None, description="按报警等级过滤，如：高、中、低"),
    status: str | None = Query(default=None, description="待确认、已确认、已处置、已忽略"),
    start: str | None = Query(default=None, description="触发时间起点，如 2026-09-01 或 2026-09-01 08:00"),
    end: str | None = Query(default=None, description="触发时间终点，只到日时包含当天全天"),
) -> dict[str, Any]:
    """导出报警中心清单：返回当前过滤条件下的全量数据。"""
    start_at, end_at = _resolve_range(start, end)
    items, total = service.list_entries(
        keyword=keyword, level=level, status=status, start_at=start_at, end_at=end_at, page=1, size=10000
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

"""报警中心业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "alarm"
REQUIRED_FIELDS = ["报警编号", "报警类型", "报警等级"]
STATUS_ORDER = ["待确认", "已确认", "已处置", "已忽略"]
ACTION_RULES = {"确认报警": "已确认", "处置报警": "已处置", "忽略报警": "已忽略"}
NEGATIVE_ACTIONS = ["忽略报警"]
LEVEL_ORDER = ["高", "中", "低"]
OVERDUE_HOURS = 24
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def parse_moment(raw: str) -> datetime | None:
    """把触发时间解析成时间点；兼容到日与到分两种写法，解析不了就返回 None。"""
    text = raw.strip().replace("T", " ").replace("/", "-")
    if not text:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def resolve_time_range(start_raw: str | None, end_raw: str | None) -> tuple[datetime | None, datetime | None]:
    """校验触发时间段：格式要可解析、起止不能颠倒；终点只到日时按当天结束算。"""
    start_at = parse_moment(start_raw) if start_raw else None
    if start_raw and start_at is None:
        raise ValueError(f"触发时间起点「{start_raw}」无法识别，请用 2026-09-01 或 2026-09-01 08:00 这样的格式")
    end_at = parse_moment(end_raw) if end_raw else None
    if end_raw and end_at is None:
        raise ValueError(f"触发时间终点「{end_raw}」无法识别，请用 2026-09-01 或 2026-09-01 08:00 这样的格式")
    if end_at is not None and len(end_raw.strip()) <= 10:
        end_at = end_at.replace(hour=23, minute=59, second=59)
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ValueError("触发时间段起止颠倒，请调整开始与结束时间")
    return start_at, end_at


class AlarmService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        level: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(keyword=keyword, status=status, level=level, start_at=start_at, end_at=end_at)
        rows = self._sort_rows(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        level: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> dict[str, Any]:
        """等级分布与处置时效：与列表接口共用同一套过滤口径，保证数字对得上。"""
        rows = self._filter_rows(keyword=keyword, status=status, level=level, start_at=start_at, end_at=end_at)
        now = datetime.now()
        levels: dict[str, int] = {}
        for row in rows:
            name = str(row.get("报警等级") or "未标注")
            levels[name] = levels.get(name, 0) + 1
        ordered = [name for name in LEVEL_ORDER if name in levels]
        ordered += sorted(name for name in levels if name not in LEVEL_ORDER)
        distribution = [{"level": name, "count": levels[name]} for name in ordered]
        handling = {name: 0 for name in STATUS_ORDER}
        for row in rows:
            name = str(row.get("status") or "")
            if name in handling:
                handling[name] += 1
        handling["超时未处置"] = sum(1 for row in rows if self._is_overdue(row, now))
        return {"total": len(rows), "level_distribution": distribution, "handling": handling}

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"报警事件 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于报警中心可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"报警事件已{action}"

    def _filter_rows(
        self,
        *,
        keyword: str | None,
        status: str | None,
        level: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报警编号", ""))]
        if level:
            rows = [row for row in rows if str(row.get("报警等级", "")) == level]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if start_at is not None or end_at is not None:
            rows = [row for row in rows if self._in_range(row, start_at, end_at)]
        return rows

    @staticmethod
    def _in_range(row: dict[str, Any], start_at: datetime | None, end_at: datetime | None) -> bool:
        moment = parse_moment(str(row.get("触发时间") or ""))
        if moment is None:
            return False
        if start_at is not None and moment < start_at:
            return False
        if end_at is not None and moment > end_at:
            return False
        return True

    @staticmethod
    def _is_overdue(row: dict[str, Any], now: datetime) -> bool:
        """超时未处置：还没走到已处置/已忽略，且触发时间已超过处置时限。"""
        if row.get("status") not in STATUS_ORDER[:2]:
            return False
        moment = parse_moment(str(row.get("触发时间") or ""))
        return moment is not None and now - moment > timedelta(hours=OVERDUE_HOURS)

    def _sort_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """待确认与超时未处置的置顶，组内按触发时间从早到晚，保证刷新后顺序稳定。"""
        now = datetime.now()

        def rank(row: dict[str, Any]) -> tuple[int, datetime, int]:
            pinned = row.get("status") == STATUS_ORDER[0] or self._is_overdue(row, now)
            moment = parse_moment(str(row.get("触发时间") or "")) or datetime.max
            return (0 if pinned else 1, moment, int(row.get("id", 0)))

        return sorted(rows, key=rank)

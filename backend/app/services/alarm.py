"""报警中心业务规则：状态流转、字段校验、筛选口径、置顶排序与统计都收在这里。

统计口径与列表保持一致：统计直接基于同一套过滤后的结果集计算，避免列表与看板
对不上。排序规则固定在服务端，因此前端刷新、翻页或重新查询后顺序都不会丢。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "alarm"
REQUIRED_FIELDS = ["报警编号", "报警类型", "报警等级"]
STATUS_ORDER = ["待确认", "已确认", "已处置", "已忽略"]
ACTION_RULES = {"确认报警": "已确认", "处置报警": "已处置", "忽略报警": "已忽略"}
NEGATIVE_ACTIONS = ["忽略报警"]

# 报警等级由高到低；未知等级排在最后，避免新增等级后直接报错。
LEVEL_ORDER = ["高", "中", "低"]
LEVEL_RANK = {level: index for index, level in enumerate(LEVEL_ORDER)}
# “只看高等级”允许的写法，兼容接口里可能出现的“高等级/一级”等口径。
HIGH_LEVEL_ALIASES = {"高", "高等级", "一级", "高级", "high", "HIGH"}
# 处置时效：触发后超过该时长仍未处置（含待确认、已确认），视为超时未处置。
DISPOSE_SLA_HOURS = 24
# 列表里用于展示的列，处置时效是依据触发时间/处置时间动态算出来的派生列。
DISPLAY_FIELDS = [
    "报警编号", "报警类型", "报警等级", "触发点位", "触发时间",
    "确认人员", "处置措施", "报警状态", "处置时效",
]


def _level_rank(level: Any) -> int:
    return LEVEL_RANK.get(str(level or "").strip(), len(LEVEL_ORDER))


def parse_trigger_time(value: Any) -> datetime | None:
    """把触发时间解析成可比较的时间；解析不了就返回 None，排序/统计时不抛异常。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed
        except ValueError:
            continue
    return None


def parse_dispose_time(value: Any) -> datetime | None:
    """处置时间与触发时间共用一套解析口径。"""
    return parse_trigger_time(value)


def normalize_level(level: str | None) -> str | None:
    """把“只看高等级”的不同写法归一化到「高」；其余等级按原值精确匹配。"""
    text = str(level or "").strip()
    if not text:
        return None
    if text in HIGH_LEVEL_ALIASES:
        return "高"
    return text


def _is_high(level: Any) -> bool:
    return str(level or "").strip() in HIGH_LEVEL_ALIASES


def _is_handled(status: Any) -> bool:
    """已处置、已忽略都算闭环，不再计入超时未处置；判定沿用既有状态集合。"""
    return status in ("已处置", "已忽略")


def _overtime_hours(trigger: datetime | None, now: datetime) -> float | None:
    if trigger is None:
        return None
    return round((now - trigger).total_seconds() / 3600.0, 1)


class AlarmService:
    # ---- 过滤 ----------------------------------------------------------------
    def _filtered_rows(
        self,
        *,
        keyword: str | None = None,
        level: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """按报警编号、报警等级、状态、触发时间段过滤；统计与列表共用此结果集。"""
        rows = list(store.rows(MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报警编号", ""))]
        normalized_level = normalize_level(level)
        if normalized_level:
            rows = [
                row for row in rows
                if str(row.get("报警等级", "")).strip() == normalized_level
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        start_day = date.fromisoformat(start) if start else None
        end_day = date.fromisoformat(end) if end else None
        if start_day or end_day:
            def within(row: dict[str, Any]) -> bool:
                trigger = parse_trigger_time(row.get("触发时间"))
                if trigger is None:
                    return False
                day = trigger.date()
                if start_day and day < start_day:
                    return False
                if end_day and day > end_day:
                    return False
                return True
            rows = [row for row in rows if within(row)]
        return rows

    # ---- 派生属性 ------------------------------------------------------------
    def _decorate(self, row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        """补出列表要展示的派生字段，不改动既有判定与原始字段。"""
        status = row.get("status")
        trigger = parse_trigger_time(row.get("触发时间"))
        overtime_hours = _overtime_hours(trigger, now)
        overtime = (
            not _is_handled(status)
            and overtime_hours is not None
            and overtime_hours > DISPOSE_SLA_HOURS
        )
        decorated = dict(row)
        decorated["报警状态"] = status
        decorated["待确认"] = status == "待确认"
        decorated["超时未处置"] = overtime
        decorated["处置时效"] = self._timeliness_text(
            status=status,
            trigger=trigger,
            dispose=parse_dispose_time(row.get("处置时间")),
            overtime_hours=overtime_hours,
        )
        return decorated

    def _timeliness_text(
        self,
        *,
        status: Any,
        trigger: datetime | None,
        dispose: datetime | None,
        overtime_hours: float | None,
    ) -> str:
        """处置时效列：已处置给耗时，未处置给剩余/超时说明，无法计算时给占位。"""
        if status == "已忽略":
            return "已忽略"
        if status == "已处置":
            if trigger and dispose and dispose >= trigger:
                hours = (dispose - trigger).total_seconds() / 3600.0
                return f"耗时 {hours:g} 小时"
            return "已处置"
        if trigger is None or overtime_hours is None:
            return "—"
        if overtime_hours > DISPOSE_SLA_HOURS:
            prefix = "已确认仍" if status == "已确认" else ""
            return f"{prefix}超时 {overtime_hours:g} 小时未处置"
        remaining = DISPOSE_SLA_HOURS - overtime_hours
        return f"剩余 {remaining:g} 小时"

    # ---- 排序 ----------------------------------------------------------------
    def _sort_key(self, row: dict[str, Any], *, now: datetime):
        """待确认、超时未处置置顶；同组内越早触发越靠前，最后按等级兜底。

        分桶：0=待确认（无论是否超时都最高优先）、1=已确认但超时未处置、
        2=其余（SLA 内的已确认 / 已处置 / 已忽略）。组内统一按触发时间升序，
        越早触发越紧急；再用报警等级（高>中>低）保证顺序稳定可复现。
        """
        status = row.get("status")
        trigger = parse_trigger_time(row.get("触发时间"))
        overtime_hours = _overtime_hours(trigger, now)
        is_overtime = (
            not _is_handled(status)
            and overtime_hours is not None
            and overtime_hours > DISPOSE_SLA_HOURS
        )
        if status == "待确认":
            bucket = 0
        elif status == "已确认" and is_overtime:
            bucket = 1
        else:
            bucket = 2
        order_ts = trigger.timestamp() if trigger else float("inf")
        return (bucket, order_ts, _level_rank(row.get("报警等级")))

    # ---- 对外查询 ------------------------------------------------------------
    def query_rows(
        self,
        *,
        keyword: str | None = None,
        level: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """过滤 + 置顶排序 + 派生字段，返回完整结果集（未分页）。"""
        moment = now or datetime.now()
        rows = self._filtered_rows(
            keyword=keyword, level=level, status=status, start=start, end=end
        )
        rows.sort(key=lambda row: self._sort_key(row, now=moment))
        return [self._decorate(row, now=moment) for row in rows]

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        level: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.query_rows(
            keyword=keyword, level=level, status=status, start=start, end=end
        )
        total = len(rows)
        begin = max(page - 1, 0) * size
        return rows[begin:begin + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---- 统计 ----------------------------------------------------------------
    def statistics(
        self,
        *,
        keyword: str | None = None,
        level: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """等级分布与处置时效统计，口径与列表完全一致（同一过滤结果集）。"""
        moment = datetime.now()
        rows = self.query_rows(
            keyword=keyword, level=level, status=status, start=start, end=end,
            now=moment,
        )
        total = len(rows)

        distribution = {name: 0 for name in LEVEL_ORDER}
        high_count = 0
        pending_count = 0
        overtime_count = 0
        handled_durations: list[float] = []

        for row in rows:
            level_text = str(row.get("报警等级", "")).strip()
            if level_text in distribution:
                distribution[level_text] += 1
            if _is_high(row.get("报警等级")):
                high_count += 1
            if row.get("status") == "待确认":
                pending_count += 1
            if row.get("超时未处置"):
                overtime_count += 1
            if row.get("status") == "已处置":
                trigger = parse_trigger_time(row.get("触发时间"))
                dispose = parse_dispose_time(row.get("处置时间"))
                if trigger and dispose and dispose >= trigger:
                    handled_durations.append(
                        (dispose - trigger).total_seconds() / 3600.0
                    )

        avg_hours = round(sum(handled_durations) / len(handled_durations), 1) \
            if handled_durations else None
        return {
            "total": total,
            "highLevel": high_count,
            "pending": pending_count,
            "overtime": overtime_count,
            "avgDisposeHours": avg_hours,
            "handledCount": len(handled_durations),
            "levelDistribution": [
                {"level": name, "count": distribution[name]} for name in LEVEL_ORDER
            ],
        }

    # ---- 写入（既有判定照旧） ------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 补全可选字段，缺什么就留空，避免列表派生字段取不到值。
        for field in ("触发点位", "触发时间", "确认人员", "处置措施"):
            entry[field] = values.get(field)
        entry["处置时间"] = values.get("处置时间")
        entry["status"] = STATUS_ORDER[0]
        entry["报警状态"] = STATUS_ORDER[0]
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
        entry["报警状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 处置动作闭环时记下处置时间，供处置时效统计；确认/忽略的既有判定不变。
        if action == "处置报警" and not entry.get("处置时间"):
            entry["处置时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return entry, f"报警事件已{action}"

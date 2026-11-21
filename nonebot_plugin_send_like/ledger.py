"""点赞账本与状态机。

状态语义：
- reserved  : 已预占，请求正在执行（同目标同日只会有一条记录）
- confirmed : 协议端确认成功（至少点出 1 个赞）
- unknown   : 结果不确定（超时、未知错误、首次调用即失败）——当日不再重试
- failed    : 明确未执行成功且未产生任何副作用，允许下次重试
- blocked   : 命中平台上限，当日封锁该目标

幂等规则：状态属于 BLOCKING_STATUSES 时，当日不再对该目标发起点赞。

实现说明：账本是 `state.json` 里的 `ledger[日期][QQ号]` 字典，
同一把 `asyncio.Lock` 保证"检查 + 写入"是原子的，不需要数据库唯一约束来兜并发。
"""

from __future__ import annotations

from datetime import date as Date
from typing import Any

from nonebot.log import logger

from .state import StateStore, now_text

STATUS_RESERVED = "reserved"
STATUS_CONFIRMED = "confirmed"
STATUS_UNKNOWN = "unknown"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"

BLOCKING_STATUSES = frozenset(
    {STATUS_RESERVED, STATUS_CONFIRMED, STATUS_UNKNOWN, STATUS_BLOCKED}
)
"""命中这些状态时，当日不再重复点赞"""

RETRYABLE_STATUSES = frozenset({STATUS_FAILED})
"""命中这些状态时，允许下一次重新尝试"""

GLOBAL_SCOPE = "global"
"""账号级封锁的作用域标识"""

NOTE_MAX_LENGTH = 200
"""备注最长长度，超出截断"""


def _shorten(note: str | None) -> str | None:
    """把备注裁剪到字段长度，空串转 None。"""
    if not note:
        return None
    return note.strip()[:NOTE_MAX_LENGTH] or None


def _day_key(day: Date) -> str:
    """日期转存储键。"""
    return day.isoformat()


async def get_record(
    store: StateStore, target_id: str, day: Date
) -> dict[str, Any] | None:
    """读取某目标某日的账本记录，不存在返回 None。"""
    data = await store.read()
    return data["ledger"].get(_day_key(day), {}).get(target_id)


async def is_settled(store: StateStore, target_id: str, day: Date) -> bool:
    """判断目标当日是否已处于"不应再点赞"的状态。"""
    record = await get_record(store, target_id, day)
    if record is None:
        return False
    return record.get("status") in BLOCKING_STATUSES


async def reserve(
    store: StateStore, target_id: str, day: Date, source: str
) -> tuple[dict[str, Any] | None, bool]:
    """预占某目标某日的点赞权。

    参数:
        store: 状态存储.
        target_id: 目标 QQ 号.
        day: 账本日期.
        source: 来源标识（manual / timed）.

    返回:
        tuple[dict | None, bool]:
            - 第二项为 True 表示本次成功预占，可以执行点赞；
            - 第二项为 False 表示当日已有记录（已点过 / 正在点 / 结果未知），调用方应跳过。
    """
    key = _day_key(day)

    def _reserve(data: dict) -> tuple[dict[str, Any] | None, bool]:
        ledger = data["ledger"].setdefault(key, {})
        record = ledger.get(target_id)
        if record is None:
            ledger[target_id] = {
                "status": STATUS_RESERVED,
                "times": 0,
                "source": source,
                "note": None,
                "updated_at": now_text(),
            }
            return dict(ledger[target_id]), True

        if record.get("status") in RETRYABLE_STATUSES:
            record.update(
                {
                    "status": STATUS_RESERVED,
                    "times": 0,
                    "source": source,
                    "note": None,
                    "updated_at": now_text(),
                }
            )
            return dict(record), True

        return dict(record), False

    record, acquired = await store.mutate(_reserve)
    if acquired:
        logger.debug(f"账本预占成功 | 目标: {target_id} | 来源: {source}")
    else:
        logger.debug(f"账本已存在记录，跳过 | 目标: {target_id}")
    return record, acquired


async def settle(
    store: StateStore,
    target_id: str,
    day: Date,
    status: str,
    times: int = 0,
    note: str | None = None,
) -> None:
    """落定账本状态。

    参数:
        store: 状态存储.
        target_id: 目标 QQ 号.
        day: 账本日期.
        status: 目标状态，取 STATUS_* 之一.
        times: 实际点出的赞数.
        note: 备注或错误摘要，超长自动截断.
    """
    key = _day_key(day)

    def _settle(data: dict) -> bool:
        record = data["ledger"].get(key, {}).get(target_id)
        if record is None:
            return False
        record.update(
            {
                "status": status,
                "times": int(times),
                "note": _shorten(note),
                "updated_at": now_text(),
            }
        )
        return True

    if not await store.mutate(_settle):
        logger.warning(f"账本记录为空，无法落定状态: {status} | 目标: {target_id}")


async def block(store: StateStore, day: Date, scope: str, reason: str | None = None) -> None:
    """写入当日封锁标记（幂等，重复写入保留首次原因）。"""
    key = _day_key(day)

    def _block(data: dict) -> None:
        blocks = data["blocks"].setdefault(key, {})
        if scope not in blocks:
            blocks[scope] = {"reason": _shorten(reason), "created_at": now_text()}

    await store.mutate(_block)
    logger.warning(f"已写入当日封锁 | 范围: {scope} | 原因: {reason}")


async def is_blocked(store: StateStore, day: Date, scope: str) -> bool:
    """判断某作用域当日是否已被封锁。"""
    data = await store.read()
    return scope in data["blocks"].get(_day_key(day), {})


async def is_globally_blocked(store: StateStore, day: Date) -> bool:
    """判断当日是否已被账号级封锁。"""
    return await is_blocked(store, day, GLOBAL_SCOPE)


async def list_blocks(store: StateStore, day: Date) -> list[tuple[str, dict]]:
    """列出某日全部封锁记录。"""
    data = await store.read()
    return list(data["blocks"].get(_day_key(day), {}).items())


async def count_ledger(
    store: StateStore, day: Date, statuses: frozenset[str] | None = None
) -> int:
    """统计某日账本条数，可按状态过滤。"""
    data = await store.read()
    entries = data["ledger"].get(_day_key(day), {})
    if statuses:
        return sum(1 for record in entries.values() if record.get("status") in statuses)
    return len(entries)

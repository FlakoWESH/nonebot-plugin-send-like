"""白名单数据访问层。

职责边界：
- 只负责 QQ 号校验、白名单的增删查与启用状态读写；
- 不涉及点赞、额度、账本与任何协议端调用；
- 不做消息拼装，调用方（命令层 / 定时任务）自行组织提示文案。

边界行为约定：
- 非法 QQ 号 -> 抛 ValueError，由调用方捕获并提示；
- 重复添加 -> 返回 AddOutcome.EXISTS，不抛异常、不覆盖原记录；
- 名单为空 -> 查询返回空列表 / False，不抛异常；
- 已停用（enabled=False）的目标不计入可点赞集合。
"""

from __future__ import annotations

from enum import Enum

from nonebot.log import logger

from .state import StateStore, now_text

QQ_MIN_LENGTH = 5
"""QQ 号最短长度"""
QQ_MAX_LENGTH = 12
"""QQ 号最长长度"""
REMARK_MAX_LENGTH = 50
"""备注最长长度"""


class AddOutcome(str, Enum):
    """添加白名单的结果枚举"""

    ADDED = "added"
    """新增成功"""
    EXISTS = "exists"
    """目标已存在"""


def normalize_target(raw: str | int) -> str:
    """校验并规范化为字符串形式的 QQ 号。

    参数:
        raw: 待校验的 QQ 号，允许 int 或 str.

    返回:
        str: 规范化后的 QQ 号（去首尾空白）.

    异常:
        ValueError: 非纯数字、长度不在 5-12 位、或以 0 开头时抛出.
    """
    text = str(raw).strip()
    if not text:
        raise ValueError("QQ 号不能为空")
    if not text.isdigit():
        raise ValueError("QQ 号必须是纯数字")
    if not (QQ_MIN_LENGTH <= len(text) <= QQ_MAX_LENGTH):
        raise ValueError(f"QQ 号长度需在 {QQ_MIN_LENGTH}-{QQ_MAX_LENGTH} 位之间")
    if text.startswith("0"):
        raise ValueError("QQ 号不能以 0 开头")
    return text


def normalize_remark(remark: str | None) -> str | None:
    """规范化备注，超长截断为 REMARK_MAX_LENGTH，空串转为 None。"""
    if remark is None:
        return None
    text = remark.strip()
    if not text:
        return None
    return text[:REMARK_MAX_LENGTH]


async def add_target(
    store: StateStore,
    target_id: str | int,
    remark: str | None = None,
    created_by: str | int | None = None,
) -> AddOutcome:
    """添加白名单目标（幂等，重复添加不覆盖原记录）。

    参数:
        store: 状态存储.
        target_id: 目标 QQ 号.
        remark: 备注，可选.
        created_by: 添加者 QQ 号，可选.

    返回:
        AddOutcome: ADDED 表示新增成功，EXISTS 表示目标已存在.

    异常:
        ValueError: QQ 号或添加者 QQ 号不合法时抛出.
    """
    qq = normalize_target(target_id)
    creator = normalize_target(created_by) if created_by is not None else None

    def _add(data: dict) -> AddOutcome:
        whitelist = data["whitelist"]
        if qq in whitelist:
            return AddOutcome.EXISTS
        whitelist[qq] = {
            "remark": normalize_remark(remark),
            "enabled": True,
            "created_by": creator,
            "created_at": now_text(),
        }
        return AddOutcome.ADDED

    outcome = await store.mutate(_add)
    if outcome is AddOutcome.ADDED:
        logger.info(f"白名单新增目标: {qq}")
    else:
        logger.debug(f"白名单目标已存在: {qq}")
    return outcome


async def remove_target(store: StateStore, target_id: str | int) -> bool:
    """移除白名单目标。

    参数:
        store: 状态存储.
        target_id: 目标 QQ 号.

    返回:
        bool: 是否确实删除了记录（不存在时返回 False）.

    异常:
        ValueError: QQ 号不合法时抛出.
    """
    qq = normalize_target(target_id)
    removed = await store.mutate(lambda data: data["whitelist"].pop(qq, None) is not None)
    if removed:
        logger.info(f"白名单移除目标: {qq}")
    return removed


async def set_enabled(store: StateStore, target_id: str | int, enabled: bool) -> bool:
    """启用或停用白名单目标。

    参数:
        store: 状态存储.
        target_id: 目标 QQ 号.
        enabled: True 启用，False 停用.

    返回:
        bool: 目标是否存在（不存在时返回 False，不做任何写入）.

    异常:
        ValueError: QQ 号不合法时抛出.
    """
    qq = normalize_target(target_id)

    def _set(data: dict) -> bool:
        entry = data["whitelist"].get(qq)
        if entry is None:
            return False
        entry["enabled"] = bool(enabled)
        return True

    return await store.mutate(_set)


async def is_allowed(store: StateStore, target_id: str | int) -> bool:
    """判断目标是否在白名单中且处于启用状态。"""
    qq = normalize_target(target_id)
    data = await store.read()
    entry = data["whitelist"].get(qq)
    return bool(entry and entry.get("enabled", True))


async def get_enabled_ids(store: StateStore) -> list[str]:
    """获取所有启用状态的白名单 QQ 号（按添加顺序）。"""
    data = await store.read()
    return [
        qq for qq, entry in data["whitelist"].items() if entry.get("enabled", True)
    ]


async def list_targets(
    store: StateStore, enabled_only: bool = False
) -> list[tuple[str, dict]]:
    """列出白名单记录。

    参数:
        store: 状态存储.
        enabled_only: 为 True 时只返回启用状态的目标.

    返回:
        list[tuple[str, dict]]: (QQ 号, 记录) 列表，空名单返回空列表.
    """
    data = await store.read()
    result = []
    for qq, entry in data["whitelist"].items():
        if enabled_only and not entry.get("enabled", True):
            continue
        result.append((qq, entry))
    return result


async def count_targets(store: StateStore, enabled_only: bool = True) -> int:
    """统计白名单数量（默认只统计启用状态）。"""
    data = await store.read()
    if enabled_only:
        return sum(1 for entry in data["whitelist"].values() if entry.get("enabled", True))
    return len(data["whitelist"])

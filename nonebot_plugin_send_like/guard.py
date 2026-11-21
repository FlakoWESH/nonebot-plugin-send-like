"""风控保护层。

包含三块互相独立的能力：
1. 平台上限识别：扫描协议端返回的提示字段，判断是否命中上限；
2. 节奏控制（Pacer）：限制单位时间内发起的点赞目标数，避免对频；
3. 并发闸门（ConcurrencyGuard）：限制批量点赞的并发执行数。

说明：Pacer 与 ConcurrencyGuard 都是进程内状态，重启后清零；
需要跨重启保留的"当日封锁"由 ledger 落盘承担。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

PLATFORM_LIMIT_FIELDS = (
    "error",
    "wording",
    "message",
    "msg",
    "retmsg",
    "errmsg",
    "detail",
)
"""协议端可能承载限流提示的字段名"""

PLATFORM_LIMIT_KEYWORDS = (
    "上限",
    "频繁",
    "超过",
    "已达",
    "次数已",
    "冷却",
    "太快",
    "稍后再试",
    "限制",
    "too many",
    "too fast",
    "rate limit",
    "exceed",
    "quota",
    "frequent",
    "limit reached",
)
"""命中即判定为平台上限/限流的关键词"""

REASON_MAX_LENGTH = 200
"""原因摘要最长长度"""


def _stringify(value: object) -> str:
    """把任意字段值安全地转成字符串。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def collect_messages(exc: BaseException) -> str:
    """从异常对象中收集协议端返回的提示文本。

    优先读取 OneBot v11 `ActionFailed.info`（适配器把响应字典完整挂在该属性上），
    其次读取异常自身的字符串，保证非 ActionFailed 异常也能拿到描述。

    参数:
        exc: 协议端抛出的异常.

    返回:
        str: 用 " | " 拼接的提示文本，可能为空串.
    """
    parts: list[str] = []
    info: Any = getattr(exc, "info", None)
    if isinstance(info, dict):
        for field in PLATFORM_LIMIT_FIELDS:
            text = _stringify(info.get(field)).strip()
            if text and text not in parts:
                parts.append(text)
    text = str(exc).strip()
    if text and text not in parts:
        parts.append(text)
    return " | ".join(parts)


def is_platform_limit(exc: BaseException) -> bool:
    """判断异常是否为平台上限/限流导致。"""
    text = collect_messages(exc).lower()
    if not text:
        return False
    return any(keyword in text for keyword in PLATFORM_LIMIT_KEYWORDS)


def describe_exception(exc: BaseException) -> str:
    """生成用于账本记录的错误摘要，超长自动截断。"""
    text = collect_messages(exc) or exc.__class__.__name__
    return text[:REASON_MAX_LENGTH]


class Pacer:
    """节奏控制：限制单位时间内发起的点赞目标数（滑动窗口）。"""

    def __init__(self, max_calls: int, time_window: float):
        if max_calls <= 0 or time_window <= 0:
            raise ValueError("Pacer 的 max_calls 与 time_window 必须为正数")
        self.max_calls = max_calls
        self.time_window = float(time_window)
        self._events: dict[object, list[float]] = {}
        self._lock = asyncio.Lock()

    async def wait(
        self,
        key: object = "global",
        max_wait: float = 120.0,
        slice_seconds: float = 0.5,
    ) -> bool:
        """等待到可放行的时机。

        参数:
            key: 限流分组的键，默认全局共用一组.
            max_wait: 最长等待秒数，超时返回 False.
            slice_seconds: 轮询睡眠切片，避免忙等.

        返回:
            bool: 是否在 max_wait 内取得放行资格.
        """
        loop = asyncio.get_running_loop()
        waited = 0.0

        while True:
            async with self._lock:
                now = loop.time()
                events = self._events.setdefault(key, [])
                while events and now - events[0] >= self.time_window:
                    events.pop(0)
                if len(events) < self.max_calls:
                    events.append(now)
                    return True
                left = self.time_window - (now - events[0])

            if waited >= max_wait:
                return False
            sleep_for = max(0.05, min(slice_seconds, left, max_wait - waited))
            await asyncio.sleep(sleep_for)
            waited += sleep_for

    def left_time(self, key: object = "global") -> float:
        """距离下次可放行还需等待的秒数（粗估，0 表示可直接放行）。"""
        events = self._events.get(key, [])
        if len(events) < self.max_calls:
            return 0.0
        loop = asyncio.get_running_loop()
        return max(0.0, self.time_window - (loop.time() - events[0]))


class ConcurrencyGuard:
    """并发闸门：限制同时执行的点赞数量，需配合 async with 使用。"""

    def __init__(self, max_concurrent: int):
        if max_concurrent <= 0:
            raise ValueError("ConcurrencyGuard 的 max_concurrent 必须为正数")
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @asynccontextmanager
    async def slot(self, key: object = "global") -> AsyncIterator[None]:
        """占用一个并发槽位，退出时自动释放。"""
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()

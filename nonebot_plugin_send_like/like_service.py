"""点赞核心服务。

职责：把一个目标"点满赞"的完整流程收敛到一处，供手动点赞命令和定时任务共用。

流程：
1. 当日账号级/目标级封锁检查（命中直接 BLOCKED）
2. 历史记录幂等检查（当日已手动点赞或已回赞则 SKIPPED）
3. 账本预占（同目标同日只有一次执行机会）
4. 节奏控制（Pacer 放行）
5. 分轮调用 send_like，每轮 10 个
6. 失败分类：
   - 命中平台上限 -> 目标当日封锁，返回 BLOCKED
   - 非上限失败且已点出过赞 -> confirmed 部分成功
   - 非上限失败且一个都没点出 -> unknown，当日不再重试
7. 落定账本，并回写点赞记录（供每日人数额度与自动回赞复用）

不做的事：白名单校验、每日 499 人数额度、消息拼装——均由调用方负责。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date as Date
from enum import Enum

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from . import ledger
from .guard import Pacer, describe_exception, is_platform_limit
from .state import StateStore
from .storage import LikeRecordStore
from .whitelist import normalize_target

CHUNK_TIMES = 10
"""单次 send_like 调用的点赞数（协议端上限）"""

DEFAULT_MAX_TIMES = 50
"""默认点满赞数"""

DEFAULT_ROUND_INTERVAL = 1.0
"""轮与轮之间的间隔秒数"""


class LikeStatus(str, Enum):
    """单目标点赞结果"""

    LIKED = "liked"
    """点满成功"""
    PARTIAL = "partial"
    """部分成功（中途遇到失败）"""
    SKIPPED = "skipped"
    """当日已处理过，跳过"""
    BLOCKED = "blocked"
    """命中平台上限，当日封锁"""
    UNKNOWN = "unknown"
    """结果不确定，当日不重试"""
    FAILED = "failed"
    """明确失败，可重试"""


@dataclass(slots=True)
class LikeOutcome:
    """单目标点赞结果载体"""

    target_id: str
    status: LikeStatus
    times: int = 0
    reason: str = ""

    @property
    def ok(self) -> bool:
        """是否确实点出了赞。"""
        return self.status in (LikeStatus.LIKED, LikeStatus.PARTIAL)

    @property
    def should_abort_batch(self) -> bool:
        """是否应当中止当前批量任务。"""
        return self.status in (LikeStatus.BLOCKED, LikeStatus.UNKNOWN)


class LikeService:
    """单目标点赞核心服务。"""

    def __init__(
        self,
        bot: Bot,
        state: StateStore,
        records: LikeRecordStore,
        *,
        max_times: int = DEFAULT_MAX_TIMES,
        chunk_times: int = CHUNK_TIMES,
        round_interval: float = DEFAULT_ROUND_INTERVAL,
        pacer: Pacer | None = None,
    ):
        """初始化服务。

        参数:
            bot: OneBot v11 Bot 实例.
            state: 白名单/账本/封锁存储.
            records: 点赞记录存储.
            max_times: 单目标单日最多点出的赞数.
            chunk_times: 单次调用的点赞数，默认 10.
            round_interval: 轮间间隔秒数.
            pacer: 节奏控制器，None 表示不做节奏控制.
        """
        self._bot = bot
        self._state = state
        self._records = records
        self.max_times = max(CHUNK_TIMES, int(max_times))
        self.chunk_times = max(1, min(CHUNK_TIMES, int(chunk_times)))
        self.round_interval = max(0.0, float(round_interval))
        self.pacer = pacer

    @property
    def rounds(self) -> int:
        """点满所需的轮数。"""
        return max(1, self.max_times // self.chunk_times)

    async def run(
        self,
        target_id: str | int,
        source: str = "manual",
        max_times: int | None = None,
        day: Date | None = None,
    ) -> LikeOutcome:
        """对单个目标执行点赞。

        参数:
            target_id: 目标 QQ 号.
            source: 来源标识（manual / timed）.
            max_times: 本次最多点出的赞数，None 表示使用实例默认值.
            day: 账本日期，None 表示今天.

        返回:
            LikeOutcome: 结果.

        异常:
            ValueError: 目标 QQ 号不合法.
        """
        qq = normalize_target(target_id)
        today = day or Date.today()
        want = self.max_times if max_times is None else max(CHUNK_TIMES, int(max_times))

        # 1. 封锁检查
        if await ledger.is_globally_blocked(self._state, today):
            logger.debug(f"当日账号级封锁，跳过 | 目标: {qq}")
            return LikeOutcome(qq, LikeStatus.BLOCKED, 0, "账号当日已封锁")
        if await ledger.is_blocked(self._state, today, qq):
            logger.debug(f"当日目标级封锁，跳过 | 目标: {qq}")
            return LikeOutcome(qq, LikeStatus.BLOCKED, 0, "目标当日已封锁")

        # 2. 历史记录幂等
        if await self._already_liked_today(qq, today):
            logger.debug(f"当日已点过赞，跳过 | 目标: {qq}")
            return LikeOutcome(qq, LikeStatus.SKIPPED, 0, "当日已点过赞")

        # 3. 账本预占
        record, acquired = await ledger.reserve(self._state, qq, today, source)
        if not acquired:
            if record is not None and record.get("status") == ledger.STATUS_BLOCKED:
                return LikeOutcome(qq, LikeStatus.BLOCKED, record.get("times", 0), "目标当日已封锁")
            return LikeOutcome(qq, LikeStatus.SKIPPED, 0, "当日已处理或正在处理")

        # 4. 节奏控制
        if self.pacer is not None and not await self.pacer.wait():
            await ledger.settle(self._state, qq, today, ledger.STATUS_FAILED, 0, "节奏控制等待超时")
            return LikeOutcome(qq, LikeStatus.FAILED, 0, "节奏控制等待超时")

        # 5. 分轮点赞
        return await self._do_rounds(qq, want, today)

    async def _do_rounds(self, qq: str, want: int, today: Date) -> LikeOutcome:
        """执行分轮点赞并落定账本。"""
        liked = 0
        rounds = max(1, want // self.chunk_times)

        for index in range(rounds):
            try:
                await self._bot.send_like(user_id=int(qq), times=self.chunk_times)
                liked += self.chunk_times
            except Exception as exc:  # noqa: BLE001 - 需按异常类型分流
                return await self._handle_failure(qq, liked, exc, today)

            if index < rounds - 1 and self.round_interval > 0:
                await asyncio.sleep(self.round_interval)

        await ledger.settle(self._state, qq, today, ledger.STATUS_CONFIRMED, liked)
        await self._mirror_record(qq, today)
        logger.info(f"点赞成功 | 目标: {qq} | 次数: {liked}")
        return LikeOutcome(qq, LikeStatus.LIKED, liked)

    async def _handle_failure(
        self, qq: str, liked: int, exc: BaseException, today: Date
    ) -> LikeOutcome:
        """处理点赞过程中的异常，按类型落定账本并返回结果。"""
        reason = describe_exception(exc)
        logger.warning(f"点赞失败 | 目标: {qq} | 已点出: {liked} | 原因: {reason}")

        if is_platform_limit(exc):
            await ledger.block(self._state, today, qq, reason)
            await ledger.settle(self._state, qq, today, ledger.STATUS_BLOCKED, liked, reason)
            return LikeOutcome(qq, LikeStatus.BLOCKED, liked, reason)

        if liked > 0:
            # 中途失败但已点出部分赞，按部分成功处理，不再重试
            await ledger.settle(self._state, qq, today, ledger.STATUS_CONFIRMED, liked, reason)
            await self._mirror_record(qq, today)
            return LikeOutcome(qq, LikeStatus.PARTIAL, liked, reason)

        # 一个都没点出：结果不确定（可能今日已点过，也可能是未知错误），当日不再重试
        await ledger.settle(self._state, qq, today, ledger.STATUS_UNKNOWN, 0, reason)
        return LikeOutcome(qq, LikeStatus.UNKNOWN, 0, reason)

    async def _already_liked_today(self, qq: str, today: Date) -> bool:
        """检查点赞记录里当日是否已对该目标点过赞或已回赞。"""
        record = await self._records.get_record(qq, today)
        if not record:
            return False
        return bool(record.get("manual_liked") or record.get("is_returned"))

    async def _mirror_record(self, qq: str, today: Date) -> None:
        """把成功结果回写点赞记录，供每日人数额度与自动回赞复用。"""
        try:
            await self._records.mark_manual_liked(qq, today)
        except Exception as e:  # noqa: BLE001 - 回写失败不应影响点赞结果
            logger.error(f"回写点赞记录失败 | 目标: {qq} | 原因: {e!r}")

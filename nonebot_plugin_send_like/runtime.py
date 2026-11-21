"""运行时装配。

把「读配置 → 建服务 / 建限流器」这类胶水逻辑收在一处，
命令层与定时层都从这里拿实例，避免各自散落一份配置读取。
"""

from __future__ import annotations

from datetime import date

from nonebot import get_plugin_config

from .config import SendLikeConfig
from .guard import ConcurrencyGuard, Pacer
from .like_service import DEFAULT_MAX_TIMES, LikeService
from .state import StateStore
from .storage import LikeRecordStore

config = get_plugin_config(SendLikeConfig)
"""插件配置（nonebot 在加载期解析）"""

state = StateStore(config.send_like_state_file)
"""白名单 / 账本 / 封锁 / 定时配置存储"""

records = LikeRecordStore(config.send_like_data_file)
"""点赞记录存储"""

_pacer: Pacer | None = None
_concurrency: ConcurrencyGuard | None = None


def get_pacer() -> Pacer:
    """获取进程内共享的节奏控制器（配置变更时自动重建）。"""
    global _pacer
    max_calls = max(1, int(config.send_like_pacer_max_calls))
    window = max(1, int(config.send_like_pacer_time_window))
    if _pacer is None or _pacer.max_calls != max_calls or _pacer.time_window != window:
        _pacer = Pacer(max_calls, window)
    return _pacer


def get_concurrency() -> ConcurrencyGuard:
    """获取进程内共享的并发闸门（配置变更时自动重建）。"""
    global _concurrency
    limit = max(1, int(config.send_like_max_concurrent))
    if _concurrency is None or _concurrency.max_concurrent != limit:
        _concurrency = ConcurrencyGuard(limit)
    return _concurrency


def build_service(bot, max_times: int | None = None) -> LikeService:
    """按当前配置装配一个点赞服务实例。

    参数:
        bot: OneBot v11 Bot 实例.
        max_times: 覆盖单目标点满数，None 表示使用配置项 send_like_like_times.
    """
    times = int(
        max_times
        if max_times is not None
        else config.send_like_like_times or DEFAULT_MAX_TIMES
    )
    return LikeService(
        bot,
        state,
        records,
        max_times=times,
        round_interval=float(config.send_like_like_round_interval),
        pacer=get_pacer(),
    )


def require_whitelist() -> bool:
    """是否要求手动点赞目标必须来自白名单。"""
    return bool(config.send_like_require_whitelist)


def daily_limit() -> int:
    """每日点赞人数上限。"""
    return int(config.send_like_daily_like_limit)


async def used_today(day: date | None = None) -> int:
    """今日已点赞过的人数（手动点赞 + 自动回赞都占额度）。"""
    return await records.count_liked(day or date.today())


async def remaining_today(day: date | None = None) -> int:
    """今日剩余可点赞人数。"""
    return max(0, daily_limit() - await used_today(day))

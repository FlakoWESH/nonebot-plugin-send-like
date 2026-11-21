"""定时点赞任务与排程管理。

设计约束：
- 插件加载时**不自动创建排程**，必须由管理员显式执行「定时点赞开启」，
  避免账号刚被风控时被自动任务打到。
- 排程用 nonebot-plugin-apscheduler 的 AsyncIOScheduler 承载（cron 触发）；
  调度器是内存态，重启会丢，因此开启参数落在 state.json，启动时按记录恢复。
- 批处理顺序：白名单 → 每日额度 → 逐目标走 LikeService（内含账本、节奏、上限识别）。
- 连续多个目标命中 BLOCKED/UNKNOWN 时中止本批次，避免在账号级限流下继续硬打。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import nonebot
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger
from nonebot.plugin import require

from . import ledger, runtime, whitelist
from .like_service import LikeOutcome, LikeStatus

try:  # 依赖异常时插件仍可加载，定时命令给出提示
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler as APS_SCHEDULER

    SCHEDULER_AVAILABLE = True
except Exception as e:  # noqa: BLE001
    APS_SCHEDULER = None  # type: ignore[assignment]
    SCHEDULER_AVAILABLE = False
    logger.warning(f"nonebot-plugin-apscheduler 不可用，定时功能已禁用: {e!r}")

JOB_ID = "send_like_timed"
"""定时任务的调度器 ID"""

ABORT_AFTER_FAILURES = 3
"""连续多少个目标命中 BLOCKED/UNKNOWN 就中止本批次"""


def _pick_bot() -> Bot | None:
    """从已连接的 bot 里挑一个用于定时任务。"""
    try:
        bots = nonebot.get_bots()
    except Exception:  # noqa: BLE001 - 早期调用可能取不到
        return None
    for bot in bots.values():
        return bot
    return None


async def run_timed_batch(
    bot: Bot,
    *,
    limit: int = 0,
    times: int = 0,
    day: date | None = None,
) -> dict[str, int]:
    """执行一轮按白名单的批量点赞，返回统计结果。

    从调度入口中拆出来，便于脱离调度器做验证。

    参数:
        bot: OneBot v11 Bot 实例.
        limit: 本次最多处理的目标数，0 表示白名单全部.
        times: 单目标点满数，0 表示使用配置.
        day: 账本日期，None 表示今天.

    返回:
        dict[str, int]: 各状态计数与总量统计.
    """
    today = day or date.today()
    stats: dict[str, int] = {
        "total": 0,
        "liked": 0,
        "partial": 0,
        "skipped": 0,
        "blocked": 0,
        "unknown": 0,
        "failed": 0,
        "aborted": 0,
    }

    if await ledger.is_globally_blocked(runtime.state, today):
        logger.info("定时点赞跳过：账号当日已被封锁")
        return stats

    targets = await whitelist.get_enabled_ids(runtime.state)
    if not targets:
        logger.info("定时点赞跳过：白名单为空或全部停用")
        return stats

    if limit and limit > 0:
        targets = targets[:limit]

    remaining = await runtime.remaining_today(today)
    if remaining <= 0:
        logger.info("定时点赞跳过：今日点赞人数额度已用尽")
        return stats

    service = runtime.build_service(bot, max_times=times if times > 0 else None)
    concurrency = runtime.get_concurrency()
    batch_size = max(1, concurrency.max_concurrent)

    quota_lock = asyncio.Lock()
    quota_left = remaining

    async def _run_one(qq: str) -> LikeOutcome | None:
        """占用一个额度名额后执行单目标点赞，失败时归还名额。"""
        nonlocal quota_left
        async with quota_lock:
            if quota_left <= 0:
                return None
            quota_left -= 1
        async with concurrency.slot():
            outcome = await service.run(qq, source="timed", day=today)
        if not outcome.ok:
            async with quota_lock:
                quota_left += 1
        return outcome

    consecutive = 0
    for start in range(0, len(targets), batch_size):
        chunk = targets[start : start + batch_size]
        results = await asyncio.gather(
            *(_run_one(qq) for qq in chunk), return_exceptions=True
        )

        for qq, result in zip(chunk, results):
            stats["total"] += 1
            if isinstance(result, BaseException):
                stats["failed"] += 1
                logger.error(f"定时点赞异常 | 目标: {qq} | 原因: {result!r}")
                continue
            if result is None:
                stats["skipped"] += 1
                continue

            if result.status is LikeStatus.LIKED:
                stats["liked"] += 1
            elif result.status is LikeStatus.PARTIAL:
                stats["partial"] += 1
            elif result.status is LikeStatus.SKIPPED:
                stats["skipped"] += 1
            elif result.status is LikeStatus.BLOCKED:
                stats["blocked"] += 1
            elif result.status is LikeStatus.UNKNOWN:
                stats["unknown"] += 1
            else:
                stats["failed"] += 1

            consecutive = consecutive + 1 if result.should_abort_batch else 0

        # 中止判断放在整批结果统计之后：同一批次内已发出的请求都要计入统计，
        # 否则会出现"实际点成功但没计数"的情况；同时让成功结果正确重置连续计数。
        if consecutive >= ABORT_AFTER_FAILURES:
            stats["aborted"] = 1
            logger.warning(
                f"连续 {consecutive} 个目标命中封锁/未知，"
                f"中止本批次（已处理 {stats['total']} 个）"
            )
            break

        if quota_left <= 0:
            break

    logger.info(
        "定时点赞完成 | 总数: {total} | 点满: {liked} | 部分: {partial} | "
        "跳过: {skipped} | 封锁: {blocked} | 未知: {unknown} | 失败: {failed}".format(
            **stats
        )
    )
    return stats


def _next_run_text(hour: int, minute: int) -> str:
    """计算下一次触发的本地时间文本（仅用于展示）。"""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%d %H:%M")


async def _job_entry() -> None:
    """调度器入口：读取已保存的参数并执行一轮批量点赞。"""
    data = await runtime.state.read()
    schedule = data.get("schedule", {})
    bot = _pick_bot()
    if bot is None:
        logger.warning("定时点赞跳过：当前没有已连接的 bot")
        return
    logger.info(f"定时点赞任务开始 | 模式: 每日 {schedule.get('hour')}:{schedule.get('minute')}")
    await run_timed_batch(
        bot,
        limit=int(schedule.get("limit", 0)),
        times=int(schedule.get("times", 0)),
    )


def _validate_time(hour: int, minute: int) -> None:
    """校验时分范围。"""
    if not (0 <= hour <= 23):
        raise ValueError("小时需在 0-23 之间")
    if not (0 <= minute <= 59):
        raise ValueError("分钟需在 0-59 之间")


async def enable_schedule(hour: int, minute: int, limit: int = 0, times: int = 0) -> None:
    """开启每日定时点赞。

    参数:
        hour: 触发小时（0-23）.
        minute: 触发分钟（0-59）.
        limit: 每轮最多处理的目标数，0 表示白名单全部.
        times: 单目标点满数，0 表示使用配置.

    异常:
        RuntimeError: 未安装 nonebot-plugin-apscheduler.
        ValueError: 时分越界.
    """
    if not SCHEDULER_AVAILABLE:
        raise RuntimeError("未安装 nonebot-plugin-apscheduler，无法使用定时功能")
    _validate_time(hour, minute)

    assert APS_SCHEDULER is not None
    if APS_SCHEDULER.get_job(JOB_ID):
        APS_SCHEDULER.remove_job(JOB_ID)
    APS_SCHEDULER.add_job(
        _job_entry,
        "cron",
        hour=hour,
        minute=minute,
        id=JOB_ID,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )

    def _save(data: dict) -> None:
        data["schedule"] = {
            "enabled": True,
            "hour": int(hour),
            "minute": int(minute),
            "limit": max(0, int(limit)),
            "times": max(0, int(times)),
        }

    await runtime.state.mutate(_save)
    logger.info(f"定时点赞已开启 | 每日 {hour:02d}:{minute:02d}")


async def disable_schedule() -> bool:
    """关闭每日定时点赞。

    返回:
        bool: 之前是否处于开启状态.
    """
    data = await runtime.state.read()
    was_enabled = bool(data.get("schedule", {}).get("enabled"))

    if SCHEDULER_AVAILABLE:
        assert APS_SCHEDULER is not None
        if APS_SCHEDULER.get_job(JOB_ID):
            APS_SCHEDULER.remove_job(JOB_ID)

    def _save(data: dict) -> None:
        data.setdefault("schedule", {})["enabled"] = False

    await runtime.state.mutate(_save)
    logger.info("定时点赞已关闭")
    return was_enabled


async def schedule_status() -> dict[str, Any]:
    """读取定时任务状态。"""
    data = await runtime.state.read()
    schedule = data.get("schedule", {})
    enabled = bool(schedule.get("enabled"))
    job_alive = False
    if SCHEDULER_AVAILABLE:
        assert APS_SCHEDULER is not None
        job_alive = APS_SCHEDULER.get_job(JOB_ID) is not None
    return {
        "available": SCHEDULER_AVAILABLE,
        "enabled": enabled,
        "job_alive": job_alive,
        "hour": int(schedule.get("hour", 9)),
        "minute": int(schedule.get("minute", 0)),
        "limit": int(schedule.get("limit", 0)),
        "times": int(schedule.get("times", 0)),
        "next_run": _next_run_text(
            int(schedule.get("hour", 9)), int(schedule.get("minute", 0))
        )
        if enabled
        else None,
    }


async def restore_schedule() -> None:
    """启动时按 state.json 里的记录恢复排程。"""
    if not SCHEDULER_AVAILABLE:
        return
    try:
        data = await runtime.state.read()
        schedule = data.get("schedule", {})
        if not schedule.get("enabled"):
            return
        await enable_schedule(
            int(schedule.get("hour", 9)),
            int(schedule.get("minute", 0)),
            int(schedule.get("limit", 0)),
            int(schedule.get("times", 0)),
        )
        logger.info("已按上次配置恢复定时点赞排程")
    except Exception as e:  # noqa: BLE001 - 恢复失败不应阻塞启动
        logger.error(f"恢复定时点赞排程失败: {e!r}")

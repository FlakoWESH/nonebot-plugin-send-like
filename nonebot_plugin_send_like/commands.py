"""命令层：手动点赞、白名单管理、定时点赞管理。

权限约定（按用户确认）：
- 手动点赞：所有用户可用；
- 白名单与定时相关命令：仅超级用户（`nonebot.permission.SUPERUSER`）。

命令名保持扁平（`白名单添加` 而不是 `白名单 添加`），避免 Alconna 把参数和子命令
混在一起解析。
"""

from __future__ import annotations

from typing import List

from arclet.alconna import Alconna, Args
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.log import logger
from nonebot.permission import SUPERUSER
from nonebot.plugin import require

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import (  # noqa: E402
    AlconnaMatches,
    Arparma,
    At,
    UniMessage,
    on_alconna,
)

from . import ledger, runtime, timed, whitelist  # noqa: E402
from .like_service import LikeStatus  # noqa: E402

LIST_DISPLAY_LIMIT = 50
"""白名单列表最多展示的条数"""


def _extract_at_users(content: UniMessage) -> List[int]:
    """从 UniMessage 中提取 @ 用户列表（过滤 @全体成员）。"""
    users: List[int] = []
    for seg in content:
        if isinstance(seg, At) and seg.flag == "user" and seg.target and seg.target != "all":
            users.append(int(seg.target))
    return users


def _quota_exhausted_text(daily_limit: int) -> str:
    """每日人数额度用尽时的提示文案。"""
    return (
        f"(＞﹏＜) 呜哇——今天已经给 {daily_limit} 位小伙伴点满赞啦，"
        "碰到 QQ 的每日红线了！\n"
        "再点下去 bot 就要被风控抓走关小黑屋了 qaq，"
        "明天额度重置后再来找我玩吧～(｡•́︿•̀｡)"
    )


async def run_manual_like(bot: Bot, at_users: list[int]) -> str:
    """执行手动点赞流程，返回要回复给用户的文本。

    从命令处理器中拆出来，便于不依赖 matcher 上下文做单元验证。

    参数:
        bot: OneBot v11 Bot 实例.
        at_users: 被 @ 的用户 QQ 列表.

    返回:
        str: 汇总回复文本.
    """
    if not at_users:
        return "要 @ 一位小伙伴我才能点赞哦～(´･ω･`)"

    max_users = max(1, int(runtime.config.send_like_manual_max_users))
    if len(at_users) > max_users:
        return (
            f"单次最多给 {max_users} 位小伙伴点赞，"
            "一次点这么多我会手忙脚乱的啦～(>_<)"
        )

    daily_limit = runtime.daily_limit()
    remaining = await runtime.remaining_today()

    # 当天额度已用完（第 daily_limit+1 人调用）
    if remaining <= 0:
        return _quota_exhausted_text(daily_limit)

    need_whitelist = runtime.require_whitelist()
    service = runtime.build_service(bot)

    liked: list[tuple[int, int]] = []
    skipped: list[int] = []
    denied: list[int] = []
    blocked: list[int] = []
    unknown: list[int] = []
    failed: list[int] = []
    quota_full: list[int] = []

    for uid in at_users:
        # 当日人数额度已用尽
        if remaining <= 0:
            quota_full.append(uid)
            continue

        # 白名单校验（默认不启用，开启后白名单外的人直接拒绝）
        if need_whitelist and not await whitelist.is_allowed(runtime.state, uid):
            denied.append(uid)
            continue

        outcome = await service.run(uid, source="manual")
        if outcome.ok:
            liked.append((uid, outcome.times))
            remaining -= 1
        elif outcome.status is LikeStatus.SKIPPED:
            skipped.append(uid)
        elif outcome.status is LikeStatus.BLOCKED:
            blocked.append(uid)
        elif outcome.status is LikeStatus.UNKNOWN:
            unknown.append(uid)
        else:
            failed.append(uid)

    # 汇总回复
    lines: list[str] = []
    if liked:
        names = "、".join(str(uid) for uid, _ in liked)
        lines.append(f"已经给 {names} 点满赞啦～(๑•̀ㅂ•́)و✧")
    if skipped:
        names = "、".join(str(uid) for uid in skipped)
        lines.append(f"{names} 今天已经点过赞啦，明天再来找我～(｡･ω･｡)")
    if denied:
        names = "、".join(str(uid) for uid in denied)
        lines.append(f"{names} 不在白名单里哦～先让超管用「白名单添加 QQ号」把人加进来吧")
    if blocked:
        names = "、".join(str(uid) for uid in blocked)
        lines.append(f"{names} 今天被平台关小黑屋了（点赞上限），明天再试～(つ﹏⊂)")
    if unknown:
        names = "、".join(str(uid) for uid in unknown)
        lines.append(f"{names} 点赞结果不确定，今天先不重复点了，免得被风控抓走～")
    if quota_full:
        names = "、".join(str(uid) for uid in quota_full)
        lines.append(f"{names} 抱歉呀～今天的点赞额度刚好见底了，明天再补上～(｡•́︿•̀｡)")
    if failed:
        names = "、".join(str(uid) for uid in failed)
        lines.append(f"{names} 点赞失败了，稍后再试试～")

    return "\n".join(lines)


# ========== 命令：手动点赞 ==========
like_cmd = on_alconna(
    Alconna("点赞", Args["content", UniMessage, ""]),
    aliases={"赞"},
    priority=5,
    block=True,
)


@like_cmd.handle()
async def handle_manual_like(
    bot: Bot,
    event: Event,
    arp: Arparma = AlconnaMatches(),
):
    """手动点赞处理函数。"""
    content = arp.query[UniMessage]("content", UniMessage())
    text = await run_manual_like(bot, _extract_at_users(content))
    await UniMessage.text(text).finish()


# ========== 命令：白名单管理 ==========
wl_add = on_alconna(
    Alconna("白名单添加", Args["target", str]["remark", str, ""]),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

wl_remove = on_alconna(
    Alconna("白名单移除", Args["target", str]),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

wl_list = on_alconna(
    Alconna("白名单列表"),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

wl_enable = on_alconna(
    Alconna("白名单启用", Args["target", str]),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

wl_disable = on_alconna(
    Alconna("白名单停用", Args["target", str]),
    priority=5,
    block=True,
    permission=SUPERUSER,
)


@wl_add.handle()
async def handle_wl_add(event: Event, arp: Arparma = AlconnaMatches()):
    """添加白名单目标。"""
    raw = str(arp.query("target", "")).strip()
    remark = str(arp.query("remark", "")).strip() or None
    try:
        outcome = await whitelist.add_target(
            runtime.state, raw, remark, event.get_user_id()
        )
    except ValueError as e:
        await UniMessage.text(f"(・_・;) 这个 QQ 号好像不太对：{e}").finish()

    if outcome is whitelist.AddOutcome.EXISTS:
        await UniMessage.text(f"「{raw}」已经在白名单里啦～").finish()

    total = await whitelist.count_targets(runtime.state)
    logger.info(f"白名单添加: {raw}")
    await UniMessage.text(
        f"已经把「{raw}」加入白名单啦～现在一共 {total} 个可点赞目标 (๑•̀ㅂ•́)و✧"
    ).finish()


@wl_remove.handle()
async def handle_wl_remove(arp: Arparma = AlconnaMatches()):
    """移除白名单目标。"""
    raw = str(arp.query("target", "")).strip()
    try:
        removed = await whitelist.remove_target(runtime.state, raw)
    except ValueError as e:
        await UniMessage.text(f"(・_・;) 这个 QQ 号好像不太对：{e}").finish()

    if not removed:
        await UniMessage.text(f"白名单里没有「{raw}」哦，是不是记错号啦～").finish()

    total = await whitelist.count_targets(runtime.state)
    logger.info(f"白名单移除: {raw}")
    await UniMessage.text(f"已经把「{raw}」移出白名单～还剩 {total} 个可点赞目标").finish()


@wl_enable.handle()
async def handle_wl_enable(arp: Arparma = AlconnaMatches()):
    """启用白名单目标。"""
    raw = str(arp.query("target", "")).strip()
    try:
        exists = await whitelist.set_enabled(runtime.state, raw, True)
    except ValueError as e:
        await UniMessage.text(f"(・_・;) 这个 QQ 号好像不太对：{e}").finish()

    if not exists:
        await UniMessage.text(
            f"白名单里没有「{raw}」哦，先用「白名单添加 {raw}」加进来吧～"
        ).finish()

    total = await whitelist.count_targets(runtime.state)
    await UniMessage.text(
        f"已经重新启用「{raw}」～现在一共 {total} 个可点赞目标 (๑•̀ㅂ•́)و✧"
    ).finish()


@wl_disable.handle()
async def handle_wl_disable(arp: Arparma = AlconnaMatches()):
    """停用白名单目标。"""
    raw = str(arp.query("target", "")).strip()
    try:
        exists = await whitelist.set_enabled(runtime.state, raw, False)
    except ValueError as e:
        await UniMessage.text(f"(・_・;) 这个 QQ 号好像不太对：{e}").finish()

    if not exists:
        await UniMessage.text(f"白名单里没有「{raw}」哦，是不是记错号啦～").finish()

    total = await whitelist.count_targets(runtime.state)
    await UniMessage.text(
        f"已经把「{raw}」停用啦，不会再给他点赞～现在还剩 {total} 个可点赞目标"
    ).finish()


@wl_list.handle()
async def handle_wl_list():
    """查看白名单。"""
    rows = await whitelist.list_targets(runtime.state)
    if not rows:
        await UniMessage.text(
            "白名单还是空的哦～用「白名单添加 QQ号」把人加进来吧 (´･ω･`)"
        ).finish()

    enabled = sum(1 for _, entry in rows if entry.get("enabled", True))
    lines = [f"白名单共 {len(rows)} 个目标（启用 {enabled} 个）："]
    for index, (qq, entry) in enumerate(rows[:LIST_DISPLAY_LIMIT], start=1):
        remark = f" - {entry['remark']}" if entry.get("remark") else ""
        status = "" if entry.get("enabled", True) else "（已停用）"
        lines.append(f"{index}. {qq}{remark}{status}")
    if len(rows) > LIST_DISPLAY_LIMIT:
        lines.append(f"……还有 {len(rows) - LIST_DISPLAY_LIMIT} 个未显示")
    await UniMessage.text("\n".join(lines)).finish()


# ========== 命令：定时点赞管理 ==========
sched_on = on_alconna(
    Alconna(
        "定时点赞开启",
        Args["hour", int]["minute", int]["limit", int, 0]["times", int, 0],
    ),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

sched_off = on_alconna(
    Alconna("定时点赞关闭"),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

sched_status = on_alconna(
    Alconna("定时点赞状态"),
    priority=5,
    block=True,
    permission=SUPERUSER,
)

sched_now = on_alconna(
    Alconna("定时点赞立即", Args["limit", int, 0]["times", int, 0]),
    priority=5,
    block=True,
    permission=SUPERUSER,
)


@sched_on.handle()
async def handle_sched_on(bot: Bot, arp: Arparma = AlconnaMatches()):
    """开启每日定时点赞。"""
    hour = int(arp.query("hour", 0))
    minute = int(arp.query("minute", 0))
    limit = int(arp.query("limit", 0))
    times = int(arp.query("times", 0))
    try:
        await timed.enable_schedule(hour, minute, limit, times)
    except RuntimeError as e:
        await UniMessage.text(f"(・_・;) {e}").finish()
    except ValueError as e:
        await UniMessage.text(f"(・_・;) 时间不太对：{e}").finish()

    logger.info(f"定时点赞开启: {hour:02d}:{minute:02d} limit={limit} times={times}")
    extra = []
    if limit > 0:
        extra.append(f"每轮最多 {limit} 人")
    if times > 0:
        extra.append(f"每人 {times} 赞")
    detail = f"（{'，'.join(extra)}）" if extra else ""
    await UniMessage.text(
        f"定时点赞已开启～每天 {hour:02d}:{minute:02d} 自动按白名单点一轮{detail}"
    ).finish()


@sched_off.handle()
async def handle_sched_off():
    """关闭每日定时点赞。"""
    was_enabled = await timed.disable_schedule()
    logger.info("定时点赞关闭")
    if was_enabled:
        await UniMessage.text("定时点赞已经关掉啦，之后不会自动点赞了～").finish()
    await UniMessage.text("定时点赞本来就是关着的哦～").finish()


@sched_status.handle()
async def handle_sched_status():
    """查看定时点赞状态。"""
    status = await timed.schedule_status()
    if not status["available"]:
        await UniMessage.text(
            "(・_・;) 没装 nonebot-plugin-apscheduler，定时功能用不了，"
            "先执行 nb plugin install nonebot-plugin-apscheduler 吧～"
        ).finish()

    if not status["enabled"]:
        await UniMessage.text("定时点赞还没开启哦～用「定时点赞开启 时 分」打开吧").finish()

    lines = [
        f"定时点赞：每天 {status['hour']:02d}:{status['minute']:02d}",
        f"下次触发：{status['next_run']}",
        f"每轮人数：{'全部白名单' if status['limit'] <= 0 else status['limit']}",
        f"每人赞数：{'跟随配置' if status['times'] <= 0 else status['times']}",
    ]
    if not status["job_alive"]:
        lines.append("⚠ 调度器里没找到任务，可能被外部清掉了，建议重启插件或重新开启")
    await UniMessage.text("\n".join(lines)).finish()


@sched_now.handle()
async def handle_sched_now(bot: Bot, arp: Arparma = AlconnaMatches()):
    """立即按白名单执行一轮。"""
    limit = int(arp.query("limit", 0))
    times = int(arp.query("times", 0))
    stats = await timed.run_timed_batch(bot, limit=limit, times=times)
    if stats["total"] == 0:
        await UniMessage.text(
            "这轮没处理任何人哦～可能白名单为空、今天额度用完，或账号已被封锁"
        ).finish()

    lines = [
        f"本轮处理 {stats['total']} 人：点满 {stats['liked']}，部分 {stats['partial']}，"
        f"跳过 {stats['skipped']}，封锁 {stats['blocked']}，"
        f"未知 {stats['unknown']}，失败 {stats['failed']}"
    ]
    if stats["aborted"]:
        lines.append("⚠ 连续命中封锁/未知，已提前中止本轮")
    await UniMessage.text("\n".join(lines)).finish()

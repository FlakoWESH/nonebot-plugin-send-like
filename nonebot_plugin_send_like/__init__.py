"""点赞与自动回赞插件

功能：
1. 手动点赞：发送 "点赞 @用户" 给指定用户点赞（支持白名单强制）
2. 自动回赞：有人把 Bot 资料卡点满时自动回赞（默认 50 次）
3. 白名单：超管维护可点赞名单，定时任务只对名单内启用目标生效
4. 定时批量点赞：每日固定时间按白名单点一轮，可随时关闭
5. 防重复 / 防超量：账本状态机保证同目标同日只点一次，每日人数上限默认 499
6. 风控保护：节奏控制、并发闸门、平台上限识别与当日封锁

依赖：nonebot2 + nonebot-adapter-onebot + nonebot-plugin-alconna
定时功能可选依赖：nonebot-plugin-apscheduler
持久化：JSON 文件存储，零数据库依赖
"""

from nonebot import get_driver, require
from nonebot.adapters.onebot.v11 import Bot, NoticeEvent
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_alconna")

from . import runtime, timed  # noqa: E402
from .bootstrap import seed_superusers  # noqa: E402
from .config import SendLikeConfig  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="点赞与自动回赞",
    description="手动点赞 + 资料卡赞满自动回赞 + 白名单 + 定时批量点赞",
    usage=(
        "点赞 @用户 - 给指定用户点赞\n"
        "白名单添加 QQ号 [备注] - 加入白名单（超管）\n"
        "白名单移除 QQ号 - 移出白名单（超管）\n"
        "白名单列表 - 查看白名单（超管）\n"
        "白名单启用 QQ号 - 重新启用已停用的目标（超管）\n"
        "白名单停用 QQ号 - 停用目标但保留记录（超管）\n"
        "定时点赞开启 时 分 [人数] [次数] - 每天定时按白名单点一轮（超管）\n"
        "定时点赞关闭 - 关闭定时点赞（超管）\n"
        "定时点赞状态 - 查看定时任务状态（超管）\n"
        "定时点赞立即 [人数] [次数] - 立刻按白名单点一轮（超管）\n"
        "给 Bot 资料卡点满赞，Bot 自动回赞"
    ),
    type="application",
    homepage="https://github.com/FlakoWESH/nonebot-plugin-send-like",
    supported_adapters={"~onebot.v11"},
    extra={"version": "0.2.0"},
)

config = runtime.config
"""插件配置（与 runtime 共用同一份解析结果）"""

# 命令层在文件末尾导入：导入即注册 matcher，此时运行时已装配完毕，避免循环导入
from . import commands  # noqa: E402,F401


# ========== 事件：好友资料卡点赞自动回赞 ==========
praise_notice = None
try:
    from nonebot import on_notice

    praise_notice = on_notice(priority=5, block=False)
except Exception:  # noqa: BLE001
    logger.warning("当前 nonebot 版本不支持 on_notice，自动回赞功能未启用")


if praise_notice is not None:

    @praise_notice.handle()
    async def auto_return_like(bot: Bot, event: NoticeEvent):
        """自动回赞处理函数。

        触发条件：好友资料卡点赞事件、当日累计次数达到阈值、当日尚未回赞过。
        """
        if getattr(event, "notice_type", None) != "notify":
            return
        if getattr(event, "sub_type", None) != "friend_praise":
            return
        if not config.send_like_auto_return:
            return

        user_id = str(event.user_id)
        times = getattr(event, "times", 1)
        if not isinstance(times, int) or times < 1:
            times = 1

        record = await runtime.records.increment(user_id, times)
        if record["is_returned"]:
            return

        if record["total_times"] >= config.send_like_praise_threshold:
            try:
                await bot.send_like(user_id=event.user_id, times=config.send_like_return_times)
                await runtime.records.mark_returned(user_id)
                logger.info(
                    f"自动回赞成功 user={user_id} 对方点赞={record['total_times']} "
                    f"回赞次数={config.send_like_return_times}"
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"自动回赞失败 user={user_id}: {e}")


# ========== 启动初始化 ==========
@get_driver().on_startup
async def _startup_init():
    """清理过期数据、导入超管、恢复定时排程。"""
    try:
        await runtime.records.cleanup_old_records(
            keep_days=config.send_like_record_retention_days
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"点赞记录清理失败: {e!r}")

    try:
        await runtime.state.prune(config.send_like_record_retention_days)
    except Exception as e:  # noqa: BLE001
        logger.error(f"账本清理失败: {e!r}")

    try:
        await seed_superusers()
    except Exception as e:  # noqa: BLE001
        logger.error(f"超管导入失败: {e!r}")

    try:
        await timed.restore_schedule()
    except Exception as e:  # noqa: BLE001
        logger.error(f"定时排程恢复失败: {e!r}")

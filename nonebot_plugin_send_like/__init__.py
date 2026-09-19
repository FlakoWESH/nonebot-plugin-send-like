"""
点赞与自动回赞插件（Alconna优化版）
功能：
1. 手动点赞：发送 "点赞 @用户" 给指定用户点赞
2. 自动回赞：当有人给Bot资料卡点满赞时，自动回赞（默认回50次）
优化点：
- 使用 Alconna 命令解析器替代手动遍历 MessageSegment
- 使用 UniMessage 统一消息发送
- 使用 At/Text 消息段类型替代字符串类型判断
依赖：nonebot2 + nonebot-adapter-onebot + nonebot-plugin-alconna
持久化：JSON文件存储，零数据库依赖
"""
from typing import List

from arclet.alconna import Alconna, Args
from nonebot import get_driver, get_plugin_config, on_notice, require
from nonebot.adapters.onebot.v11 import Bot, NoticeEvent
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import (
    AlconnaMatches,
    Arparma,
    At,
    Text,
    UniMessage,
    on_alconna,
)

from .config import SendLikeConfig
from .storage import LikeRecordStore

# ========== 插件元数据 ==========
__plugin_meta__ = PluginMetadata(
    name="点赞与自动回赞",
    description="手动点赞 + 资料卡赞满自动回赞（Alconna优化版）",
    usage=(
        "点赞 @用户 - 给指定用户点赞\n"
        "给Bot资料卡点满赞，Bot自动回赞"
    ),
    type="application",
    homepage="https://github.com/FlakoWESH/nonebot-plugin-send-like",
    supported_adapters={"~onebot.v11"},
)

# ========== 加载配置与存储 ==========
config = get_plugin_config(SendLikeConfig)
store = LikeRecordStore(config.send_like_data_file)


# ========== Alconna参数解析工具 ==========
def _extract_at_users(content: UniMessage) -> List[int]:
    """从UniMessage中提取@用户列表

    Alconna优化点：使用 isinstance(seg, At) 替代 seg.type == "at"
    """
    users = []
    for seg in content:
        if isinstance(seg, At) and seg.flag == "user" and seg.target and seg.target != "all":
            users.append(int(seg.target))
    return users


# ========== 命令1：手动点赞 ==========
# Alconna优化点：
# - on_alconna 替代 on_command
# - aliases 参数注册别名
# - Args["content", UniMessage, ""] 接收包含@用户的消息
like_cmd = on_alconna(
    Alconna("点赞", Args["content", UniMessage, ""]),
    aliases={"赞"},
    priority=5,
    block=True,
)


@like_cmd.handle()
async def manual_like(
    bot: Bot,
    arp: Arparma = AlconnaMatches(),
):
    """手动点赞处理函数

    Alconna优化点：
    - Arparma = AlconnaMatches() 依赖注入获取解析结果
    - arp.query[UniMessage]("content") 类型安全获取参数
    - 替代原生的 args: Message = CommandArg() + 手动遍历seg
    """
    content = arp.query[UniMessage]("content", UniMessage())
    at_users = _extract_at_users(content)

    if not at_users:
        await UniMessage.text("请@需要点赞的用户\n用法：点赞 @用户").finish()

    success = 0
    failed = []
    for user_id in at_users:
        try:
            await bot.send_like(user_id=user_id, times=config.send_like_manual_times)
            success += 1
        except Exception as e:
            failed.append((user_id, str(e)))
            logger.warning(f"手动点赞失败 user={user_id}: {e}")

    # 使用UniMessage构建结果消息
    result = UniMessage.text(f"已成功给 {success} 位用户点赞")
    if failed:
        result += UniMessage.text(f"\n失败 {len(failed)} 人")
        if len(failed) <= 3:
            for uid, reason in failed:
                result += UniMessage.text(f"\n· {uid}：{reason}")

    await result.finish()


# ========== 事件：好友资料卡点赞自动回赞 ==========
# 注意：自动回赞是通知事件，不是命令，因此不使用Alconna
# 保持 on_notice 监听，在函数内筛选事件类型
praise_notice = on_notice(priority=5, block=False)


@praise_notice.handle()
async def auto_return_like(bot: Bot, event: NoticeEvent):
    """自动回赞处理函数

    触发条件：
    1. 事件类型为通知事件（notice）
    2. notice_type = "notify"
    3. sub_type = "friend_praise"（好友资料卡点赞）
    4. 用户当日累计点赞数达到阈值
    5. 当日尚未回赞过
    """
    # 筛选好友点赞事件
    if not hasattr(event, "notice_type") or event.notice_type != "notify":
        return
    if not hasattr(event, "sub_type") or event.sub_type != "friend_praise":
        return

    # 全局开关
    if not config.send_like_auto_return:
        return

    user_id = str(event.user_id)

    # 本次点赞次数（部分协议端会携带times字段，默认1次）
    times = getattr(event, "times", 1)
    if not isinstance(times, int) or times < 1:
        times = 1

    logger.debug(f"收到好友点赞事件 user={user_id} times={times}")

    # 累加点赞次数
    record = await store.increment(user_id, times)

    # 已回赞则跳过（幂等性保证）
    if record["is_returned"]:
        return

    # 达到阈值触发回赞
    if record["total_times"] >= config.send_like_praise_threshold:
        try:
            await bot.send_like(
                user_id=event.user_id,
                times=config.send_like_return_times,
            )
            await store.mark_returned(user_id)
            logger.info(
                f"自动回赞成功 user={user_id} "
                f"对方点赞={record['total_times']} "
                f"回赞次数={config.send_like_return_times}"
            )
        except Exception as e:
            logger.error(f"自动回赞失败 user={user_id}: {e}")


# ========== 启动时清理过期记录 ==========
@get_driver().on_startup
async def _cleanup_on_startup():
    """启动时清理30天前的过期点赞记录"""
    await store.cleanup_old_records(keep_days=30)
    logger.info("点赞记录过期清理完成")

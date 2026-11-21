"""send_like 插件配置"""
from pydantic import BaseModel


class SendLikeConfig(BaseModel):
    """点赞与自动回赞插件配置"""

    # 是否启用自动回赞功能
    send_like_auto_return: bool = True

    # 触发回赞的点赞次数阈值（普通用户10/会员20）
    send_like_praise_threshold: int = 10

    # Bot回赞次数（Bot给非好友默认可点50次）
    send_like_return_times: int = 50

    # 手动点赞命令每次点赞次数
    send_like_manual_times: int = 10

    # 点赞记录数据文件路径
    send_like_data_file: str = "data/send_like_records.json"

    # 白名单/账本/封锁状态文件路径
    send_like_state_file: str = "data/send_like_state.json"

    # 是否要求手动点赞目标必须在白名单内（定时任务始终只读白名单）
    send_like_require_whitelist: bool = False

    # 单次手动点赞最多 @ 多少人
    send_like_manual_max_users: int = 10

    # 每日点赞人数上限（QQ 每日可被点赞的人数红线）
    send_like_daily_like_limit: int = 499

    # 单个目标点满的赞数
    send_like_like_times: int = 50

    # 每轮 send_like 之间的间隔秒数
    send_like_like_round_interval: float = 1.0

    # 节奏控制：单位时间窗口内最多发起多少个目标的点赞
    send_like_pacer_max_calls: int = 6

    # 节奏控制的时间窗口（秒）
    send_like_pacer_time_window: int = 60

    # 批量点赞的最大并发数
    send_like_max_concurrent: int = 2

    # 账本与封锁记录保留天数
    send_like_record_retention_days: int = 30

"""
send_like 插件配置
"""
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

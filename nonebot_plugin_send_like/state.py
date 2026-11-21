"""插件状态存储（JSON 文件，零数据库依赖）。

与 `storage.py` 的点赞记录文件分开存放，避免改动已有 `send_like_records.json`
的格式。结构：

```json
{
  "whitelist": {"123456": {"remark": null, "enabled": true, "created_by": "10000", "created_at": "..."}},
  "ledger": {"2026-11-21": {"123456": {"status": "confirmed", "times": 50, "source": "manual", "note": null, "updated_at": "..."}}},
  "blocks": {"2026-11-21": {"123456": {"reason": "..."}, "global": {"reason": "..."}}},
  "schedule": {"enabled": false, "hour": 9, "minute": 0, "limit": 0, "times": 0}
}
```

所有读写都在同一把 asyncio.Lock 内完成，写入走临时文件 + `os.replace`，
保证并发下不会出现半截文件；字典键天然承担唯一约束（同目标同日只会有一条账本）。
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

from nonebot.log import logger

T = TypeVar("T")

DEFAULT_SCHEDULE: dict[str, Any] = {
    "enabled": False,
    "hour": 9,
    "minute": 0,
    "limit": 0,
    "times": 0,
}
"""定时任务的默认配置（未开启）"""


class StateStore:
    """白名单、账本、封锁与定时配置的统一存储。"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] | None = None

    def _empty(self) -> dict[str, Any]:
        """构造空数据结构。"""
        return {
            "whitelist": {},
            "ledger": {},
            "blocks": {},
            "schedule": dict(DEFAULT_SCHEDULE),
        }

    def _load_locked(self) -> dict[str, Any]:
        """加载数据到内存（调用方需持锁）。"""
        if self._data is not None:
            return self._data
        data = self._empty()
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for key, default in data.items():
                        value = loaded.get(key, default)
                        data[key] = value if isinstance(value, dict) else default
                    data["schedule"] = {**DEFAULT_SCHEDULE, **data["schedule"]}
                logger.info(f"点赞插件状态加载成功：{self.file_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"点赞插件状态文件损坏，将重新创建: {e}")
        self._data = data
        return data

    def _save_locked(self) -> None:
        """原子写盘（调用方需持锁）。"""
        assert self._data is not None
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.file_path)
        except OSError as e:
            logger.error(f"点赞插件状态保存失败: {e}")

    async def read(self) -> dict[str, Any]:
        """读取一份数据副本，调用方修改它不会影响内存状态。"""
        async with self._lock:
            return copy.deepcopy(self._load_locked())

    async def mutate(self, mutator: Callable[[dict[str, Any]], T]) -> T:
        """在锁内修改数据并落盘，返回 mutator 的返回值。

        参数:
            mutator: 接收可变字典的函数，可直接修改结构.
        """
        async with self._lock:
            data = self._load_locked()
            result = mutator(data)
            self._save_locked()
            return result

    async def prune(self, keep_days: int) -> int:
        """删除超过保留天数的账本与封锁记录。

        参数:
            keep_days: 保留天数，小于 1 时不清理.

        返回:
            int: 清理掉的天数条数.
        """
        if keep_days < 1:
            return 0
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()

        def _prune(data: dict[str, Any]) -> int:
            removed = 0
            for section in ("ledger", "blocks"):
                old = [d for d in data[section] if d < cutoff]
                for d in old:
                    del data[section][d]
                removed += len(old)
            return removed

        return await self.mutate(_prune)


def now_text() -> str:
    """当前本地时间字符串，用于记录时间戳。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

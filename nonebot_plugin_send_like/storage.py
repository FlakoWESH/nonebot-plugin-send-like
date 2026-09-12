"""
点赞记录存储模块（纯JSON文件实现，零数据库依赖）
数据结构：
{
    "2026-09-12": {
        "123456": {"total_times": 10, "is_returned": true},
        "789012": {"total_times": 5, "is_returned": false}
    }
}
"""
import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from nonebot.log import logger


class LikeRecordStore:
    """点赞记录存储器（基于JSON文件，异步文件锁保证并发安全）"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._lock = asyncio.Lock()
        self._cache: Dict[str, Dict[str, dict]] = {}
        self._loaded = False

    def _ensure_dir(self):
        """确保数据目录存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """从文件加载数据到内存缓存（同步方法，由调用方加锁）"""
        if self._loaded:
            return
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.info(f"点赞记录加载成功，共 {len(self._cache)} 天的数据")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"点赞记录文件损坏，将重新创建: {e}")
                self._cache = {}
        else:
            self._cache = {}
        self._loaded = True

    def _save(self):
        """将内存缓存保存到文件（同步方法，由调用方加锁）"""
        self._ensure_dir()
        tmp_path = self.file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.file_path)
        except IOError as e:
            logger.error(f"点赞记录保存失败: {e}")
            if tmp_path.exists():
                tmp_path.unlink()

    async def get_or_create(
        self, user_id: str, today: Optional[date] = None
    ) -> dict:
        """获取或创建用户当日点赞记录

        参数:
            user_id: 用户QQ号
            today: 日期，默认为今天

        返回:
            点赞记录字典 {"total_times": int, "is_returned": bool}
        """
        if today is None:
            today = date.today()
        date_key = today.isoformat()

        async with self._lock:
            self._load()
            if date_key not in self._cache:
                self._cache[date_key] = {}
            if user_id not in self._cache[date_key]:
                self._cache[date_key][user_id] = {
                    "total_times": 0,
                    "is_returned": False,
                }
            # 返回副本，避免外部修改
            return dict(self._cache[date_key][user_id])

    async def increment(self, user_id: str, times: int = 1) -> dict:
        """累加用户当日点赞次数

        参数:
            user_id: 用户QQ号
            times: 本次点赞次数

        返回:
            更新后的点赞记录
        """
        today = date.today().isoformat()

        async with self._lock:
            self._load()
            if today not in self._cache:
                self._cache[today] = {}
            if user_id not in self._cache[today]:
                self._cache[today][user_id] = {
                    "total_times": 0,
                    "is_returned": False,
                }
            self._cache[today][user_id]["total_times"] += times
            self._save()
            return dict(self._cache[today][user_id])

    async def mark_returned(self, user_id: str) -> bool:
        """标记用户当日已完成回赞

        参数:
            user_id: 用户QQ号

        返回:
            是否标记成功
        """
        today = date.today().isoformat()

        async with self._lock:
            self._load()
            if (
                today in self._cache
                and user_id in self._cache[today]
            ):
                self._cache[today][user_id]["is_returned"] = True
                self._save()
                return True
            return False

    async def cleanup_old_records(self, keep_days: int = 30):
        """清理超过指定天数的历史记录

        参数:
            keep_days: 保留天数
        """
        from datetime import timedelta

        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        async with self._lock:
            self._load()
            old_dates = [d for d in self._cache if d < cutoff]
            for d in old_dates:
                del self._cache[d]
            if old_dates:
                self._save()
                logger.info(f"清理了 {len(old_dates)} 天的过期点赞记录")

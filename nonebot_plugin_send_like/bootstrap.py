"""超管白名单引导。

首次加载且白名单仍为空时，把超级管理员 QQ 写进白名单，作为定时任务的初始目标，
省去手工添加。读取顺序（取第一个能解析出非空 SUPERUSERS 的来源）：

1. `.env.{ENVIRONMENT}`（nonebot 的标准加载文件，如 `.env.dev`）
2. `.env`
3. nonebot 已解析的 `driver.config.superusers`

只在白名单**完全为空**时导入一次：管理员之后手动删掉的人，重启不会被加回来。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import nonebot
from nonebot.log import logger

from . import runtime, whitelist
from .whitelist import AddOutcome

SUPERUSERS_PATTERN = re.compile(r"^\s*SUPERUSERS\s*=\s*(.+)$", re.MULTILINE)
"""匹配 .env 里的 SUPERUSERS 行"""

ENVIRONMENT_PATTERN = re.compile(r"^\s*ENVIRONMENT\s*=\s*(.+)$", re.MULTILINE)
"""匹配 .env 里的 ENVIRONMENT 行"""

ENV_FILE_NAMES = (".env",)
"""基础环境文件名"""

SEED_REMARK = "超级管理员（自动导入）"
"""自动导入时的备注"""


def _read_text(path: Path) -> str | None:
    """安全读取文本文件，读不到返回 None。"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 配置读取失败不应影响启动
        return None


def _parse_value(raw: str) -> list[str]:
    """把 SUPERUSERS 的值解析成字符串列表，兼容 JSON 与裸逗号写法。"""
    text = raw.strip().strip("'\"")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        return [str(item) for item in data]
    if isinstance(data, str):
        return [data]

    # 兜底：去掉方括号后按逗号切分
    text = text.strip("[]")
    return [part.strip().strip("'\"") for part in text.split(",")]


def parse_superusers(text: str) -> list[str]:
    """从 env 文本中解析 SUPERUSERS，返回去重后的 QQ 字符串列表。

    参数:
        text: env 文件内容.

    返回:
        list[str]: QQ 号列表，无法解析时返回空列表.
    """
    match = SUPERUSERS_PATTERN.search(text)
    if not match:
        return []
    result: list[str] = []
    for item in _parse_value(match.group(1)):
        item = item.strip()
        if not item or item in result:
            continue
        result.append(item)
    return result


def _env_name(root: Path) -> str | None:
    """读取基础 .env 中的 ENVIRONMENT，用于定位 `.env.{env}`。"""
    text = _read_text(root / ".env")
    if not text:
        return None
    match = ENVIRONMENT_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip().strip("'\"")


def candidate_paths(root: Path | None = None) -> list[Path]:
    """按优先级列出候选的配置文件路径。"""
    base = root or Path.cwd()
    names: list[str] = []
    env = _env_name(base)
    if env:
        names.append(f".env.{env}")
    names.extend(ENV_FILE_NAMES)
    return [base / name for name in names]


def load_superusers(root: Path | None = None) -> tuple[list[str], str]:
    """按优先级读取超管 QQ 列表。

    参数:
        root: 项目根目录，None 表示当前工作目录.

    返回:
        tuple[list[str], str]: (QQ 列表，来源描述).
    """
    for path in candidate_paths(root):
        text = _read_text(path)
        if not text:
            continue
        parsed = parse_superusers(text)
        if parsed:
            return parsed, path.name

    try:
        configured = nonebot.get_driver().config.superusers
    except Exception:  # noqa: BLE001 - driver 未初始化时忽略
        configured = set()
    return [str(item) for item in configured if str(item).strip()], "nonebot config"


async def seed_superusers(root: Path | None = None) -> int:
    """白名单为空时，把超管导入白名单。

    参数:
        root: 项目根目录，None 表示当前工作目录.

    返回:
        int: 实际新增的条数（白名单已非空时返回 0）.
    """
    data = await runtime.state.read()
    if data["whitelist"]:
        logger.debug("白名单非空，跳过超管导入")
        return 0

    qq_list, source = load_superusers(root)
    if not qq_list:
        logger.info("未读取到超管 QQ，白名单保持为空")
        return 0

    added = 0
    for qq in qq_list:
        try:
            outcome = await whitelist.add_target(runtime.state, qq, SEED_REMARK)
        except ValueError:
            logger.warning(f"超管 QQ 不合法，已跳过: {qq}")
            continue
        if outcome is AddOutcome.ADDED:
            added += 1

    logger.info(f"已从 {source} 导入 {added} 个超管到白名单")
    return added

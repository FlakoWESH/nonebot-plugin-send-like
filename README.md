<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-send-like ✨
[![LICENSE](https://img.shields.io/github/license/FlakoWESH/nonebot-plugin-send-like.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-send-like.svg)](https://pypi.python.org/pypi/nonebot-plugin-send-like)
[![python](https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg)](https://www.python.org)
<br/>
[![ruff](https://img.shields.io/badge/code%20style-ruff-black?style=flat-square&logo=ruff)](https://github.com/astral-sh/ruff)
[![nonebot2](https://img.shields.io/badge/nonebot-2.0+-red.svg)](https://v2.nonebot.dev)
[![alconna](https://img.shields.io/badge/Alconna-powered-blue?style=flat-square)](https://github.com/nonebot/plugin-alconna)

</div>

## 📖 介绍

NoneBot2 资料卡点赞插件，支持手动给指定用户点赞，以及自动回赞功能。基于 Alconna 命令解析器优化。

- **手动点赞**：在群聊或私聊中 @用户 即可为其资料卡点赞
- **自动回赞**：当有用户点赞 Bot 资料卡并赞满指定阈值时，Bot 自动回赞对方
- **点赞阈值触发**：可配置触发回赞所需的点赞次数（普通用户每天只能给单个用户点 10 赞，会员 20 赞）
- **回赞数量可配**：Bot 回赞次数可配置（Bot 可给非好友点 50 赞）
- **记录持久化**：自动记录点赞事件，防止重复触发回赞
- **Alconna 优化**：使用 Alconna 命令解析器，类型安全参数获取

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-send-like --upgrade

使用 **pypi** 源安装

    nb plugin install nonebot-plugin-send-like --upgrade -i "https://pypi.org/simple"

使用 **清华源** 安装

    nb plugin install nonebot-plugin-send-like --upgrade -i "https://pypi.tuna.tsinghua.edu.cn/simple"

</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details open>
<summary>uv</summary>

    uv add nonebot-plugin-send-like

安装仓库 master 分支

    uv add git+https://github.com/FlakoWESH/nonebot-plugin-send-like@master
</details>

<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-send-like

安装仓库 master 分支

    pdm add git+https://github.com/FlakoWESH/nonebot-plugin-send-like@master
</details>

<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-send-like

安装仓库 master 分支

    poetry add git+https://github.com/FlakoWESH/nonebot-plugin-send-like@master
</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_send_like"]

</details>

## ⚙️ 配置

在 `.env` 文件中添加以下配置（均为可选，有默认值）：

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| SEND_LIKE_AUTO_RETURN | 否 | `true` | 是否启用自动回赞功能 |
| SEND_LIKE_PRAISE_THRESHOLD | 否 | `10` | 触发自动回赞所需的点赞阈值 |
| SEND_LIKE_RETURN_TIMES | 否 | `50` | Bot 自动回赞的次数 |
| SEND_LIKE_MANUAL_TIMES | 否 | `10` | 手动点赞时每次点赞的次数 |
| SEND_LIKE_DATA_FILE | 否 | `data/send_like_records.json` | 点赞记录文件路径 |

### 点赞次数说明

| 用户类型 | 每日可给单个用户点赞数 |
|:---:|:---:|
| 普通 QQ 用户 | 10 次 |
| QQ 会员 | 20 次 |
| Bot（给非好友） | 50 次 |

## 🎉 使用

### 指令表

| 指令 | 说明 |
|:---:|:---:|
| 点赞 @用户 | 手动为指定用户资料卡点赞 |
| 赞 @用户 | 同上，别名 |

### 自动回赞

自动回赞为被动事件，无需手动指令：
1. 当有用户点赞 Bot 的资料卡
2. 累计点赞次数达到 `SEND_LIKE_PRAISE_THRESHOLD`（默认 10 次）
3. Bot 自动回赞对方 `SEND_LIKE_RETURN_TIMES`（默认 50 次）
4. 回赞记录持久化，同一天不会重复回赞同一用户

### 使用示例

```
点赞 @123456
赞 @789012
```

## ⚠️ 注意事项

1. **协议端要求**：自动回赞依赖 `friend_praise` 事件通知，需协议端支持该事件上报（NapCatQQ、Lagrange 等主流协议端均支持）
2. **点赞频率**：QQ 官方限制每日点赞次数，超出限制会失败
3. **记录文件**：默认存储在 `data/send_like_records.json`，请确保数据目录可写
4. **协议端兼容**：基于 OneBot v11 标准 API 开发，适配 go-cqhttp、NapCatQQ、Lagrange.Core 等主流协议端

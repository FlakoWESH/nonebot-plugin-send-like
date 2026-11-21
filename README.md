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
- **白名单**：超管维护可点赞名单，定时任务只对名单内启用目标生效（手动点赞默认不强制）
- **定时批量点赞**：每天固定时间按白名单点一轮，可随时关闭，重启后自动恢复排程
- **防重复**：账本状态机保证同一目标当天只点一次，中途失败也能正确落账
- **防超量**：每日点赞人数上限默认 499，达到红线直接拒绝而非硬打
- **风控保护**：节奏控制（默认 6 人 / 60 秒）、并发上限（默认 2）、平台上限识别并当日封锁
- **超管自动入驻**：首次加载且白名单为空时，自动把 `SUPERUSERS` 写入白名单

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

> 定时点赞依赖的 **nonebot-plugin-apscheduler** 已随插件自动安装。若你的环境手动裁剪了依赖，缺少它时插件仍可加载，仅定时相关命令会提示安装。

## ⚙️ 配置

在 `.env` 文件中添加以下配置（均为可选，有默认值）：

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| SEND_LIKE_AUTO_RETURN | 否 | `true` | 是否启用自动回赞功能 |
| SEND_LIKE_PRAISE_THRESHOLD | 否 | `10` | 触发自动回赞所需的点赞阈值 |
| SEND_LIKE_RETURN_TIMES | 否 | `50` | Bot 自动回赞的次数 |
| SEND_LIKE_MANUAL_TIMES | 否 | `10` | 手动点赞时每次点赞的次数 |
| SEND_LIKE_DATA_FILE | 否 | `data/send_like_records.json` | 点赞记录文件路径 |
| SEND_LIKE_STATE_FILE | 否 | `data/send_like_state.json` | 白名单 / 账本 / 封锁 / 定时配置文件路径 |
| SEND_LIKE_REQUIRE_WHITELIST | 否 | `false` | 手动点赞是否要求目标在白名单内（定时任务始终只读白名单） |
| SEND_LIKE_MANUAL_MAX_USERS | 否 | `10` | 单次手动点赞最多 @ 多少人 |
| SEND_LIKE_DAILY_LIKE_LIMIT | 否 | `499` | 每日点赞人数上限 |
| SEND_LIKE_LIKE_TIMES | 否 | `50` | 单个目标点满的赞数 |
| SEND_LIKE_LIKE_ROUND_INTERVAL | 否 | `1.0` | 每轮 `send_like` 之间的间隔秒数 |
| SEND_LIKE_PACER_MAX_CALLS | 否 | `6` | 单位时间窗口内最多发起多少个目标 |
| SEND_LIKE_PACER_TIME_WINDOW | 否 | `60` | 节奏控制的时间窗口（秒） |
| SEND_LIKE_MAX_CONCURRENT | 否 | `2` | 批量点赞最大并发数 |
| SEND_LIKE_RECORD_RETENTION_DAYS | 否 | `30` | 账本与封锁记录保留天数 |

### 点赞次数说明

| 用户类型 | 每日可给单个用户点赞数 |
|:---:|:---:|
| 普通 QQ 用户 | 10 次 |
| QQ 会员 | 20 次 |
| Bot（给非好友） | 50 次 |

## 🎉 使用

### 指令表

| 指令 | 说明 | 权限 |
|:---:|:---:|:---:|
| 点赞 @用户 | 手动为指定用户资料卡点赞 | 所有人 |
| 赞 @用户 | 同上，别名 | 所有人 |
| 白名单添加 QQ号 [备注] | 加入白名单 | 超管 |
| 白名单移除 QQ号 | 移出白名单 | 超管 |
| 白名单列表 | 查看名单、备注与停用状态 | 超管 |
| 白名单启用 QQ号 | 重新启用已停用的目标 | 超管 |
| 白名单停用 QQ号 | 停用目标但保留记录 | 超管 |
| 定时点赞开启 时 分 [人数] [次数] | 每天定时按白名单点一轮 | 超管 |
| 定时点赞关闭 | 关闭定时点赞 | 超管 |
| 定时点赞状态 | 查看排程与下次触发时间 | 超管 |
| 定时点赞立即 [人数] [次数] | 立刻按白名单点一轮 | 超管 |

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

## 📋 白名单

- 白名单只决定**定时任务给谁点**；手动点赞是否受限由 `SEND_LIKE_REQUIRE_WHITELIST` 控制，默认关闭，升级后行为不变
- 停用只改状态不删记录，列表里会标注「已停用」，随时可用「白名单启用」恢复
- 首次加载且白名单为空时，自动把 `SUPERUSERS` 导入（备注「超级管理员（自动导入）」），只导一次，之后手动删掉的人不会在重启时补回来
- 读取顺序：`.env.{ENVIRONMENT}` → `.env` → nonebot 已解析的 `superusers`

## ⏰ 定时点赞

- 插件加载时**不会自动建排程**，必须由超管执行「定时点赞开启」才会开始运行
- 开启参数写入 `send_like_state.json`，重启后自动恢复；调度器本身是内存态，所以恢复依赖该文件
- 每轮只处理白名单内启用目标，受「每日人数上限」约束；连续 3 个目标命中封锁/未知会提前中止本轮
- 命令只接受「时 分」，不接受 cron 表达式，避免 Alconna 按空格分词把表达式拆散

## 🧾 防重复与防超量

账本按「目标 + 日期」记录状态，同一天同一目标只会真正执行一次：

| 状态 | 含义 | 当日是否再点 |
|:---:|:---|:---:|
| `reserved` | 已预占，请求执行中 | 否 |
| `confirmed` | 已确认点出（含部分成功） | 否 |
| `unknown` | 结果不确定 | 否 |
| `blocked` | 命中平台上限 | 否 |
| `failed` | 明确失败且无副作用 | 是，允许重试 |

每日人数上限从点赞记录统计（手动点赞与自动回赞都占额度），默认 499，超过直接拒绝并提示，不会把请求打到协议端。

## ⚠️ 注意事项

1. **协议端要求**：自动回赞依赖 `friend_praise` 事件通知，需协议端支持该事件上报（NapCatQQ、Lagrange 等主流协议端均支持）
2. **点赞频率**：QQ 官方限制每日点赞次数，超出限制会失败
3. **记录文件**：默认存储在 `data/send_like_records.json`，请确保数据目录可写
4. **协议端兼容**：基于 OneBot v11 标准 API 开发，适配 go-cqhttp、NapCatQQ、Lagrange.Core 等主流协议端
5. **权限**：白名单与定时命令仅响应 `SUPERUSERS`，配置里没写超管则这些命令不可用
6. **状态文件**：`data/send_like_state.json` 保存白名单、账本、封锁与定时配置，删除等同于清空名单与当日记录
7. **平台上限识别基于关键词**：命中「频繁 / 上限 / too many」等提示才判定限流，未命中会按未知处理（当日不重试）

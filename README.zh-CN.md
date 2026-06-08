# net-auto-switch

[![CI](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](.python-version)

[English](README.md) · **简体中文**

macOS 上的**分层网络自动优化守护进程**:底层按需切换 WiFi,上层自动切换 Clash Verge 节点 / 订阅,在网络变差时无需人工干预即可恢复连通与代理质量。

## Features

- **分层编排** — 每轮先检查 WiFi(物理层),再检查 Clash(代理层),"先保证能上网,再保证代理质量"
- **WiFi 层可选 + 低频** — 通过开关启用;独立检查间隔 + 切换冷却双保险,避免频繁切换
- **Clash 节点智能选择** — 按可配置地区分组(默认 SG → Tokyo → JP_Other),延迟测速 + 优先级降级
- **Profile 兜底** — 所有节点不可用时,通过 AppleScript 自动切换订阅
- **配置全外置** — 阈值 / 间隔 / 端口 / secret / 地区正则均在 `config.toml`,secret 不入库
- **`--dry-run`** — 演练模式,完全无副作用(不做任何真实切换)
- **故障隔离** — 任一层瞬时错误不会拖垮守护进程
- **开机自启** — launchd 服务,`RunAtLoad` + `KeepAlive` 崩溃自动重启

## 功能特性概览

| 类别 | 做什么 |
|------|--------|
| **分层编排** | 每轮先跑 WiFi 层、再跑 Clash 层 —— 先保证能上网,再优化代理。两层相互隔离:单层失败不影响另一层、也不会杀掉守护进程。 |
| **WiFi 层**(可选,低频) | 读当前网络并 ping 测延迟 / 丢包;超过阈值判定"网差";候选 = *已存偏好网络 ∩ 当前可扫到的网络*;**只有候选快出至少 `min_improvement_ms` 才切换**。受独立检查间隔**与**切换后冷却双重约束。 |
| **Clash 节点选择** | 按地区分组(SG / Tokyo / JP_Other,正则可配);当前节点稳定(`delay_limit`)就不动;否则测速选本组最佳,并按 `group_priority` 跨地区降级。名字看不出城市的 JP 节点会经 IP 归属地实测来识别东京。 |
| **订阅兜底** | 所有节点不可用时,通过 AppleScript UI 自动化切换订阅 profile。 |
| **频率限制** | 节点切换 ≤ `max_switch_per_min`;订阅切换 ≤ `max_profile_switch_per_30min`。 |
| **运行模式** | 长驻守护、单轮(`--once`)、零副作用演练(`--dry-run`);`--config` 指定配置。 |
| **安装与运维** | 一行 `curl` 安装、`init` 引导向导(自动探测 Clash Verge)、一键 `update`、launchd 服务(开机自启 + 崩溃重启)。日志每天轮转、14 天后自动清理。 |
| **配置与安全** | 所有可调项在 `config.toml`(加载时校验);secret 绝不入库 —— 仓库只跟踪 `config.example.toml`。 |

## Architecture

```
cli.py  (argparse 入口: --once / --dry-run / --config + 日志)
   │
   └── orchestrator.py  (主循环: WiFi 优先 → Clash; 频率/冷却; 故障隔离)
         ├── wifi.py    (WiFi 层: 探测/扫描/切换 via networksetup/system_profiler/ping)
         ├── clash.py   (ClashController: 分组/选择算法/节点切换/profile 兜底)
         └── config.py  (TOML 加载 → dataclass + 校验)
```

详见 [`CONTEXT.md`](CONTEXT.md)(领域术语与不变量)与 [`docs/adr/`](docs/adr/)(架构决策)。

## Quick Start

### 一行安装(推荐)

```bash
curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash
```

自动:没 [uv](https://docs.astral.sh/uv/) 就装 uv → clone 到 `~/.net-auto-switch` →
装依赖 → 安装全局 `net-auto-switch` 命令 → 跑 `init` 引导。再次执行即更新已有安装。

### 手动安装

```bash
git clone https://github.com/OctopusGarage/net-auto-switch.git
cd net-auto-switch
uv sync                  # 创建 .venv(Python 由 .python-version 固定)并装依赖
uv run net-auto-switch init   # 引导式安装 — 见下
```

想直接下载?每个 [release](https://github.com/OctopusGarage/net-auto-switch/releases)
都自带自动生成的源码 tarball / zip。

### 引导式安装(`init`)

`init` 会读取 Clash Verge 的配置,**自动探测** API 地址、secret、代理端口、
`profiles.yaml` 路径,验证连接,**做健康检查**(没有可用节点则中止并给出指引),
**检查每个订阅的自动更新 / 到期 / 流量并引导你修复过期订阅**,
**扫描你订阅里的实际节点、识别出有哪些地区(US / JP / HK …)并让你挑选优先级**,
写入 `config.toml`(已有则先备份),并询问是否注册 launchd 服务:

```bash
uv run net-auto-switch init          # 交互式
uv run net-auto-switch init --yes    # 全自动(采用所有默认值)
```

`init` 每一步都会检查环境并明确告诉你怎么修 —— 比如不是 macOS、Clash Verge 没装 /
没运行 / 连不上、secret 不对、或没有可用节点时,都会给出对应指引。

想手动配置(或不使用 Clash Verge)?改用模板:
`cp config.example.toml config.toml`,然后编辑它。

```bash
# 不切换任何东西,先演练验证
uv run net-auto-switch --once --dry-run
```

### 更新

```bash
net-auto-switch update    # 拉取最新 + 重新装依赖 + 重载 launchd 服务
```

(手动 clone 的话:`git pull && uv sync`,再重跑 `./scripts/install-launchd.sh`。)

## Usage

```bash
uv run net-auto-switch init                 # 引导式安装(见 Quick Start)
uv run net-auto-switch update               # 更新到最新版本
uv run net-auto-switch --once --dry-run    # 单轮、演练
uv run net-auto-switch --once              # 单轮
uv run net-auto-switch                      # 长驻
uv run net-auto-switch --config /path/to/config.toml
```

`uv run net-auto-switch` 等价于 `uv run python -m net_auto_switch.cli`。

### 进程管理脚本

```bash
./scripts/start.sh    # 后台手动启动(写 .net-auto-switch.pid)
./scripts/status.sh   # 查看是否运行
./scripts/stop.sh     # 停止
```

## Configuration

所有设置在 `config.toml`(模板见 `config.example.toml`)。

| 键 | 默认 | 说明 |
|----|------|------|
| `main_interval` | `600` | 主循环间隔(秒) |
| `wifi.enabled` | `true` | 是否启用 WiFi 层 |
| `wifi.check_interval` | `3600` | WiFi 检查间隔(秒) |
| `wifi.switch_cooldown` | `7200` | WiFi 切换后冷却(秒) |
| `wifi.bad_latency_ms` | `200` | 判定"网差"的延迟阈值 |
| `wifi.bad_loss_pct` | `5` | 判定"网差"的丢包阈值(%) |
| `wifi.min_improvement_ms` | `100` | 改善达到此值才切换 |
| `wifi.interface` | `en0` | WiFi 网卡 |
| `clash.api` | `http://127.0.0.1:9097` | Clash 外部控制 API |
| `clash.secret` | *(必填)* | Clash API secret |
| `clash.proxy_port` | `7890` | Clash HTTP 代理端口(IP 定位用) |
| `clash.delay_limit` | `300` | 当前节点稳定阈值(ms) |
| `clash.max_switch_per_min` | `3` | 每分钟最多节点切换次数 |
| `clash.max_profile_switch_per_30min` | `1` | 每 30 分钟最多 profile 切换次数 |
| `clash.profiles_yaml` | *(Clash Verge 路径)* | profiles.yaml 位置 |
| `clash.group_priority` | `["SG","Tokyo","JP_Other"]` | 地区降级优先级(名称须在 `regions` 中定义) |
| `clash.trial` | `试用` | 名字命中此正则的节点被忽略 |
| `clash.regions` | SG / Tokyo / JP_Other | 地区名 → 正则,按顺序匹配(先命中者胜)。**完全可配** |
| `clash.ip_enrich` | Tokyo ← JP_Other | 可选:按 IP 归属地把节点重分类进某地区;删掉即关闭 |

**自定义地区** —— `regions` 完全可配,可以把任意地区设为主。比如「以美国为主」:

```toml
group_priority = ["US", "JP", "SG"]

[clash.regions]
US = "(US|United States|美国|🇺🇸)"
JP = "(JP|Japan|日本|🇯🇵)"
SG = "(SG|Singapore|新加坡|🇸🇬)"
```

节点按**第一个**命中的地区归类(更具体的写前面);一个都不命中的节点会被忽略。

## Production Deployment (macOS launchd)

以 launchd 服务运行,开机自启 + 崩溃自动重启:

```bash
./scripts/install-launchd.sh     # 装依赖 + 生成 plist + 注册并加载
./scripts/uninstall-launchd.sh   # 卸载

# 手动查看
launchctl list com.octopusgarage.net-auto-switch
tail -f logs/launchd.err.log
```

**特性:**
- `RunAtLoad` — 开机即启动
- `KeepAlive` + `ThrottleInterval=10` — 崩溃自动重启,最小间隔 10s(防崩溃循环)
- launchd 标准输出/错误 → `logs/launchd.out.log` / `logs/launchd.err.log`

## Resilience

| 机制 | 行为 |
|------|------|
| 层级隔离 | WiFi / Clash 各自 try/except,单层失败不影响另一层、不杀进程 |
| Clash API 错误 | 捕获 `RequestException`,记录后进入下一轮 |
| 节点全挂 | 自动切换订阅 profile 兜底(受 30 分钟频率限制) |
| 切换频率限制 | 节点 ≤ 3 次/分钟,profile ≤ 1 次/30 分钟 |
| 进程自愈 | launchd `KeepAlive` 崩溃自动重启 |

## Logs

- **程序日志(权威)**:`~/Library/Logs/net_auto_switch.log` —— **每天午夜轮转,保留 14 天**自动清理(`TimedRotatingFileHandler`),不会无限增长。
- launchd 方式运行时:stdout 丢弃(`/dev/null`,避免与上面的轮转日志重复),`logs/launchd.err.log` 仅捕获日志系统初始化前的崩溃(正常运行时基本为空)。
- 手动 `start.sh` 运行时:输出追加到 `logs/net-auto-switch.out.log`(开发用)。

保留天数由 `cli.py` 的 `LOG_BACKUP_DAYS` 控制(默认 14)。

## Project Layout

```
net-auto-switch/
├── net_auto_switch/     # 包: config / setup / wifi / clash / orchestrator / cli
├── tests/               # pytest 单测
├── scripts/             # 运维脚本 + launchd plist + wrapper
├── docs/
│   └── adr/             # 架构决策记录
├── install.sh           # 一行 curl 安装脚本(引导)
├── config.example.toml  # 配置模板(config.toml 被 gitignore)
├── CONTEXT.md           # 领域术语与不变量
├── pyproject.toml       # 依赖 + 工具配置(pytest / ruff)
├── uv.lock              # uv 锁定的依赖版本(提交入库)
└── .python-version      # 固定 Python 版本(uv 读取)
```

## Testing

```bash
uv run pytest          # 全量单测
uv run ruff check .    # 静态检查
uv run ruff format .   # 格式化
```

## Requirements

- macOS,[uv](https://docs.astral.sh/uv/)(自动管理 Python 3.12,见 `.python-version`)
- Clash Verge 已运行且开启外部控制(API 端口与 secret 与配置一致)
- WiFi 切换需相应系统权限;profile 兜底依赖"系统设置 → 隐私与安全性 → 辅助功能"授权

## Contributing

欢迎贡献 —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE) © Kingson Wu

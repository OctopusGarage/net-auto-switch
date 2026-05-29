# net-auto-switch

macOS 上的**分层网络自动优化守护进程**:底层按需切换 WiFi,上层自动切换 Clash Verge 节点 / 订阅,在网络变差时无需人工干预即可恢复连通与代理质量。整合并重构自 `dev_env_utils` 下的 `wifi_auto_switch.py` 与 `clash_verge_auto_switch_region.py`。

## Features

- **分层编排** — 每轮先检查 WiFi(物理层),再检查 Clash(代理层),"先保证能上网,再保证代理质量"
- **WiFi 层可选 + 低频** — 通过开关启用;独立检查间隔 + 切换冷却双保险,避免频繁切换
- **Clash 节点智能选择** — 按地区分组(SG → Tokyo → JP_Other),延迟测速 + 优先级降级
- **Profile 兜底** — 所有节点不可用时,通过 AppleScript 自动切换订阅
- **配置全外置** — 阈值 / 间隔 / 端口 / secret / 地区正则均在 `config.toml`,secret 不入库
- **`--dry-run`** — 演练模式,完全无副作用(不做任何真实切换)
- **故障隔离** — 任一层瞬时错误不会拖垮守护进程
- **开机自启** — launchd 服务,`RunAtLoad` + `KeepAlive` 崩溃自动重启

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

```bash
cd net-auto-switch
cp config.example.toml config.toml   # 修改 secret / 端口 / 阈值
pip install -e ".[dev]"

# 手动演练(不实际切换)
python -m net_auto_switch.cli --once --dry-run
```

## Usage

```bash
python -m net_auto_switch.cli --once --dry-run    # 单轮、演练
python -m net_auto_switch.cli --once              # 单轮
python -m net_auto_switch.cli                      # 长驻
python -m net_auto_switch.cli --config /path/to/config.toml
```

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
| `clash.group_priority` | `["SG","Tokyo","JP_Other"]` | 地区降级优先级 |
| `clash.patterns.*` | *(正则)* | SG / JP / Tokyo / 试用 的识别正则 |

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

- 程序日志:`~/Library/Logs/net_auto_switch.log`
- launchd 捕获:`logs/launchd.out.log` / `logs/launchd.err.log`(launchd 方式运行时)
- 手动 `start.sh` 捕获:`logs/net-auto-switch.out.log`

## Project Layout

```
net-auto-switch/
├── net_auto_switch/     # 包: config / wifi / clash / orchestrator / cli
├── tests/               # pytest 单测(40 cases)
├── scripts/             # 运维脚本 + launchd plist + wrapper
├── docs/
│   ├── adr/             # 架构决策记录
│   └── superpowers/     # 设计 spec 与实现 plan
├── config.example.toml  # 配置模板(config.toml 被 gitignore)
├── CONTEXT.md           # 领域术语与不变量
├── CLAUDE.md            # 项目原则(给 Claude Code)
└── pyproject.toml
```

## Testing

```bash
pytest          # 全量单测
ruff check .    # 静态检查
```

## Requirements

- macOS,Python 3.11+
- Clash Verge 已运行且开启外部控制(API 端口与 secret 与配置一致)
- WiFi 切换需相应系统权限;profile 兜底依赖"系统设置 → 隐私与安全性 → 辅助功能"授权

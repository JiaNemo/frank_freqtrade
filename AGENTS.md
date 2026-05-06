# Freqtrade AGENTS.md

## Dev Setup

```bash
uv pip install -r requirements-dev.txt
uv pip install -e .
```

## Running Tests

```bash
pytest tests/freqai/
pytest tests/ -k freqai
```

## Code Quality

```bash
ruff check . && ruff format .
mypy freqtrade
pre-commit run -a
```

## PR Conventions

- PRs go to `develop` branch, not `stable`
- Install pre-commit: `pre-commit install`

---

## Trading Bot Server (47.108.169.101)

### Server Info
- IP: 47.108.169.101
- SSH: `ssh root@47.108.169.101`
- Strategies: `/data/freqtrade/user_data/strategies/`
- Freqtrade source: `/data/freqtrade/freqtrade/`
- Venv: `/data/venv/bin/`
- API Auth: `freqtrade:freqtrade123`

### Bot Architecture
| 项目 | 值 |
|-----|-----|
| Service | freqtrade |
| Port | 8888 |
| Config | configLong.json |
| 策略 | RecoveryStrategyMulti v19 |

### Bot Management
```bash
# systemctl
ssh root@47.108.169.101 "systemctl restart freqtrade"
ssh root@47.108.169.101 "systemctl status freqtrade"

# API
curl -s -X POST http://127.0.0.1:8888/api/v1/start -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='
curl -s -X POST http://127.0.0.1:8888/api/v1/stop -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='

# 快速启动
./ai/shell/startbot.sh
```

### OKX WebSocket
Config中已设置 `ws_enabled: false`。重启后Bot进入STOPPED状态，需调用 `/api/v1/start` 恢复交易。

### Troubleshooting
- Bot STOPPED after restart: call `/api/v1/start`
- WebSocket errors: `journalctl -u freqtrade | grep ERROR`
- RateLimit (code 50011): wait or reduce whitelist size

### 数据库查询
```bash
ssh root@47.108.169.101 "sudo -u postgres psql -d trading -c 'SELECT ... FROM trades ORDER BY id DESC LIMIT 10;'"
```

---

## RecoveryStrategyMulti v19 (当前策略)

### 核心思想
**熬到盈利** — 大幅放宽止损让交易撑住波动，trailing够宽让利润跑，用max_open_trades控频而非收紧入场信号。

### 核心参数
| 参数 | 值 |
|-----|-----|
| timeframe | 5m |
| can_short | True |
| max_open_trades | 7 |
| max_hours_before_force_entry | 12 |
| cooldown_minutes | **120min(常规) / 90min(7-9am)** |
| profit_target_usdt | **99(已禁用)**，由trailing stop决定退出 |

### ATR 动态止损 (v19)
| ATR% | 波动状态 | Long止损 | Short止损 |
|------|---------|---------|----------|
| < 0.20 | 低波动 | -6.0% | -5.0% |
| 0.20 - 0.30 | 中波动 | -7.0% | -6.0% |
| > 0.30 | 高波动 | -8.0% | -7.0% |

fallback: Long -6.0%, Short -5.0%

价格触发线(4X)：Long低1.50%/中1.75%/高2.00%, Short低1.25%/中1.50%/高1.75%

### ATR 动态杠杆
| ATR% | 波动状态 | 杠杆 |
|----------|---------|------|
| > 0.35 | 极高波动 | 4X |
| 0.25 - 0.35 | 高波动 | 5X |
| 0.15 - 0.25 | 低波动 | 6X |
| < 0.15 | 极低波动 | 7X |

### Entry 信号 (v18)
| 方向 | 条件 |
|------|------|
| Long | RSI < 45, slowk < 40, atr% < 2.5, atr% > 0.3, close > EMA200, 15m RSI < 55, rsi_rising(shift1), ema200_slope > 0.005 |
| Short | RSI > 55, slowk > 35, atr% < 2.0, atr% > 0.3, close < EMA200, 15m RSI > 45, rsi_falling(shift1), ema200_slope < -0.005 |

7-9am Long额外限制：RSI<40, slowk<30

### Exit 信号
| 方向 | 条件 |
|------|------|
| Long | fisher_rsi > 0.5 AND RSI > 70 |
| Short | fisher_rsi < -0.5 AND RSI > 80 |

### Trailing Stop (时段化)
| 时段 | Long positive | Long offset | Short positive | Short offset |
|------|--------------|-------------|---------------|-------------|
| 0-8am | **1.5%** | 4% | 1.5% | 4% |
| 9-18h | 3% | **4%** | 1.5% | 2% |
| 18-21h | 3% | 6% | 1.5% | 4% |

### 冷却与风控 (v19)
- 同pair+方向止损后cooldown **120min**（7-9am 90min）
- **全局方向冷却**：任何币stoploss后，该方向所有币60min内不可入场
- **方向熔断**：连续2笔同方向stoploss后暂停该方向60min
- 逆转暂停：连败熔断(open trades>=2笔同方向亏损) + 连续亏损3笔暂停

### 时段方向逆转 (v12 动态逆转)
| 时段 (CST) | 逆转逻辑 |
|------------|---------|
| 0-8am | 动态：滚动3天Short胜率>Long+10%→保持Short，否则S→L |
| 10am-4pm | 动态：滚动3天Short胜率>Long+10%→保持Short，否则S→L |
| 7pm-11pm | 动态：滚动3天Long胜率>Short+10%→保持Long，否则L→S |

参数：`no_short_before_hour=8`，动态逆转每5分钟重算

### 黑名单
- Long: HYPE, TAO, TRUMP
- Short: LDO, BLUR, PEOPLE, ORDI

---

## Config Files

| 文件 | 本地 | 服务器 |
|-----|------|--------|
| configLong.json | `ai/config/` | `/data/freqtrade/` |
| RecoveryStrategyMulti.py | `ai/strategies/` | `/data/freqtrade/user_data/strategies/` |

### configLong.json 关键参数
| 参数 | 值 |
|-----|-----|
| max_open_trades | 7 |
| stake_amount | 10 USDT |
| dry_run | false |
| trading_mode | futures |
| margin_mode | isolated |
| max_leverage | 7 |
| trailing_stop | true |
| trailing_stop_positive | 0.015 |
| trailing_stop_positive_offset | 0.02 |
| use_custom_stoploss | true |
| strategy | RecoveryStrategyMulti |
| ws_enabled | false |

### Whitelist (22 pairs)
BTC, SOL, BCH, DOGE, AVAX, ARB, ENS, NEAR, BLUR, ENJ, PEOPLE, SHIB, ICP, ORDI, HYPE, TRUMP, BNB, TAO, LDO, ZEC, LTC, PENDLE

### Blacklisted Pairs (27 pairs)
XRP, UNI, INJ, ATOM, FIL, ADA, APT, SUI, COMP, ETH, LINK, SEI, OP, AAVE, SATS, MATIC, MKR, FTM, STG 等

---

## Database Schema (PostgreSQL)

### trades table 关键字段
| 列 | 类型 | 说明 |
|----|------|------|
| id | SERIAL PK | |
| pair | VARCHAR(25) | 交易对 |
| is_open | BOOLEAN | 是否持仓中 |
| is_short | BOOLEAN | 做空标记 |
| open_rate / close_rate | DOUBLE | 开/平仓价格 |
| open_date / close_date | TIMESTAMP | 开/平仓时间 (naive, CST) |
| close_profit_abs | DOUBLE | 实际盈亏(USDT) |
| stop_loss_pct | DOUBLE | 止损百分比 |
| is_stop_trailing | BOOLEAN | 是否移动止损 |
| exit_reason | VARCHAR(255) | 平仓原因 |
| leverage | DOUBLE | 杠杆倍数 |
| stake_amount | DOUBLE | 投入金额 |

索引: `ix_trades_pair(pair)`, `ix_trades_is_open(is_open)`

---

## v19 变更记录 (2026-05-06)

| 改动 | 旧值 | 新值 | 目的 |
|------|------|------|------|
| Long止损 | -2.5/-3.0/-3.5% | **-6.0/-7.0/-8.0%** | 4X下价格需跌1.5%才触发，今天0笔会止损 |
| Short止损 | -2.0/-2.5/-3.0% | **-5.0/-6.0/-7.0%** | 同上 |
| 常规冷却 | 45min | **120min** | 止损后等更久 |
| 全局方向冷却 | 无 | **60min** | 任何币止损→该方向所有币60min不再入场 |
| 方向熔断 | 无 | **2笔同方向stoploss→暂停60min** | 防止连续猎杀 |
| 凌晨Long trailing_positive | 3% | **1.5%** | 更早追踪但4%offset才锁定 |
| 入场信号 | v18收紧版 | **恢复v18** | 信号照常进，靠止损+冷却控频 |

**数据依据**：今天11笔stop_loss价格只跌0.47%-0.78%，旧止损4X下价格0.625%就触发全部被猎杀；新止损4X下最低1.25%，今天0笔会触发。

---

## Bug修复记录

### close_date时区Bug (2026-04-29 ✅)
`close_date`和`order_filled_date`比真实时间少8小时。修复：所有时间字段统一用`datetime.now()`（返回CST本地时间），绕过OKX→ccxt时间戳转换链。历史数据已批量+8h修复。

### astimezone Bug (2026-04-27 ✅)
`safe_value_fallback`返回int而非datetime，直接调`.astimezone()`崩溃。修复：先判断类型。

### max()空序列Bug (2026-04-27 ✅)
`order_filled_utc`全为None时`max()`崩溃。修复：先收集到list再判断。

---

## 参数修改历史

| 日期 | 版本 | 修改 | 原因 |
|-----|------|------|------|
| 05-06 | v19 | 止损大幅放宽 Long-6/-7/-8%, Short-5/-6/-7% | 今天0笔止损会触发，旧止损全被猎杀 |
| 05-06 | v19 | 冷却45→120min, 全局方向冷却60min, 方向熔断 | 控频代替收紧入场 |
| 05-06 | v19 | 凌晨Long trailing_positive 3%→1.5% | 更早追踪但offset保持4%给空间 |
| 05-06 | v19 | 入场信号恢复v18, ATR%下限0.3% | 信号照常进 |
| 05-04 | v15 | EMA200斜率0.01→0.005, 15m RSI±5放宽, RSI动量shift(2)→(1), Long日间offset 3→4% | 横盘信号太严 |
| 05-04 | v14 | RSI<40→45/slowk<35→40(Long), RSI>60→55/slowk>40→35(Short), Short trailing 2%→1.5% | 增加入场机会 |
| 05-02 | v12 | 动态逆转, Long黑名单HYPE/TAO/TRUMP, ATR%下限0.8%, 7-9am冷却90min | 逆转自动化 |
| 04-29 | v6 | 时段方向逆转(0-8am S→L, 6-7am L→S, 10am-3pm S→L) | 时段胜率差异 |
| 04-27 | v3 | 白名单扩充20→22, ATR杠杆5X档, 止损放宽0.5% | 交易机会+止损过紧 |
| 04-26 | v2 | ATR动态止损替代固定止损 | 盈亏比失衡 |

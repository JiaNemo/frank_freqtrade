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

### 单Bot架构 (当前)
| 项目 | 值 |
|-----|-----|
| Service | freqtrade |
| Port | 8888 |
| Config | configLong.json |
| 策略 | RecoveryStrategyMulti |

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
OKX WebSocket may fail due to rate limits. Config中已设置 `ws_enabled: false`。重启后Bot进入STOPPED状态，需调用 `/api/v1/start` 恢复交易。

### Troubleshooting
- Bot STOPPED after restart: call `/api/v1/start`
- WebSocket errors: `journalctl -u freqtrade | grep ERROR`
- RateLimit (code 50011): wait or reduce whitelist size
- 已移除 incompatible pairs (2026-04-15): SATS, MATIC, MKR, FTM, STG

---

## RecoveryStrategyMulti (当前策略)

### 核心参数
| 参数 | 值 |
|-----|-----|
| timeframe | 5m |
| can_short | True |
| stoploss (Long/Short) | -3% / -3% |
| trailing_stop | True |
| trailing_stop_positive | **1.5%** |
| trailing_stop_positive_offset | **2%** |
| trailing_only_offset_is_reached | True |
| use_custom_stoploss | True |
| max_hours_before_force_entry | 12 |

### 方向风控
- **同方向最大持仓数**：`max_open_trades // 2 + 1`（当前 max_open=7，即同方向最多4笔）
- 超过限制时 `confirm_trade_entry` 返回 False，拒绝新入场
- 保证至少有 3 个 slot 给另一方向

### 趋势过滤 (EMA200)
- Long 只在价格 > EMA200 时入场（上升趋势做多）
- Short 只在价格 < EMA200 时入场（下降趋势做空）
- 避免逆势扎堆单一方向

### Entry 信号
| 方向 | 条件 |
|------|------|
| Long | RSI < 30, slowk < 30, atr% < 2.5, close > EMA200 |
| Short | RSI > 60, slowk > 40, atr% < 3.0, close < EMA200 |

### Exit 信号
| 方向 | 条件 |
|------|------|
| Long | fisher_rsi > 0.5 AND RSI > 70 |
| Short | fisher_rsi < -0.5 AND RSI > 80 |

### Minimal ROI (custom_exit)
| 持仓时长 | Long | Short |
|---------|------|-------|
| 0min | 2% | 1.5% |
| 30min | 5% | 2% |
| 60min | 8% | 1% |

### ATR 动态杠杆
| ATR分位数 | 波动状态 | 杠杆 |
|----------|---------|------|
| > 80% | 极高波动 | 2X |
| 60% - 80% | 高波动 | 3X |
| 40% - 60% | 中波动 | 4X |
| < 40% | 低波动 | 5X |

注：configLong.json 中 max_leverage=4，实际杠杆上限为4X

---

## Config Files

| 文件 | 位置 | 说明 |
|-----|------|------|
| configLong.json | 本地: `ai/config/`，服务器: `/data/freqtrade/` | **当前使用** |
| configShort.json | 服务器: `/data/freqtrade/` | 历史遗留，已废弃 |
| RecoveryStrategyMulti.py | 本地: 项目根目录，服务器: `/data/freqtrade/user_data/strategies/` | 当前策略 |

**注意**：配置文件中已删除 `minimal_roi` 和 `stoploss` 覆盖，让策略文件的值生效。

### configLong.json 关键参数
| 参数 | 值 |
|-----|-----|
| max_open_trades | 10 |
| stake_amount | 10 USDT |
| dry_run | false |
| trading_mode | futures |
| margin_mode | isolated |
| max_leverage | 4 |
| trailing_stop | true |
| trailing_stop_positive | 0.015 |
| trailing_stop_positive_offset | 0.02 |
| use_custom_stoploss | true |
| strategy | RecoveryStrategyMulti |
| ws_enabled | false |

### Blacklisted Pairs (2026-04-15)
17 high-loss pairs identified. Worst: NEIRO (14% winrate, -0.71 USDT), TURBO, BOME.
See `ai/config/config_blacklist_annotated.json` for full list.

---

## Scripts (ai/shell/)

| 脚本 | 说明 |
|-----|------|
| startbot.sh | Start bot via REST API |
| market_analysis.py | 市场分析，直接查询PostgreSQL |
| strategy_switch.py | 历史遗留（Multi策略已不需要手动切换） |

### market_analysis.py
- 直接查询PostgreSQL数据库（不通过API）
- 按 `ORDER BY id DESC` 获取最新交易
- 分别获取 Long/Short 最近10条 + 10-20条
- 胜率加权：60%×最近10条 + 40%×10-20条
- 评分算法：盈利基础分10分 + 盈亏差距分(上限40) + 胜率差距分(上限20) + trailing_stop惩罚

### 数据库查询方式
```bash
ssh root@47.108.169.101 "sudo -u postgres psql -d trading -c 'SELECT ... FROM trades ORDER BY id DESC LIMIT 10;'"
```

---

## Database Schema (PostgreSQL)

### trades table 关键字段
| 列 | 类型 | 说明 |
|----|------|------|
| id | SERIAL PK | |
| pair | VARCHAR(25) | 交易对 (BTC/USDT:USDT) |
| is_open | BOOLEAN | 是否持仓中 |
| is_short | BOOLEAN | 做空标记 |
| open_rate | DOUBLE | 开仓价格 |
| close_rate | DOUBLE | 平仓价格 |
| open_date | TIMESTAMP | 开仓时间 (naive, CST) |
| close_date | TIMESTAMP | 平仓时间 (naive, CST, **已修复时区bug**) |
| close_profit_abs | DOUBLE | 实际盈亏(USDT) |
| stop_loss_pct | DOUBLE | 止损百分比 |
| is_stop_trailing | BOOLEAN | 是否移动止损 |
| exit_reason | VARCHAR(255) | 平仓原因 |
| strategy | VARCHAR(100) | 策略名 |
| leverage | DOUBLE | 杠杆倍数 |
| stake_amount | DOUBLE | 投入金额 |
| amount | DOUBLE | 交易数量 |
| funding_fees | DOUBLE | 累计资金费率 |

索引: `ix_trades_pair(pair)`, `ix_trades_is_open(is_open)`

---

## Bug修复记录

### close_date 时区Bug (2026-04-24 ✅)

**问题**：`close_date` 多了8小时，`open_date` 正确。

**根因**：服务器CST时区 + `TIMESTAMP WITHOUT TIME ZONE` 列 + psycopg2对aware/naive datetime的不同处理 + `date_last_filled_utc` 属性错误地把naive DB值标记为UTC导致二次写入时+8h。

**修复**（两处）：
```python
# freqtrade/persistence/trade_model.py:946
self.close_date = (self.close_date or self._date_last_filled_utc or dt_now()).replace(tzinfo=None)

# freqtrade/freqtradebot.py:554
trade.close_date = trade.date_last_filled_utc.replace(tzinfo=None)
```

**数据库修复**：`UPDATE trades SET close_date = close_date - interval '8 hours' WHERE is_open = false AND close_date IS NOT NULL;` (524条)

**状态**：✅ 已修复，待观察新交易验证

### ATR杠杆调试日志 (2026-04-23 ✅)

**问题**：杠杆始终为2X。已在 `calculate_atr_percentile_leverage` 添加日志：`logger.info(f"{pair} ATR%: {atr_percent_current:.4f}, percentile: {percentile:.2f}, leverage: {leverage}")`

---

## 参数修改历史

| 日期 | 修改 | 原因 |
|-----|------|------|
| 04-23 | Long Entry atr% <3.0→<2.5 | 减少高波动入场 |
| 04-23 | Short Entry RSI >65→>60, slowk >55→>40 | 增加Short信号 |
| 04-23 | Short Exit RSI <30→>80 | 修正反向逻辑 |
| 04-23 | Long stoploss -2%→-3% | 降低止损率 |
| 04-23 | trailing_stop_positive 0.05→0.03, offset 0.08→0.04 | 更早锁定利润 |
| 04-24 | trailing_stop_positive 0.03→**0.015**, offset 0.04→**0.02** | 多数交易max偏移3-4%即回落，需更早追踪 |
| 04-24 | close_date 时区bug修复 | psycopg2 aware/naive处理差异 |

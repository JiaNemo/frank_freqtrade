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

## RecoveryStrategyMulti (当前策略 v5)

### 核心参数
| 参数 | 值 |
|-----|-----|
| timeframe | 5m |
| can_short | True |
| stoploss (Long/Short) | ATR动态(见下表) |
| trailing_stop | True |
| trailing_stop_positive | **1.5%** |
| trailing_stop_positive_offset | **2%(日间) / 4%(凌晨)** |
| trailing_only_offset_is_reached | True |
| use_custom_stoploss | True |
| max_hours_before_force_entry | 12 |

### 时段方向逆转 (v6, 2026-04-29)
- **0-5am + 8am CST**：Short信号自动转为Long入场（`populate_entry_trend`中S→L，排除6-7am）
- **6-7am CST**：Long信号自动转为Short入场（`populate_entry_trend`中L→S，优先级高于S→L）
- **10am-3pm CST**：Short信号自动转为Long入场（`populate_entry_trend`中S→L）
- 数据依据：0-5am Short胜率48%→Long 61%, 6-7am Long胜率34%→Short 68%, 10am-3pm Short胜率46%→Long 87%
- 参数：`no_short_before_hour=9`, `no_long_start_hour=6`, `no_long_end_hour=8`, `short_to_long_start=10`, `short_to_long_end=16`
- 日志标记：`X short -> long` 或 `X long -> short`
- **6-7am用elif避免与0-8am S→L冲突**：6-7am只做L→S，不走S→L

### 凌晨Trailing加宽 (v5, 2026-04-29)
- **0-8am**：Long trailing_stop_positive_offset = **4%**（`trailing_offset_night = 0.04`）
- **9am+**：Long trailing_stop_positive_offset = **2%**（默认值）
- Short保持不变：1.0%/1.5%
- 原因：凌晨震荡中30-55分钟就被trailing扫出，加宽到4%让利润跑更远

### 方向风控
- **同方向最大持仓数**：`max_open_trades // 2 + 1`（当前 max_open=7，即同方向最多4笔）
- 超过限制时 `confirm_trade_entry` 返回 False，拒绝新入场
- 保证至少有 3 个 slot 给另一方向

### 趋势过滤 (EMA200)
- Long 只在价格 > EMA200 时入场（上升趋势做多）
- Short 只在价格 < EMA200 时入场（下降趋势做空）
- 避免逆势扎堆单一方向

### Entry 信号 (v5, 2026-04-27)
| 方向 | 条件 | 旧值→新值 |
|------|------|----------|
| Long | RSI < 40, slowk < 35, atr% < 2.5, close > EMA200 | RSI<35→40, slowk<30→35 |
| Short | RSI > 60, slowk > 40, atr% < 2.0, close < EMA200 | RSI>70→60, slowk>50→40 |

### Cooldown
- 同pair+方向止损后cooldown **15min**（旧值30min，v5改为15min减少错过信号窗口）

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

### ATR 动态杠杆 (v4, 2026-04-27)
| ATR% | 波动状态 | 杠杆 |
|----------|---------|------|
| > 0.35 | 极高波动 | 2X |
| 0.25 - 0.35 | 高波动 | 3X |
| 0.15 - 0.25 | 低波动 | 4X |
| < 0.15 | 极低波动 | 5X |

注：configLong.json 中 max_leverage=5，策略根据ATR自动选择2-5X

### ATR 动态止损 (v4, 2026-04-27)
| ATR% | 波动状态 | Long止损 | Short止损 |
|------|---------|---------|----------|
| < 0.20 | 低波动 | -2.0% | -1.5% |
| 0.20 - 0.30 | 中波动 | -2.5% | -2.0% |
| > 0.30 | 高波动 | -3.0% | -2.5% |

fallback: Long -2.0%, Short -1.5%

**v4变更(2026-04-27)**：全线放宽0.5%，解决低波动止损过紧导致几分钟即触发的问题（4X下-1.5%价格变化即触发，放宽到-2.0%后需0.5%价格变化）

---

## Config Files

| 文件 | 位置 | 说明 |
|-----|------|------|
| configLong.json | 本地: `ai/config/`，服务器: `/data/freqtrade/` | **当前使用** |
| configShort.json | 服务器: `/data/freqtrade/` | 历史遗留，已废弃 |
| RecoveryStrategyMulti.py | 本地: `ai/strategies/`，服务器: `/data/freqtrade/user_data/strategies/` | 当前策略 |

**注意**：配置文件中已删除 `minimal_roi` 和 `stoploss` 覆盖，让策略文件的值生效。

### configLong.json 关键参数
| 参数 | 值 |
|-----|-----|
| max_open_trades | 10 |
| stake_amount | 10 USDT |
| dry_run | false |
| trading_mode | futures |
| margin_mode | isolated |
| max_leverage | 5 |
| trailing_stop | true |
| trailing_stop_positive | 0.015 |
| trailing_stop_positive_offset | 0.02 |
| use_custom_stoploss | true |
| strategy | RecoveryStrategyMulti |
| ws_enabled | false |

### Whitelist (2026-04-27, 20 pairs)
BTC, SOL, BCH, DOGE, AVAX, ARB, ENS, NEAR, BLUR, ENJ, PEOPLE, SHIB, ICP, ORDI, HYPE, TRUMP, BNB, TAO, LDO, COMP

### Blacklisted Pairs (2026-04-27, 26 pairs)
原17个(2026-04-15) + 新增9个历史亏损移除: XRP(-3.34), UNI(-1.23), INJ(-1.08), ATOM(-1.01), FIL(-0.92), ADA(-0.44), APT(-0.38), SUI(-0.31)
See `ai/config/config_blacklist_annotated.json` for original list.

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

### close_date/order_filled_date 时区Bug (2026-04-29 ✅ v4 最终修复)

**问题**：`close_date`和`order_filled_date`比真实时间少8小时（存的是UTC值而非CST）

**根因**：
1. `open_date`由`datetime.now()`设置（返回CST本地时间，正确）
2. `order_date`和`order_filled_date`由OKX时间戳转换：`dt_from_ts(ts).astimezone().replace(tzinfo=None)`
3. OKX原始`fillTime`是标准UTC epoch（正确），但ccxt传递的`lastTradeTimestamp`比OKX原始值恰好少8h（根因不明，可能ccxt内部处理差异）
4. `close_date`从`order_filled_date`派生，也少8h

**v4修复（2026-04-29）**：所有时间字段统一用`datetime.now()`（返回CST本地时间），绕过整个OKX→ccxt→freqtrade时间戳转换链：
- `trade_model.py` update_from_ccxt_object：`self.order_date = datetime.now()`，`self.order_filled_date = datetime.now()`
- `trade_model.py` close()方法：`self.close_date = datetime.now()`
- `freqtradebot.py` handle_onexchange_order：`trade.close_date = datetime.now()`
- `trade_model.py` _date_last_filled_utc：修复`max()`空序列bug（先收集list再判断）
- `trade_model.py` JSON restore：`datetime.fromtimestamp(ts, tz=UTC)` → `dt_from_ts(ts)`

**⚠️ 注意**：`dt_now()`返回UTC aware datetime（`datetime.now(UTC)`），不适合存为naive列。必须用`datetime.now()`（无timezone参数，返回本地CST）

**数据库修复**：历史数据批量+8h：`UPDATE orders SET order_filled_date = order_filled_date + interval '8 hours'`，`UPDATE trades SET close_date = close_date + interval '8 hours'`

**状态**：✅ v4已修复并验证，新交易时间戳正确（CST）

### ATR杠杆调试日志 (2026-04-23 ✅)

**问题**：杠杆始终为2X。已在 `calculate_atr_percentile_leverage` 添加日志：`logger.info(f"{pair} ATR%: {atr_percent_current:.4f}, percentile: {percentile:.2f}, leverage: {leverage}")`

### update_from_ccxt_object astimezone Bug (2026-04-27 ✅)

**问题**：Bot在处理NEAR/USDT:USDT委托单时崩溃：`AttributeError: 'int' object has no attribute 'astimezone'`

**根因**：`trade_model.py:227` 修复时区时，`safe_value_fallback(order, "lastTradeTimestamp")` 在OKX返回值存在时返回int（毫秒时间戳），而非default_value的datetime对象。直接对int调`.astimezone()`崩溃。

**修复**：先判断类型，int则先`dt_from_ts()`转datetime：
```python
last_ts = safe_value_fallback(order, "lastTradeTimestamp", default_value=dt_ts())
if isinstance(last_ts, int):
    self.order_filled_date = dt_from_ts(last_ts).astimezone().replace(tzinfo=None)
else:
    self.order_filled_date = last_ts.astimezone().replace(tzinfo=None)
```

### _date_last_filled_utc max()空序列Bug (2026-04-27 ✅)

**问题**：Bot重启时崩溃：`ValueError: max() arg is an empty sequence`

**根因**：trade 589的order是委托单（未成交），`select_filled_orders()`返回了orders但`order_filled_utc`全为None，generator为空，`max()`崩溃。

**修复**：先收集到list再判断：
```python
filled_dates = [o.order_filled_utc for o in orders if o.order_filled_utc]
if filled_dates:
    return max(filled_dates)
return None
```

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
| 04-24 | close_date 时区bug v3修复 | order_filled_utc假UTC问题，改用order_filled_date |
| 04-26 | Long stoploss -3%→ATR动态(-1.5%~-2.5%) | Long止损平均-0.452，需5.2次盈利抵1次止损，收紧止损 |
| 04-26 | Short stoploss -2%→ATR动态(-1.0%~-2.0%) | 与Long统一ATR动态止损逻辑 |
| 04-27 | 白名单16→20，移除8亏损币(XRP/UNI/INJ/ATOM/FIL/ADA/APT/SUI)，新增12币(BLUR/ENJ/PEOPLE/SHIB/ICP/ORDI/HYPE/TRUMP/BNB/TAO/LDO/COMP) | 扩充交易机会，移除历史亏损币 |
| 04-27 | ATR杠杆增加5X档(ATR%<0.15→5X)，max_leverage 4→5 | 极低波动时放大收益 |
| 04-27 | ATR动态止损全线放宽0.5%（Long: -1.5/-2.0/-2.5→-2.0/-2.5/-3.0, Short: -1.0/-1.5/-2.0→-1.5/-2.0/-2.5） | 低波动止损过紧，4X下-1.5%价格即触发，几分钟就被清出 |
| 04-27 | Entry信号放宽：Long RSI<35→40/slowk<30→35, Short RSI>70→60/slowk>50→40 | 交易偏少，20白名单币13个未触发，Short信号完全消失(RSI>70+EMA200过滤太严) |
| 04-27 | Cooldown 30min→15min | 止损后等太久错过信号窗口 |
| 04-29 | 时段方向锁：0-8am禁止Short入场(`no_short_before_hour=9`) | 0-8am Short胜率仅25%(04-28/29)，历史45%，凌晨震荡偏多Short被反复猎杀 |
| 04-29 | 凌晨Trailing加宽：0-8am Long offset 2%→4%(`trailing_offset_night=0.04`) | 凌晨震荡30-55分钟就被trailing扫出，加宽让利润跑更远 |
| 04-29 | 时段方向逆转v6：6-7am Long→Short(`no_long_start/end=6/8`), 10am-3pm Short→Long(`short_to_long_start/end=10/16`) | 6-7am Long胜率34%→Short 68%, 10am-3pm Short胜率46%→Long 87%，逆转挽回预计+3~4 USDT |

---

## 时段方向逆转验证 (2026-04-29, 排除4月18日)

### 整体对比（排除4月18日高杠杆异常日）
| 指标 | 含4月18日 | 排除4月18日 |
|------|---------|-----------|
| 总PnL | -18.50 | **+1.95** |
| 总交易数 | 635 | 575 |

排除4月18日（一天亏-20.45，50X/100X历史遗留），策略本身是盈利的。

### 时段方向胜率对比（排除4月18日）
| 时段 | Short胜率 | Long胜率 | 差值 | Short PnL | Long PnL | 逆转方向 | 逆转依据 |
|------|----------|---------|------|-----------|----------|---------|---------|
| 0-5am | 47.9% | **65.4%** | +17.5% | -1.91 | -0.25 | S→L ✅ | Short亏，Long只微亏 |
| 6-7am | **64.0%** | 39.3% | +24.7% | +1.60 | -2.05 | L→S ✅ | Long出血，Short盈利 |
| 8am | 25.0% | 47.4% | +22.4% | -0.73 | -1.37 | 不处理 | 仅23笔，样本太小 |
| 10am-3pm | 43.8% | **88.2%** | +44.4% | -4.30 | +5.02 | S→L ✅ | 差距全天最大 |
| 其他时段 | 52.4% | 70.1% | +17.7% | +2.58 | +3.36 | 不处理 | 双方均盈利 |

### 逐小时明细（排除4月18日）
| 小时(CST) | 交易数 | Short胜率 | Long胜率 | Short PnL | Long PnL | 优势方向 |
|-----------|-------|----------|---------|-----------|----------|---------|
| 0 | 12 | 60.0% | 57.1% | +0.20 | -0.25 | 持平 |
| 1 | 11 | 42.9% | 25.0% | -0.46 | -0.38 | 都差 |
| 2 | 28 | **75.0%** | **83.3%** | +0.79 | +0.43 | 都好 |
| 3 | 30 | 26.1% | 57.1% | -1.01 | -0.12 | Long |
| 4 | 23 | 46.2% | 50.0% | -1.48 | -0.50 | Long |
| 5 | 21 | 55.6% | **83.3%** | +0.05 | +0.58 | Long |
| 6 | 50 | **63.6%** | 41.2% | +0.85 | -1.07 | **Short** |
| 7 | 28 | **78.6%** | 36.4% | +0.75 | -0.98 | **Short** |
| 8 | 23 | 25.0% | 47.4% | -0.73 | -1.37 | 都差 |
| 10 | 34 | 66.7% | **92.3%** | -0.02 | +0.97 | **Long** |
| 11 | 16 | 33.3% | **100%** | -1.41 | +0.95 | **Long** |
| 12 | 27 | 23.1% | **71.4%** | -1.56 | +0.75 | **Long** |
| 13 | 28 | 50.0% | **90.0%** | -0.51 | +1.01 | **Long** |
| 14 | 11 | 28.6% | 75.0% | -0.45 | -0.05 | **Long** |
| 15 | 24 | 33.3% | **94.4%** | -0.35 | +1.39 | **Long** |

### 逆转模拟效果
| 场景 | 总PnL |
|------|-------|
| 实际（无逆转） | +1.95 |
| 模拟（三条逆转全开） | **+20.22** |
| 逆转增量 | **+18.27** |

### 逆转为何有效——根因分析
逆转能获利，不是因为freqtrade信号判断错误，而是因为**策略的入场信号和退出机制在不同时段有系统性偏差**。

**1. EMA200趋势过滤在震荡市中给出错误方向**
- Long信号：RSI<40 + slowk<35 + **close > EMA200**（上升趋势回调做多）
- Short信号：RSI>60 + slowk>40 + **close < EMA200**（下降趋势反弹做空）
- 凌晨0-5am市场是窄幅震荡，价格在EMA200附近来回穿越 → 价格刚跌破EMA200触发Short → 但只是震荡下沿，马上反弹 → Short被打止损
- **不是信号判断错，是EMA200在无趋势市场中失效——它把噪音当趋势**

**2. Trailing Stop对Short方向不友好**
- 0-8am的Short亏损83%来自trailing_stop_loss（30笔亏-2.21）
- 凌晨波动小但频繁假突破 → Short刚盈利1-2%就被trailing锁定 → 价格反弹 → 小亏出场
- Long方向加宽到4%后能跑更远，但Short的trailing没有时段调整

**3. 时段性市场结构差异**
| 时段 | 市场特征 | 策略假设 | 实际情况 |
|------|---------|---------|---------|
| 0-5am | 亚洲盘，流动性低，震荡偏多 | EMA200判断趋势 | 震荡中EMA200失效，Short被反复猎杀 |
| 6-7am | 早盘波动放大 | 趋势延续 | 长期趋势在开盘时被短期波动覆盖，Long被假突破止损 |
| 10am-3pm | 欧美交易时段，趋势性强 | Short在EMA200下方做空 | 白天即使短暂跌破EMA200也容易V型反转，Short被轧空 |

**核心本质**：策略用同一套参数全天运行，但市场在不同时段的微观结构完全不同。逆转不是在纠正"信号判断错误"，而是在**利用时段性的市场结构偏差**——同一个信号在不同时段的含义不同。

---

## 数据分析记录 (2026-04-26)

### 整体数据（539笔已平仓）
| 指标 | 数值 |
|------|------|
| 总盈亏 | -15.86 USDT |
| 总胜率 | 64.2% (346W / 190L) |
| 平均盈利 | +0.094 USDT |
| 平均亏损 | -0.255 USDT |
| 盈亏比 | 0.37:1 |

**核心问题：胜率64%仍亏损 → 盈亏比严重失衡**

### Long vs Short 对比
| 指标 | Long | Short |
|------|------|-------|
| 交易数 | 336 | 203 |
| 胜率 | 67.6% | 58.6% |
| 总盈亏 | **-14.96** | -0.89 |
| 平均亏损 | -0.319 | -0.169 |

**Long是亏损主因，Long止损平均-0.452是Short的1.7倍**

### 退出原因分析
| 退出原因 | 次数 | 总盈亏 |
|---------|------|--------|
| ROI | 155 | +13.88 |
| Exit Signal | 155 | +12.34 |
| Trailing Stop | 99 | -6.21 |
| **Stop Loss** | **96** | **-38.49** |

**止损是最大出血点：Long止损69次亏-31.18，Short止损27次亏-7.31**

### 最亏钱币种（历史累计）
ETH(-4.90), XRP(-3.34), LINK(-2.72), SEI(-1.69), UNI(-1.23), OP(-1.19)

### 最赚钱币种
BCH(+1.31), ARB(+1.01), DOGE(+0.86), ENJ(+0.81), BTC(+0.50)

### 近7天Short亏损严重
SEI(-1.03), APT(-0.71), AAVE(-0.46), LINK(-0.32), ATOM(-0.32)

### 时段分析
| 时段(CST) | 交易数 | 胜率 | 总盈亏 | 评价 |
|-----------|--------|------|--------|------|
| 8:00 | 42 | 26.2% | -18.98 | 极差 |
| 9:00 | 30 | 50.0% | -2.55 | 差 |
| 0:00 | 30 | 96.7% | +2.11 | 极好 |
| 20:00 | 19 | 89.5% | +1.85 | 好 |

**8:00 CST亏-18.98，占总亏损120%**

### 杠杆问题
50X/100X历史遗留亏损-19.0 USDT。当前ATR系统已改为2-5X，此问题不再出现。

### 待优化建议（未实施）
1. 🔴 8:00 CST时段限制入场（7-9点不入场或加大门槛）
2. 🔴 SEI/APT Short加入黑名单
3. 🟡 Short trailing_stop_positive_offset 2%→3%（让利润跑更远）
4. 🟡 大市值币（ETH/XRP/LINK）降低杠杆到2X或提高入场门槛
5. 🟡 时间衰减止损（持仓越久止损越紧）
6. 🟢 profit_target 0.2 USDT 扩大使用（平均+0.208，效果好）
7. 🟢 BTC/ETH Short适当增加权重（胜率75%+）

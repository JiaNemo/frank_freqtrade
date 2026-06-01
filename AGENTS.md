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
| 策略 | RecoveryStrategyMulti v24 (优化版) |

...

## RecoveryStrategyMulti v24 优化版 (当前策略)

### 核心思想
**熬到盈利** — 大幅放宽止损让交易撑住波动，trailing够宽让利润跑，用max_open_trades控频而非收紧入场信号。v24增加利润保护机制。

### 核心参数
| 参数 | 当前值 | 说明 |
|-----|--------|------|
| timeframe | 5m | |
| can_short | True | |
| max_open_trades | 7 | |
| max_hours_before_force_entry | 72 | 72小时强制平仓 |
| cooldown_minutes | 15min | 常规冷却 |
| profit_target_usdt | **已禁用** | 由trailing stop决定退出 |
| trailing_stop_positive | **0.025** | 盈利回撤2.5% (v24放宽) |
| trailing_stop_positive_offset | 0.05 | 盈利>5%启动trailing |
| max_leverage | 5 | 最大杠杆限制 |

### ATR 动态止损 (v23 反转逻辑)
| ATR% | 波动状态 | Long止损 | Short止损 | 说明 |
|------|---------|---------|---------|------|
| < 0.20 | 低波动 | -6% | -6% | 低波动宽止损避免噪音 |
| 0.20-0.30 | 中波动 | -5% | -5% | 中波动正常止损 |
| > 0.30 | 高波动 | -4% | -4% | 高波动紧止损控制风险 |

fallback: Long -5%, Short -5%

### ATR 动态杠杆 (v23 降低)
| ATR% | 波动状态 | 杠杆 |
|----------|---------|------|
| > 0.35 | 极高波动 | 3X |
| 0.25-0.35 | 高波动 | 4X |
| 0.15-0.25 | 低波动 | 4X |
| < 0.15 | 极低波动 | 5X |

### Entry 信号 (v23 收紧)
| 方向 | 条件 | 备注 |
|------|--------|------|
| Long | RSI < 40, slowk < 35, ATR% < 2.5, ATR% > 0.4, close > EMA200, 15m RSI < 55, rsi_rising(shift1), ema200_slope > 0.005 | 收紧入场 |
| Short | RSI > 65, slowk > 40, ATR% < 2.0, ATR% > 0.4, close < EMA200, 15m RSI > 45, rsi_falling(shift1), ema200_slope < -0.005 | 收紧入场 |

### ADX 趋势过滤 (v22保留)
| 条件 | 效果 |
|------|------|
| ADX > 25 + 做空 | **REJECT** - 趋势市场不做空 |
| ADX > 25 + Long + 无量确认 | **REJECT** - 谨慎做多 |
| ADX < 25 | 震荡市场 - 双向可操作 |

### RSI Divergence 检测 (v22保留)
| 模式 | 条件 | 效果 |
|------|------|------|
| 价格创新高 + RSI未跟随 | close > close.shift(5) + RSI < RSI.shift(5) | 潜在见顶信号 |
| 价格创新低 + RSI未跟随 | close < close.shift(5) + RSI > RSI.shift(5) | 潜在见底信号 |

### Exit 信号 (v24 放宽Long)
| 方向 | 条件 |
|------|--------|
| Long | fisher_rsi > 0.5 AND RSI > 65 |
| Short | fisher_rsi < -0.6 AND RSI < 30 |

### 利润保护机制 (v24 新增)
| 触发条件 | 退出原因 | 说明 |
|----------|----------|------|
| profit > 3% 且峰值回撤 > 4% | profit_drawdown_exit | 保护3%以上利润 |
| profit > 5% 且低于峰值80% | high_profit_protection | 高利润时更积极退出 |

### Trailing Stop (v24 调整)
| 参数 | 值 | 说明 |
|------|-----|------|
| trailing_stop_positive | **2.5%** | 盈利回撤2.5%即平仓 (v24放宽) |
| trailing_stop_positive_offset | 5% | 盈利>5%启动trailing |
| trailing_offset_day | 5% | 日间激活阈值 |
| trailing_offset_night | 5% | 夜间激活阈值 |
| trailing_offset_evening | 5% | 晚间激活阈值 |

### 冷却与风控
- 同pair+方向止损后cooldown **15min**
- **全局方向冷却**：任何币stoploss后，该方向所有币15min内不可入场
- **方向熔断**：连续2笔同方向stoploss后暂停该方向10min

### 黑名单
- Long: BLUR, ORDI, LDO, PEOPLE, ARB
- Short: LDO, BLUR, PEOPLE, ORDI, ARB

### 逆势交易过滤 (v22 核心改进)
| 过滤项 | 条件 | 逻辑 |
|--------|------|------|
| ADX趋势确认 | ADX > 25 | 强趋势不做空 |
| 成交量确认 | volume > volume_sma | 无量不追涨 |
| RSI背离 | 价格+RSI背离检测 | 潜在反转点预警 |
| BTC宏观确认 | EMA200斜率 | 全局方向参考 |

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
| max_leverage | 5 |
| trailing_stop | true |
| trailing_stop_positive | **0.025** |
| trailing_stop_positive_offset | 0.05 |
| use_custom_stoploss | true |
| strategy | RecoveryStrategyMulti |
| ws_enabled | false |

### Whitelist (22 pairs, BCH已移除)
ARB, NEAR, BLUR, ENJ, ICP, ORDI, HYPE, TAO, ZEC, PENDLE, WIF, RENDER, GRT, DOT, PYTH, JUP, ENA, ONDO, ARKM, CRV, DYDX, THETA

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
| 凌晨Long trailing_positive | 3% | **1.5%** | 更早追踪但6%offset才锁定 |
| Short日间trailing offset | 2% | **6%** | Trade901因2%太小刚盈利就被扫出，统一6%给足空间 |
| Long日间trailing offset | 4% | **6%** | 统一全时段全方向6% offset |
| 凌晨trailing offset | 4% | **6%** | 同上 |
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

### trailing_offset_evening未定义Bug (2026-05-24 ✅)
代码引用`trailing_offset_evening`和`trailing_offset_short_evening`但未定义。修复：添加变量定义。

### BCH-USD市场ID歧义Bug (2026-05-26 ✅)
OKX返回`safeMarket() requires a fourth argument for BCH-USD`警告，BCH有多个相同market id的市场。修复：从whitelist移除BCH。

---

## 参数修改历史

| 日期 | 版本 | 修改 | 原因 |
|-----|------|------|------|
| 05-26 | v24 | trailing_stop_positive 1.5%→2.5%, offset保持5% | 放宽trailing减少小额亏损 |
| 05-26 | v24 | Long exit: fisher>0.6→0.5, RSI>72→65 | 放宽exit条件增加主动退出 |
| 05-26 | v24 | 新增利润保护机制: profit_drawdown_exit, high_profit_protection | 保护已有利润 |
| 05-26 | v24 | 移除BCH (OKX市场ID歧义bug) | 修复get_tickers警告 |
| 05-24 | v23 Plan B | Long入场RSI <45→<40, slowk <40→<35; Short入场RSI >60→>65, slowk >35→>40 | 收紧入场提高信号质量 |
| 05-24 | v23 Plan B | max_leverage 7→5, ATR杠杆 4-7X→3-5X | 降低杠杆减少止损触发 |
| 05-24 | v23 Plan B | Trailing offset 8%→5%, positive 2.5%→1.5% | 更早激活trailing保护利润 |
| 05-24 | v23 Plan B | ATR止损反转: 低波动-4%→-6%, 高波动-6%→-4% | 低波动宽止损避免噪音 |
| 05-24 | v23 Plan B | Short exit RSI >82→<30 | 修复Short exit在超卖区域退出 |
| 05-24 | v23 Plan B | Bug修复: trailing_offset_evening未定义 | 代码bug |
| 05-06 | v19 | 止损大幅放宽 Long-6/-7/-8%, Short-5/-6/-7% | 今天0笔止损会触发，旧止损全被猎杀 |
| 05-06 | v19 | 冷却45→120min, 全局方向冷却60min, 方向熔断 | 控频代替收紧入场 |
| 05-06 | v19 | 凌晨Long trailing_positive 3%→1.5% | 更早追踪但offset保持4%给空间 |
| 05-12 | v21 | trailing_stop_positive 0.05→0.03, offset 0.04→0.025, max_hours 12→72, exit信号fisher>0.5→0.6, RSI 70→72/80→82 | 等趋势不等时间 |
| 05-13 | v22 | RSI Short >55→60, stoploss基础-6%→-10%, ATR档位更新 | 今日Short亏66% |
| 05-12 | v21a | cooldown 180→30min | 交易量太少，180min太长 |
| 05-06 | v19 | 入场信号恢复v18, ATR%下限0.3% | 信号照常进 |
| 05-04 | v15 | EMA200斜率0.01→0.005, 15m RSI±5放宽, RSI动量shift(2)→(1), Long日间offset 3→4% | 横盘信号太严 |
| 05-04 | v14 | RSI<40→45/slowk<35→40(Long), RSI>60→55/slowk>40→35(Short), Short trailing 2%→1.5% | 增加入场机会 |
| 05-02 | v12 | 动态逆转, Long黑名单HYPE/TAO/TRUMP, ATR%下限0.8%, 7-9am冷却90min | 逆转自动化 |
| 04-29 | v6 | 时段方向逆转(0-8am S→L, 6-7am L→S, 10am-3pm S→L) | 时段胜率差异 |
| 04-27 | v3 | 白名单扩充20→22, ATR杠杆5X档, 止损放宽0.5% | 交易机会+止损过紧 |
| 04-26 | v2 | ATR动态止损替代固定止损 | 盈亏比失衡 |

---

## custom_exit 改进方案 [v24 已实施 ✅]

### 问题
开始盈利 → 持仓一段时间后大亏。Peak利润回撤太多。

### 方案
实现`custom_exit`方法，基于峰谷回撤触发exit。

| 参数 | 值 | 含义 |
|-----|-----|------|
| X (监控阈值) | 3% | profit需达到3%才开始监控回撤 |
| Y (回撤触发 | 4% | 从峰值回撤4%触发exit |

### 实现代码
```python
if current_profit > 0.03:
    peak_profit = trade.calc_profit_ratio(trade.max_rate)
    if peak_profit - current_profit > 0.04:
        return "profit_drawdown_exit"

if current_profit > 0.05:
    if current_profit < peak_profit * 0.8:
        return "high_profit_protection"
```

### 数据支持 (500笔交易分析)
- 盈利交易75%分位数峰值：1.26%
- 盈利交易90%分位数峰值：2.94%
- 止损交易75%分位数峰值：2.79%
- 当前持仓峰值<1%，X=3%可过滤假信号

### 状态
- **已实施** ✅ - v24已部署到服务器 (2026-05-26)

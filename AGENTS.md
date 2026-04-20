# Freqtrade AGENTS.md

## AI Functionality (FreqAI)

All AI/ML trading functionality is in `freqtrade/freqai/`. Key components:
- `freqtrade/freqai/freqai_interface.py` - Main FreqAI interface
- `freqtrade/freqai/data_kitchen.py` - Data preprocessing and feature engineering
- `freqtrade/freqai/data_drawer.py` - Model persistence and history
- `freqtrade/freqai/prediction_models/` - ML model implementations (LSTM, XGBoost, LightGBM, etc.)
- `freqtrade/freqai/base_models/` - Base model classes
- `freqtrade/freqai/torch/` - PyTorch utilities
- `freqtrade/freqai/RL/` - Reinforcement learning components

FreqAI is enabled via `config.json` with `freqai: {..., "enabled": true}`.

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

## Entry Points

- `freqtrade` command → `freqtrade.main:main`
- FreqAI config schema → `build_helpers/extract_config_json_schema.py`

---

## Trading Bot Server (47.108.169.101)

### Server Info
- IP: 47.108.169.101
- SSH: `ssh root@47.108.169.101`
- Strategies: `/data/freqtrade/user_data/strategies/`
- API Auth: `freqtrade:freqtrade123`

### 双Bot架构 (Dual Bot)
两个Bot同时部署，通过API启停实现零 downtime 切换：

| Bot | Service | Port | Config | 策略 |
|-----|---------|------|--------|------|
| Long Bot | freqtrade | 8888 | config.json | RecoveryStrategyLong |
| Short Bot | freqtrade-short | 8889 | configShort2.json | RecoveryStrategyShort |

**共用同一数据库**，短期无冲突（一个跑一个停）。

### Bot Management
```bash
# systemctl 管理
ssh root@47.108.169.101 "systemctl restart freqtrade"
ssh root@47.108.169.101 "systemctl restart freqtrade-short"
ssh root@47.108.169.101 "systemctl status freqtrade freqtrade-short"

# API 管理 (切换使用)
curl -s -X POST http://127.0.0.1:8888/api/v1/start -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='
curl -s -X POST http://127.0.0.1:8888/api/v1/stop -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='
curl -s -X POST http://127.0.0.1:8889/api/v1/start -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='
curl -s -X POST http://127.0.0.1:8889/api/v1/stop -H 'Authorization: Basic ZnJlcXRyYWRlOmZyZXF0cmFkZTEyMw=='
```

### OKX WebSocket Configuration (Important)
OKX WebSocket connections may fail due to rate limits. To use REST API instead, add to exchange config:
```json
"exchange": {
    "name": "okx",
    "_ft_has_params": {
        "ws_enabled": false
    }
}
```
After config change, bot enters STOPPED state - must call `/api/v1/start` API to resume trading.

### Troubleshooting No Trades
- Bot in STOPPED state after restart: call `/api/v1/start`
- WebSocket errors: check `journalctl -u freqtrade | grep ERROR`
- RateLimit issues: OKX API rate limits (code 50011) - wait or reduce whitelist size
- Incompatible pairs removed 2026-04-15: SATS, MATIC, MKR, FTM, STG

### Start Bot (no SSH needed)
```bash
./ai/shell/startbot.sh
```

---

## Trading Strategies

### Available Strategies
- `RecoveryStrategyLong.py` - 做多策略 (RSI < 30 entry, trailing stop)
- `RecoveryStrategyShort.py` - 做空策略 (RSI > 60 entry)

### ATR 动态杠杆 (ATR Percentile Dynamic Leverage)
策略内置ATR分位数法动态杠杆，根据市场波动率自动调整：

| ATR分位数排名 | 波动状态 | 杠杆 |
|--------------|----------|------|
| > 80% | 极高波动 | 1X |
| 60% - 80% | 高波动 | 2X |
| 40% - 60% | 中波动 | 3X |
| < 40% | 低波动 | 4X |

**计算逻辑**：
1. 获取最近20根K线计算ATR
2. 计算ATR占价格百分比
3. 与历史ATR%分位数对比
4. 根据分位数确定杠杆档位

### Strategy Parameters
| Param | Long | Short |
|-------|------|-------|
| stoploss | -3% | -10% |
| trailing_stop_positive | 3% | 3% |
| trailing_stop_offset | 5% | 5% |
| minimal_roi | 5%/8%/10% | 1.5%/1%/0.5% |
| max_leverage | 4X | 4X | |

---

## Config Files (ai/config/)

### 配置文件说明
- `configLong.json` - Long策略专用配置 (minimal_roi: 2%/1.5%/0.5%, stoploss: -3%)
- `configShort.json` - Short策略专用配置 (minimal_roi: 2%/1.5%/1%, stoploss: -5%)
- `config.json` - 当前运行的配置文件 (由strategy_switch.py动态切换)
- `config_blacklist_annotated.json` - 黑名单分析

### 服务器配置文件位置
- `/data/freqtrade/config.json` - 当前运行配置
- `/data/freqtrade/configLong.json` - Long策略配置备份
- `/data/freqtrade/configShort.json` - Short策略配置备份
- `/data/freqtrade/user_data/strategies/` - 策略文件目录

### 策略切换逻辑
切换策略时，strategy_switch.py会:
1. 读取 `/tmp/market_analysis.json` 分析结果
2. 复制对应配置文件到 `/data/freqtrade/config.json`
3. 重启freqtrade服务
4. 调用 `/api/v1/start` 启动Bot

### Blacklisted Pairs (2026-04-15 Analysis)
17 high-loss pairs identified:
- Worst: NEIRO (14% winrate, -0.71 USDT), TURBO (-0.56 USDT), BOME (-0.54 USDT)
- See `ai/config/config_blacklist_annotated.json` for full analysis

---

## Scripts (ai/shell/)

- `startbot.sh` - Start bot via REST API
- `market_analysis.py` - 市场分析脚本，分析最近20条(60%权重)和50条(40%权重)交易
- `strategy_switch.py` - 策略自动切换脚本，读取分析结果切换策略并调用 `/api/v1/start` 启动Bot
- Strategy files deployed to server at `/data/freqtrade/user_data/strategies/`

### 自动策略切换流程
1. `scheduler.sh` 每30分钟运行 `trading_agents_bridge.py`
2. `market_analysis.py` 分析最近20条(权重60%)和50条(权重40%)交易
3. 生成 `/tmp/market_analysis.json` 包含推荐方向(LONG/SHORT/KEEP_CURRENT)
4. `strategy_switch.py` 读取分析结果，决定是否切换策略
5. 切换后调用 `/api/v1/start` 确保Bot进入RUNNING状态
6. 发送邮件通知

---

## Database Schema (PostgreSQL)

### trades table
Freqtrade uses PostgreSQL for trade persistence.

```sql
CREATE TABLE trades (
    id                      SERIAL PRIMARY KEY,
    exchange                VARCHAR(25) NOT NULL,
    pair                   VARCHAR(25) NOT NULL,
    base_currency           VARCHAR(25),
    stake_currency         VARCHAR(25),
    is_open               BOOLEAN NOT NULL,
    fee_open              DOUBLE PRECISION NOT NULL,
    fee_open_cost         DOUBLE PRECISION,
    fee_open_currency     VARCHAR(25),
    fee_close             DOUBLE PRECISION NOT NULL,
    fee_close_cost        DOUBLE PRECISION,
    fee_close_currency    VARCHAR(25),
    open_rate             DOUBLE PRECISION NOT NULL,
    open_rate_requested   DOUBLE PRECISION,
    open_trade_value     DOUBLE PRECISION,
    close_rate            DOUBLE PRECISION,
    close_rate_requested  DOUBLE PRECISION,
    realized_profit       DOUBLE PRECISION,
    close_profit          DOUBLE PRECISION,
    close_profit_abs     DOUBLE PRECISION,
    stake_amount         DOUBLE PRECISION NOT NULL,
    max_stake_amount     DOUBLE PRECISION,
    amount               DOUBLE PRECISION NOT NULL,
    amount_requested     DOUBLE PRECISION,
    open_date            TIMESTAMP NOT NULL,
    close_date           TIMESTAMP,
    stop_loss            DOUBLE PRECISION,
    stop_loss_pct         DOUBLE PRECISION,
    initial_stop_loss    DOUBLE PRECISION,
    initial_stop_loss_pct DOUBLE PRECISION,
    is_stop_trailing     BOOLEAN NOT NULL,
    max_rate             DOUBLE PRECISION,
    min_rate             DOUBLE PRECISION,
    exit_reason          VARCHAR(255),
    exit_order_status    VARCHAR(100),
    strategy             VARCHAR(100),
    enter_tag            VARCHAR(255),
    timeframe             INTEGER,
    trading_mode         TRADING_MODE,
    amount_precision    DOUBLE PRECISION,
    price_precision     DOUBLE PRECISION,
    precision_mode      INTEGER,
    precision_mode_price INTEGER,
    contract_size       DOUBLE PRECISION,
    leverage            DOUBLE PRECISION,
    is_short            BOOLEAN NOT NULL,
    liquidation_price   DOUBLE PRECISION,
    interest_rate      DOUBLE PRECISION NOT NULL,
    funding_fees       DOUBLE PRECISION,
    funding_fee_running DOUBLE PRECISION,
    record_version     INTEGER NOT NULL
);

COMMENT ON TABLE trades IS 'Freqtrade交易记录表';
COMMENT ON COLUMN trades.exchange IS '交易所名称（如 binance、bybit）';
COMMENT ON COLUMN trades.pair IS '交易对（如 BTC/USDT:USDT）';
COMMENT ON COLUMN trades.base_currency IS '基础货币（如 BTC）';
COMMENT ON COLUMN trades.stake_currency IS '计价货币（如 USDT）';
COMMENT ON COLUMN trades.is_open IS '是否持仓中（true=开仓，false=已平仓';
COMMENT ON COLUMN trades.fee_open IS '开仓费率（百分比，如 0.001 = 0.1%';
COMMENT ON COLUMN trades.fee_open_cost IS '开仓实际手续费金额';
COMMENT ON COLUMN trades.close_rate IS '实际平仓价格';
COMMENT ON COLUMN trades.realized_profit IS '已实现盈亏（含手续费';
COMMENT ON COLUMN trades.stop_loss_pct IS '止损百分比（相对于开仓价';
COMMENT ON COLUMN trades.initial_stop_loss_pct IS '开仓时初始止损百分比';
COMMENT ON COLUMN trades.is_stop_trailing IS '是否启用移动止损';
COMMENT ON COLUMN trades.exit_reason IS '平仓原因（stop_loss、roi、exit_signal、force_exit_time_XXh_no_profit 等';
COMMENT ON COLUMN trades.trading_mode IS '交易模式（spot、futures、margin）';
COMMENT ON COLUMN trades.leverage IS '杠杆倍数（现货=1，合约 >1';
COMMENT ON COLUMN trades.funding_fees IS '累计资金费率（正值=支付，负值=收取';

CREATE INDEX ix_trades_pair ON trades(pair);
CREATE INDEX ix_trades_is_open ON trades(is_open);
```

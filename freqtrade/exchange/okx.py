import logging
from datetime import timedelta

import ccxt

from freqtrade.constants import BuySell
from freqtrade.enums import CandleType, MarginMode, PriceType, TradingMode
from freqtrade.exceptions import (
    DDosProtection,
    OperationalException,
    RetryableOrderError,
    TemporaryError,
)
from freqtrade.exchange import Exchange
from freqtrade.exchange.common import API_RETRY_COUNT, retrier
from freqtrade.exchange.exchange_types import CcxtOrder, FtHas
from freqtrade.util import dt_now, dt_ts


logger = logging.getLogger(__name__)

# OKX API返回的时间戳是北京时间 (UTC+8)
# 需要减去8小时来纠正时区偏差
OKX_TIMEZONE_OFFSET_MS = 8 * 60 * 60 * 1000


class Okx(Exchange):
    """Okx exchange class.

    Contains adjustments needed for Freqtrade to work with this exchange.
    """

    _ft_has: FtHas = {
        "ohlcv_candle_limit": 100,  # Warning, special case with data prior to X months
        "stoploss_order_types": {"limit": "limit"},
        "stoploss_on_exchange": True,
        "stoploss_query_requires_stop_flag": True,
        "trades_has_history": False,  # Endpoint doesn't have a "since" parameter
        "ws_enabled": True,
    }
    _ft_has_futures: FtHas = {
        "tickers_have_quoteVolume": False,
        "stop_price_type_field": "slTriggerPxType",
        "stop_price_type_value_mapping": {
            PriceType.LAST: "last",
            PriceType.MARK: "mark",
            PriceType.INDEX: "index",
        },
        "stoploss_blocks_assets": False,
        "ws_enabled": True,
    }

    _supported_trading_mode_margin_pairs: list[tuple[TradingMode, MarginMode]] = [
        (TradingMode.SPOT, MarginMode.NONE),
        # (TradingMode.MARGIN, MarginMode.CROSS),
        # (TradingMode.FUTURES, MarginMode.CROSS),
        (TradingMode.FUTURES, MarginMode.ISOLATED),
    ]

    net_only = True

    _ccxt_params: dict = {"options": {"brokerId": "ffb5405ad327SUDE"}}

    def ohlcv_candle_limit(
        self, timeframe: str, candle_type: CandleType, since_ms: int | None = None
    ) -> int:
        """
        Exchange ohlcv candle limit
        OKX has the following behaviour:
        * spot and futures:
            * 300 candles for regular candles
        * mark and premium-index:
            * 300 candles for up-to-date data
            * 100 candles for historic data
        * additional data:
            * 100 candles for additional candles
        :param timeframe: Timeframe to check
        :param candle_type: Candle-type
        :param since_ms: Starting timestamp
        :return: Candle limit as integer
        """
        if candle_type in (CandleType.FUTURES, CandleType.SPOT):
            return 300

        return super().ohlcv_candle_limit(timeframe, candle_type, since_ms)

    @retrier
    def additional_exchange_init(self) -> None:
        """
        Additional exchange initialization logic.
        .api will be available at this point.
        Must be overridden in child methods if required.
        """
        try:
            if self.trading_mode == TradingMode.FUTURES and not self._config["dry_run"]:
                accounts = self._api.fetch_accounts()
                self._log_exchange_response("fetch_accounts", accounts)
                if len(accounts) > 0:
                    self.net_only = accounts[0].get("info", {}).get("posMode") == "net_mode"
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Error in additional_exchange_init due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    def _get_posSide(self, side: BuySell, reduceOnly: bool):
        if self.net_only:
            return "net"
        if not reduceOnly:
            # Enter
            return "long" if side == "buy" else "short"
        else:
            # Exit
            return "long" if side == "sell" else "short"

    def _get_params(
        self,
        side: BuySell,
        ordertype: str,
        leverage: float,
        reduceOnly: bool,
        time_in_force: str = "GTC",
    ) -> dict:
        params = super()._get_params(
            side=side,
            ordertype=ordertype,
            leverage=leverage,
            reduceOnly=reduceOnly,
            time_in_force=time_in_force,
        )
        if self.trading_mode == TradingMode.FUTURES and self.margin_mode:
            params["tdMode"] = self.margin_mode.value
            params["posSide"] = self._get_posSide(side, reduceOnly)
        return params

    def __fetch_leverage_already_set(self, pair: str, leverage: float, side: BuySell) -> bool:
        try:
            res_lev = self._api.fetch_leverage(
                symbol=pair,
                params={
                    "mgnMode": self.margin_mode.value,
                    "posSide": self._get_posSide(side, False),
                },
            )
            self._log_exchange_response("get_leverage", res_lev)
            already_set = all(float(x["lever"]) == leverage for x in res_lev["data"])
            return already_set

        except ccxt.BaseError:
            # Assume all errors as "not set yet"
            return False

    @retrier
    def _lev_prep(self, pair: str, leverage: float, side: BuySell, accept_fail: bool = False):
        if self.trading_mode != TradingMode.SPOT and self.margin_mode is not None:
            try:
                res = self._api.set_leverage(
                    leverage=leverage,
                    symbol=pair,
                    params={
                        "mgnMode": self.margin_mode.value,
                        "posSide": self._get_posSide(side, False),
                    },
                )
                self._log_exchange_response("set_leverage", res)

            except ccxt.DDoSProtection as e:
                raise DDosProtection(e) from e
            except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
                already_set = self.__fetch_leverage_already_set(pair, leverage, side)
                if not already_set:
                    raise TemporaryError(
                        f"Could not set leverage due to {e.__class__.__name__}. Message: {e}"
                    ) from e
            except ccxt.BaseError as e:
                raise OperationalException(e) from e

    def get_max_pair_stake_amount(self, pair: str, price: float, leverage: float = 1.0) -> float:
        if self.trading_mode == TradingMode.SPOT:
            return float("inf")  # Not actually inf, but this probably won't matter for SPOT

        if pair not in self._leverage_tiers:
            return float("inf")

        pair_tiers = self._leverage_tiers[pair]
        last_max_notional = pair_tiers[-1]["maxNotional"]
        if last_max_notional is None:
            return float("inf")
        return last_max_notional / leverage

    def _get_stop_params(self, side: BuySell, ordertype: str, stop_price: float) -> dict:
        params = super()._get_stop_params(side, ordertype, stop_price)
        if self.trading_mode == TradingMode.FUTURES and self.margin_mode:
            params["tdMode"] = self.margin_mode.value
            params["posSide"] = self._get_posSide(side, True)
        return params

    def _convert_stop_order(self, pair: str, order_id: str, order: CcxtOrder) -> CcxtOrder:
        if order.get("status", "open") == "closed":
            real_order_id = order.get("info", {}).get("ordId")
            if real_order_id is not None:
                # Once a order triggered, we fetch the regular followup order.
                order_reg = self.fetch_order(real_order_id, pair)
                self._log_exchange_response("fetch_stoploss_order1", order_reg)
                order_reg["id_stop"] = order_reg["id"]
                order_reg["id"] = order_id
                order_reg["type"] = "stoploss"
                order_reg["status_stop"] = "triggered"
                return order_reg
        order = self._order_contracts_to_amount(order)
        order["type"] = "stoploss"
        return order

    @retrier
    def fetch_order(self, order_id: str, pair: str, params: dict | None = None) -> CcxtOrder:
        """
        Fetch a single order with timezone correction for OKX.
        OKX API返回的时间戳是北京时间 (UTC+8)，需要减去8小时来纠正时区偏差。
        """
        if self._config["dry_run"]:
            return self.fetch_dry_run_order(order_id)
        if params is None:
            params = {}
        try:
            if not self.exchange_has("fetchOrder"):
                return self.fetch_order_emulated(order_id, pair, params)
            order = self._api.fetch_order(order_id, pair, params=params)
            self._log_exchange_response("fetch_order", order)
            order = self._order_contracts_to_amount(order)
            order = self._adjust_timestamps_for_okx_single(order)
            return order
        except ccxt.OrderNotFound as e:
            raise RetryableOrderError(
                f"Order not found (pair: {pair} id: {order_id}). Message: {e}"
            ) from e
        except ccxt.InvalidOrder as e:
            raise InvalidOrderException(
                f"Tried to get an invalid order (pair: {pair} id: {order_id}). Message: {e}"
            ) from e
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Could not get order due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    @retrier(retries=API_RETRY_COUNT)
    def fetch_stoploss_order(
        self, order_id: str, pair: str, params: dict | None = None
    ) -> CcxtOrder:
        if self._config["dry_run"]:
            return self.fetch_dry_run_order(order_id)

        try:
            params1 = {"stop": True}
            order_reg = self._api.fetch_order(order_id, pair, params=params1)
            self._log_exchange_response("fetch_stoploss_order", order_reg)
            order_reg = self._order_contracts_to_amount(order_reg)
            order_reg = self._adjust_timestamps_for_okx_single(order_reg)
            return self._convert_stop_order(pair, order_id, order_reg)
        except (ccxt.OrderNotFound, ccxt.InvalidOrder):
            pass
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Could not get order due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

        return self._fetch_stop_order_fallback(order_id, pair)

    def _fetch_stop_order_fallback(self, order_id: str, pair: str) -> CcxtOrder:
        params2 = {"stop": True, "ordType": "conditional"}
        for method in (
            self._api.fetch_open_orders,
            self._api.fetch_closed_orders,
            self._api.fetch_canceled_orders,
        ):
            try:
                orders = method(pair, params=params2)
                orders = self._adjust_timestamps_for_okx(orders)
                orders_f = [order for order in orders if order["id"] == order_id]
                if orders_f:
                    order = orders_f[0]
                    return self._convert_stop_order(pair, order_id, order)
            except (ccxt.OrderNotFound, ccxt.InvalidOrder):
                pass
            except ccxt.DDoSProtection as e:
                raise DDosProtection(e) from e
            except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
                raise TemporaryError(
                    f"Could not get order due to {e.__class__.__name__}. Message: {e}"
                ) from e
            except ccxt.BaseError as e:
                raise OperationalException(e) from e
        raise RetryableOrderError(f"StoplossOrder not found (pair: {pair} id: {order_id}).")

    def _fetch_orders_emulate(self, pair: str, since_ms: int) -> list[CcxtOrder]:
        orders = []

        orders = self._api.fetch_closed_orders(pair, since=since_ms)
        if since_ms < dt_ts(dt_now() - timedelta(days=6, hours=23)):
            # Regular fetch_closed_orders only returns 7 days of data.
            # Force usage of "archive" endpoint, which returns 3 months of data.
            params = {"method": "privateGetTradeOrdersHistoryArchive"}
            orders_hist = self._api.fetch_closed_orders(pair, since=since_ms, params=params)
            orders.extend(orders_hist)

        orders_open = self._api.fetch_open_orders(pair, since=since_ms)
        orders.extend(orders_open)

        return self._adjust_timestamps_for_okx(orders)

    @retrier(retries=0)
    def _fetch_orders(
        self, pair: str, since: datetime, params: dict | None = None
    ) -> list[CcxtOrder]:
        """
        Fetch orders for a pair, with timezone correction for OKX.
        OKX API返回的时间戳是北京时间 (UTC+8)，需要减去8小时来纠正时区偏差。
        """
        if self._config["dry_run"]:
            return []

        try:
            since_ms = int((since.timestamp() - 10) * 1000)

            if self.exchange_has("fetchOrders"):
                if not params:
                    params = {}
                try:
                    orders: list[CcxtOrder] = self._api.fetch_orders(
                        pair, since=since_ms, params=params
                    )
                except ccxt.NotSupported:
                    orders = self._fetch_orders_emulate(pair, since_ms)
            else:
                orders = self._fetch_orders_emulate(pair, since_ms)
            self._log_exchange_response("fetch_orders", orders)
            orders = [self._order_contracts_to_amount(o) for o in orders]
            orders = self._adjust_timestamps_for_okx(orders)
            return orders
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Could not fetch orders due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    def _adjust_timestamps_for_okx(self, orders: list[CcxtOrder]) -> list[CcxtOrder]:
        """
        OKX API返回的时间戳是北京时间 (UTC+8)，但ccxt将其当作UTC处理。
        此方法将时间戳减去8小时以纠正时区偏差。

        :param orders: OKX返回的订单列表
        :return: 修正后的订单列表
        """
        timestamp_fields = ["timestamp", "lastTradeTimestamp", "datetime"]

        for order in orders:
            for field in timestamp_fields:
                if field in order and order[field] is not None:
                    order[field] = order[field] - OKX_TIMEZONE_OFFSET_MS

        return orders

    def _adjust_timestamps_for_okx_single(self, order: CcxtOrder) -> CcxtOrder:
        """
        OKX API返回的时间戳是北京时间 (UTC+8)，但ccxt将其当作UTC处理。
        此方法将时间戳减去8小时以纠正时区偏差（适用于单个订单）。

        :param order: OKX返回的单个订单
        :return: 修正后的订单
        """
        timestamp_fields = ["timestamp", "lastTradeTimestamp", "datetime"]

        for field in timestamp_fields:
            if field in order and order[field] is not None:
                order[field] = order[field] - OKX_TIMEZONE_OFFSET_MS

        return order


class Myokx(Okx):
    """MyOkx exchange class.
    Minimal adjustment to disable futures trading for the EU subsidiary of Okx
    """

    _supported_trading_mode_margin_pairs: list[tuple[TradingMode, MarginMode]] = [
        (TradingMode.SPOT, MarginMode.NONE),
    ]


class Okxus(Okx):
    """Okxus exchange class.
    Minimal adjustment to disable futures trading for the US subsidiary of Okx
    """

    _supported_trading_mode_margin_pairs: list[tuple[TradingMode, MarginMode]] = [
        (TradingMode.SPOT, MarginMode.NONE),
    ]

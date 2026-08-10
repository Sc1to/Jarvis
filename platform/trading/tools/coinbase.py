"""
Coinbase Advanced Trade API wrapper.
Uses coinbase-advanced-py SDK for JWT authentication (EC private key).
Credentials in trading_config: coinbase_api_key_name, coinbase_api_private_key.
"""
import logging

from coinbase.rest import RESTClient

log = logging.getLogger(__name__)


class CoinbaseClient:
    """Thin wrapper around coinbase-advanced-py RESTClient."""

    def __init__(self, api_key_name: str, api_private_key: str):
        self._client = RESTClient(
            api_key=api_key_name,
            api_secret=api_private_key,
        )

    # ── Auth ──────────────────────────────────────────────────────────────────

    def check_auth(self) -> bool:
        try:
            self._client.get_unix_time()
            return True
        except Exception as e:
            log.error("Coinbase auth check failed: %s", e)
            return False

    # ── Account ───────────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        response = self._client.get_accounts()
        return [a.to_dict() for a in response.accounts]

    # ── Market data ───────────────────────────────────────────────────────────

    def get_product(self, product_id: str) -> dict:
        """product_id: 'BTC-USD', 'ETH-USD', etc."""
        return self._client.get_product(product_id).to_dict()

    def get_best_bid_ask(self, product_ids: list[str]) -> dict[str, dict]:
        """Returns {product_id: pricebook_dict}."""
        r = self._client.get_best_bid_ask(product_ids=product_ids)
        return {p.product_id: p.to_dict() for p in r.pricebooks}

    def list_products(self, product_type: str = "SPOT") -> list[dict]:
        """List all tradeable products of given type."""
        r = self._client.get_products(product_type=product_type)
        return [p.to_dict() for p in r.products]

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,       # 'BUY' | 'SELL'
        base_size: str,  # string amount in base asset, e.g. '0.01'
    ) -> dict:
        r = self._client.market_order(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
        )
        if r.success:
            return r.success_response.to_dict()
        return {"error": str(r.error_response)}

    def get_order(self, order_id: str) -> dict:
        return self._client.get_order(order_id).order.to_dict()

    def cancel_orders(self, order_ids: list[str]) -> list[dict]:
        r = self._client.cancel_orders(order_ids=order_ids)
        return [res.to_dict() for res in r.results]

    def list_open_orders(self, product_id: str | None = None) -> list[dict]:
        kwargs = {"order_status": "OPEN"}
        if product_id:
            kwargs["product_id"] = product_id
        r = self._client.list_orders(**kwargs)
        return [o.to_dict() for o in r.orders]

    def list_filled_orders(self, product_id: str | None = None, limit: int = 50) -> list[dict]:
        kwargs = {"order_status": "FILLED", "limit": limit}
        if product_id:
            kwargs["product_id"] = product_id
        r = self._client.list_orders(**kwargs)
        return [o.to_dict() for o in r.orders]

    # ── Historical data ───────────────────────────────────────────────────────

    def get_candles(
        self,
        product_id: str,
        granularity: str,
        start: str,
        end: str,
    ) -> list[dict]:
        """
        Fetch OHLCV candles.
        granularity: 'ONE_MINUTE' | 'FIVE_MINUTE' | 'FIFTEEN_MINUTE' | 'ONE_HOUR' | 'ONE_DAY'
        start / end: Unix timestamp strings (seconds since epoch).
        Returns list of candle dicts sorted oldest-first.
        """
        r = self._client.get_candles(
            product_id=product_id,
            start=start,
            end=end,
            granularity=granularity,
        )
        candles = [c.to_dict() for c in r.candles]
        return sorted(candles, key=lambda c: c.get("start", 0))

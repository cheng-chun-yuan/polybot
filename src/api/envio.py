import asyncio
import json
import httpx
from typing import Optional, Callable, Awaitable, AsyncIterator
from contextlib import asynccontextmanager

import websockets
from websockets.client import WebSocketClientProtocol

from src.config import ENVIO_GRAPHQL_URL, logger
from src.storage.models import Trade


# Convert HTTP URL to WebSocket URL
def get_ws_url(http_url: str) -> str:
    return http_url.replace("https://", "wss://").replace("http://", "ws://")


# GraphQL subscription for new trades
TRADES_SUBSCRIPTION = """
subscription WatchTrades {
  RawTrade(order_by: { timestamp: desc }, limit: 1) {
    id
    orderHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    timestamp
    transactionHash
    logIndex
  }
}
"""

# GraphQL query to fetch trades by maker addresses (fallback)
TRADES_BY_MAKER_QUERY = """
query GetTradesByMaker($addresses: [String!]!, $since: Int!) {
  RawTrade(
    where: {
      maker: { _in: $addresses },
      timestamp: { _gt: $since }
    },
    order_by: { timestamp: desc },
    limit: 100
  ) {
    id
    orderHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    timestamp
    transactionHash
    logIndex
  }
}
"""

# Query for recent trades (for testing)
RECENT_TRADES_QUERY = """
query GetRecentTrades($limit: Int!) {
  RawTrade(
    order_by: { timestamp: desc },
    limit: $limit
  ) {
    id
    orderHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    timestamp
    transactionHash
    logIndex
  }
}
"""

# Query for trades by a specific maker (for whale detection)
TRADES_BY_SINGLE_MAKER_QUERY = """
query GetTradesByAddress($address: String!, $limit: Int!) {
  RawTrade(
    where: { maker: { _eq: $address } },
    order_by: { timestamp: asc },
    limit: $limit
  ) {
    id
    orderHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    timestamp
    transactionHash
    logIndex
  }
}
"""


def parse_trade(item: dict) -> Optional[Trade]:
    """Parse trade data into Trade object."""
    try:
        return Trade(
            id=item["id"],
            order_hash=item["orderHash"],
            maker=item["maker"].lower(),
            taker=item["taker"].lower(),
            maker_asset_id=item["makerAssetId"],
            taker_asset_id=item["takerAssetId"],
            maker_amount_filled=int(item["makerAmountFilled"]),
            taker_amount_filled=int(item["takerAmountFilled"]),
            timestamp=int(item["timestamp"]),
            tx_hash=item.get("transactionHash") or item.get("txHash", ""),
            log_index=int(item["logIndex"]),
        )
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse trade: {e}")
        return None


class EnvioSubscription:
    """WebSocket subscription to ENVIO GraphQL for real-time trade updates."""

    def __init__(
        self,
        url: str = ENVIO_GRAPHQL_URL,
        reconnect_interval: float = 5.0,
        max_reconnect_attempts: int = 10,
    ):
        self.http_url = url
        self.ws_url = get_ws_url(url)
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._seen_ids: set[str] = set()  # Dedup trades

    async def connect(self) -> bool:
        """Establish WebSocket connection."""
        try:
            # graphql-ws protocol
            self._ws = await websockets.connect(
                self.ws_url,
                subprotocols=["graphql-transport-ws"],
                ping_interval=30,
                ping_timeout=10,
            )

            # Send connection init
            await self._ws.send(json.dumps({"type": "connection_init"}))

            # Wait for connection ack
            response = await asyncio.wait_for(self._ws.recv(), timeout=10)
            data = json.loads(response)

            msg_type = data.get("type")
            if msg_type == "connection_ack":
                logger.info("ENVIO WebSocket connected")
                return True
            elif msg_type == "ping":
                # Respond to ping with pong
                await self._ws.send(json.dumps({"type": "pong"}))
                # Wait for actual ack
                response = await asyncio.wait_for(self._ws.recv(), timeout=10)
                data = json.loads(response)
                if data.get("type") == "connection_ack":
                    logger.info("ENVIO WebSocket connected")
                    return True

            logger.error(f"Unexpected connection response: {data}")
            return False

        except Exception as e:
            logger.error(f"Failed to connect to ENVIO WebSocket: {e}")
            return False

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        logger.info("ENVIO WebSocket disconnected")

    async def subscribe(
        self,
        on_trade: Callable[[Trade], Awaitable[None]],
        address_filter: Optional[Callable[[], Awaitable[set[str]]]] = None,
    ) -> None:
        """
        Subscribe to trades and call on_trade for each new trade.

        Args:
            on_trade: Async callback for each trade
            address_filter: Optional async function that returns set of addresses to filter
        """
        self._running = True
        reconnect_attempts = 0

        while self._running:
            try:
                if not self._ws or getattr(self._ws, 'closed', True):
                    if not await self.connect():
                        reconnect_attempts += 1
                        if reconnect_attempts >= self.max_reconnect_attempts:
                            logger.error("Max reconnect attempts reached")
                            break
                        await asyncio.sleep(self.reconnect_interval)
                        continue

                # Reset reconnect counter on successful connection
                reconnect_attempts = 0

                # Send subscription
                await self._ws.send(json.dumps({
                    "id": "1",
                    "type": "subscribe",
                    "payload": {
                        "query": TRADES_SUBSCRIPTION,
                    },
                }))

                # Listen for messages
                async for message in self._ws:
                    if not self._running:
                        break

                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "next":
                        payload = data.get("payload", {})
                        trades_data = payload.get("data", {}).get("RawTrade", [])

                        for trade_data in trades_data:
                            trade_id = trade_data.get("id")

                            # Dedup
                            if trade_id in self._seen_ids:
                                continue
                            self._seen_ids.add(trade_id)

                            # Keep seen_ids from growing too large
                            if len(self._seen_ids) > 10000:
                                self._seen_ids = set(list(self._seen_ids)[-5000:])

                            trade = parse_trade(trade_data)
                            if not trade:
                                continue

                            # Filter by addresses if provided
                            if address_filter:
                                tracked = await address_filter()
                                if trade.maker not in tracked:
                                    continue

                            # Call handler
                            try:
                                await on_trade(trade)
                            except Exception as e:
                                logger.error(f"Trade handler error: {e}")

                    elif msg_type == "error":
                        logger.error(f"Subscription error: {data}")
                        break

                    elif msg_type == "complete":
                        logger.info("Subscription completed")
                        break

            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
            except Exception as e:
                logger.error(f"Subscription error: {e}")

            # Reconnect
            if self._running:
                await self.disconnect()
                await asyncio.sleep(self.reconnect_interval)

    def stop(self) -> None:
        """Stop the subscription loop."""
        self._running = False


class EnvioClient:
    """Client for ENVIO GraphQL API (trade detection via indexer)."""

    def __init__(self, url: str = ENVIO_GRAPHQL_URL, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self.subscription = EnvioSubscription(url)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self.subscription.stop()
        await self.subscription.disconnect()

    async def _execute_query(
        self,
        query: str,
        variables: dict,
    ) -> Optional[dict]:
        """Execute a GraphQL query."""
        try:
            client = await self._get_client()
            response = await client.post(
                self.url,
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                return None

            return data.get("data")

        except httpx.HTTPError as e:
            logger.error(f"ENVIO request failed: {e}")
            return None

    async def get_trades_by_makers(
        self,
        addresses: list[str],
        since_timestamp: int,
    ) -> list[Trade]:
        """Fetch trades where maker is in the given addresses list."""
        if not addresses:
            return []

        addresses = [addr.lower() for addr in addresses]

        data = await self._execute_query(
            TRADES_BY_MAKER_QUERY,
            {"addresses": addresses, "since": since_timestamp},
        )

        if not data or "RawTrade" not in data:
            return []

        trades = []
        for item in data["RawTrade"]:
            trade = parse_trade(item)
            if trade:
                trades.append(trade)

        return trades

    async def get_recent_trades(self, limit: int = 10) -> list[Trade]:
        """Fetch most recent trades (for testing/debugging)."""
        data = await self._execute_query(
            RECENT_TRADES_QUERY,
            {"limit": limit},
        )

        if not data or "RawTrade" not in data:
            return []

        trades = []
        for item in data["RawTrade"]:
            trade = parse_trade(item)
            if trade:
                trades.append(trade)

        return trades

    async def get_trader_history(self, address: str, limit: int = 10) -> list[Trade]:
        """Fetch trade history for a specific wallet (oldest first)."""
        data = await self._execute_query(
            TRADES_BY_SINGLE_MAKER_QUERY,
            {"address": address.lower(), "limit": limit},
        )

        if not data or "RawTrade" not in data:
            return []

        trades = []
        for item in data["RawTrade"]:
            trade = parse_trade(item)
            if trade:
                trades.append(trade)

        return trades

    async def is_new_whale(self, address: str, min_usd: float = 10000, max_trades: int = 5) -> tuple[bool, list[Trade]]:
        """
        Check if a trader qualifies as a "new whale".
        Returns (is_whale, trades) where is_whale is True if:
        - Trader has <= max_trades total trades
        - ALL trades are >= min_usd
        """
        trades = await self.get_trader_history(address, limit=max_trades + 1)

        if not trades:
            return False, []

        # If they have more than max_trades, not a "new" whale
        if len(trades) > max_trades:
            return False, trades[:max_trades]

        # Check if ALL trades are >= min_usd
        all_whale_trades = all(t.usdc_value >= min_usd for t in trades)

        return all_whale_trades, trades

    async def health_check(self) -> bool:
        """Check if ENVIO endpoint is reachable."""
        try:
            await self.get_recent_trades(limit=1)
            return True
        except Exception as e:
            logger.error(f"ENVIO health check failed: {e}")
            return False


# Global client instance
envio_client = EnvioClient()

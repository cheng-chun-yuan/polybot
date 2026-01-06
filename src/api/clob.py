import httpx
from typing import Optional, Any

from src.config import CLOB_API_URL, logger


class ClobClient:
    """Client for Polymarket CLOB API (order book, pricing)."""

    def __init__(self, base_url: str = CLOB_API_URL, timeout: float = 5.0):
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_midpoint_price(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/midpoint",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            data = response.json()
            return float(data.get("mid", 0))
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Failed to fetch midpoint for {token_id}: {e}")
            return None

    async def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get market price for buy or sell side."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/price",
                params={
                    "token_id": token_id,
                    "side": side.upper(),
                },
            )
            response.raise_for_status()
            data = response.json()
            return float(data.get("price", 0))
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Failed to fetch price for {token_id}: {e}")
            return None

    async def get_order_book(self, token_id: str) -> Optional[dict[str, Any]]:
        """Get full order book for a token."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/book",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch order book for {token_id}: {e}")
            return None

    async def get_spread(self, token_id: str) -> Optional[dict[str, float]]:
        """Get bid-ask spread for a token."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/spreads",
                json=[{"token_id": token_id}],
            )
            response.raise_for_status()
            data = response.json()
            if token_id in data:
                return {"spread": float(data[token_id])}
            return None
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch spread for {token_id}: {e}")
            return None


# Global client instance
clob_client = ClobClient()

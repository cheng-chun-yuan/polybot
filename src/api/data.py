import httpx
from typing import Optional, Any

from src.config import DATA_API_URL, logger


class DataClient:
    """Client for Polymarket Data API (trades, positions, profiles)."""

    def __init__(self, base_url: str = DATA_API_URL, timeout: float = 10.0):
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

    async def get_user_trades(
        self,
        address: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get recent trades for a user."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/trades",
                params={
                    "user": address.lower(),
                    "limit": limit,
                    "offset": offset,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch trades for {address}: {e}")
            return []

    async def get_user_positions(self, address: str) -> list[dict[str, Any]]:
        """Get open positions for a user."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/positions",
                params={"user": address.lower()},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch positions for {address}: {e}")
            return []

    async def get_trader_profile(self, address: str) -> Optional[dict[str, Any]]:
        """Get trader profile and stats."""
        try:
            client = await self._get_client()
            # Try to get pseudonym/profile info from activity
            response = await client.get(
                "/activity",
                params={
                    "user": address.lower(),
                    "limit": 1,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Get total value
            value_response = await client.get(
                "/total-value",
                params={"user": address.lower()},
            )

            profile = {
                "address": address.lower(),
                "total_value": 0,
            }

            if value_response.status_code == 200:
                profile["total_value"] = value_response.json().get("totalValue", 0)

            return profile

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch profile for {address}: {e}")
            return None

    async def get_top_holders(
        self,
        token_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top token holders for a market."""
        try:
            client = await self._get_client()
            response = await client.get(
                "/top-holders",
                params={
                    "tokenId": token_id,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch top holders for {token_id}: {e}")
            return []


# Global client instance
data_client = DataClient()

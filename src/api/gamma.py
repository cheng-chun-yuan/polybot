import httpx
from typing import Optional
from functools import lru_cache

from src.config import GAMMA_API_URL, logger
from src.storage.models import Market


class GammaClient:
    """Client for Polymarket Gamma API (market metadata)."""

    def __init__(self, base_url: str = GAMMA_API_URL, timeout: float = 10.0):
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: dict[str, Market] = {}

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

    async def get_market_by_token(self, token_id: str) -> Optional[Market]:
        """Fetch market metadata by CLOB token ID."""
        # Check cache first
        if token_id in self._cache:
            return self._cache[token_id]

        try:
            client = await self._get_client()
            response = await client.get(
                "/markets",
                params={"clob_token_ids": token_id},
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                logger.warning(f"No market found for token {token_id}")
                return None

            market_data = data[0]
            # Parse outcomes and token IDs
            outcomes = market_data.get("outcomes", [])
            clob_token_ids = market_data.get("clobTokenIds", [])

            # Handle string format (sometimes returned as JSON string)
            if isinstance(outcomes, str):
                import json as json_lib
                outcomes = json_lib.loads(outcomes)
            if isinstance(clob_token_ids, str):
                import json as json_lib
                clob_token_ids = json_lib.loads(clob_token_ids)

            # Ensure token IDs are strings
            clob_token_ids = [str(tid) for tid in clob_token_ids]

            logger.debug(f"Market {market_data.get('question', '')[:50]}: outcomes={outcomes}, tokens={clob_token_ids}")

            market = Market(
                condition_id=market_data.get("conditionId", ""),
                question=market_data.get("question", "Unknown Market"),
                slug=market_data.get("slug", ""),
                outcomes=outcomes if outcomes else ["Yes", "No"],
                outcome_prices=market_data.get("outcomePrices", ["0.5", "0.5"]),
                clob_token_ids=clob_token_ids,
                category=market_data.get("category"),
            )

            # Cache the result
            self._cache[token_id] = market
            for tid in market.clob_token_ids:
                self._cache[tid] = market

            return market

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch market for token {token_id}: {e}")
            return None

    async def get_market_by_condition(self, condition_id: str) -> Optional[Market]:
        """Fetch market metadata by condition ID."""
        if condition_id in self._cache:
            return self._cache[condition_id]

        try:
            client = await self._get_client()
            response = await client.get(
                "/markets",
                params={"condition_id": condition_id},
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            market_data = data[0]
            market = Market(
                condition_id=market_data.get("conditionId", condition_id),
                question=market_data.get("question", "Unknown Market"),
                slug=market_data.get("slug", ""),
                outcomes=market_data.get("outcomes", ["Yes", "No"]),
                outcome_prices=market_data.get("outcomePrices", ["0.5", "0.5"]),
                clob_token_ids=market_data.get("clobTokenIds", []),
                category=market_data.get("category"),
            )

            self._cache[condition_id] = market
            return market

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch market {condition_id}: {e}")
            return None

    def get_outcome_name(self, market: Market, token_id: str) -> str:
        """Get the outcome name (Yes/No) for a given token ID."""
        try:
            # Try exact match first
            if token_id in market.clob_token_ids:
                idx = market.clob_token_ids.index(token_id)
                return market.outcomes[idx] if idx < len(market.outcomes) else "Unknown"

            # Try string comparison (in case of type mismatch)
            for i, tid in enumerate(market.clob_token_ids):
                if str(tid) == str(token_id):
                    return market.outcomes[i] if i < len(market.outcomes) else "Unknown"

            # For binary markets, try to determine from price
            # If we can't find it, use first outcome as default for binary markets
            if len(market.outcomes) == 2:
                logger.debug(f"Token {token_id} not in {market.clob_token_ids}, defaulting to first outcome")
                return market.outcomes[0]

            return "Unknown"
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to get outcome name: {e}")
            return "Unknown"

    def clear_cache(self) -> None:
        self._cache.clear()

    async def get_all_categories(self) -> list[dict]:
        """Fetch all available categories from /tags API."""
        try:
            client = await self._get_client()
            response = await client.get("/tags")
            response.raise_for_status()
            return response.json()  # [{id, label, slug}, ...]
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch categories: {e}")
            return []


# Global client instance
gamma_client = GammaClient()

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    chat_id: int
    username: Optional[str] = None
    created_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class TrackedWallet:
    id: int
    chat_id: int
    wallet_address: str
    label: Optional[str] = None
    min_usd: float = 0.0
    is_active: bool = True
    created_at: Optional[datetime] = None


@dataclass
class ProcessedTrade:
    trade_id: str
    wallet_address: str
    processed_at: Optional[datetime] = None


@dataclass
class Trade:
    """Represents a trade from ENVIO."""
    id: str
    order_hash: str
    maker: str
    taker: str
    maker_asset_id: str
    taker_asset_id: str
    maker_amount_filled: int
    taker_amount_filled: int
    timestamp: int
    tx_hash: str
    log_index: int

    @property
    def trade_id(self) -> str:
        return f"{self.tx_hash}-{self.log_index}"

    @property
    def side(self) -> str:
        # If makerAssetId == 0 -> Maker paid USDC -> BUY
        return "BUY" if self.maker_asset_id == "0" else "SELL"

    @property
    def outcome_token_id(self) -> str:
        return self.taker_asset_id if self.side == "BUY" else self.maker_asset_id

    @property
    def usdc_amount(self) -> int:
        return self.maker_amount_filled if self.side == "BUY" else self.taker_amount_filled

    @property
    def token_amount(self) -> int:
        return self.taker_amount_filled if self.side == "BUY" else self.maker_amount_filled

    @property
    def price(self) -> float:
        if self.token_amount == 0:
            return 0.0
        # USDC has 6 decimals, outcome tokens have 6 decimals
        return self.usdc_amount / self.token_amount

    @property
    def usdc_value(self) -> float:
        # Convert from 6 decimals
        return self.usdc_amount / 1_000_000


@dataclass
class Market:
    """Market metadata from Gamma API."""
    condition_id: str
    question: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[str]
    clob_token_ids: list[str]
    category: Optional[str] = None


@dataclass
class EnrichedTrade:
    """Trade with market metadata."""
    trade: Trade
    market: Optional[Market] = None
    outcome: Optional[str] = None


@dataclass
class Subscription:
    """User subscription settings for trade alerts."""
    chat_id: int
    min_usd: float = 0.0
    max_usd: Optional[float] = None
    side: Optional[str] = None  # "BUY", "SELL", or None for both
    categories: list[str] = None  # Market category filter (Crypto, Politics, Sports, etc.)
    # Insider detection (new traders with large first trades)
    insider_alert: bool = False
    insider_min_usd: float = 10000.0
    insider_max_trades: int = 3
    # Whale tracking (all trades above threshold)
    whale_alert: bool = False
    whale_min_usd: float = 10000.0

    def __post_init__(self):
        if self.categories is None:
            self.categories = []

    def matches_trade(self, trade: 'Trade', market: Optional['Market'] = None) -> tuple[bool, str]:
        """Check if trade matches subscription filters. Returns (match, reason)."""
        # Min USD filter
        if trade.usdc_value < self.min_usd:
            return False, f"amount ${trade.usdc_value:.2f} < ${self.min_usd}"

        # Max USD filter
        if self.max_usd and trade.usdc_value > self.max_usd:
            return False, f"amount ${trade.usdc_value:.2f} > ${self.max_usd}"

        # Side filter
        if self.side and trade.side != self.side.upper():
            return False, f"side {trade.side} != {self.side}"

        # Category filter
        if self.categories and market:
            market_cat = (market.category or "").lower()
            if not any(cat.lower() == market_cat for cat in self.categories):
                return False, f"category {market_cat} not in {self.categories}"

        return True, "matched"

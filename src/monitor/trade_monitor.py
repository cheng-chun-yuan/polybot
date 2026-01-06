import asyncio
from typing import Callable, Optional, Awaitable

from src.config import POLL_INTERVAL, logger
from src.storage.database import db
from src.storage.models import Trade, EnrichedTrade
from src.api.envio import envio_client
from src.api.gamma import gamma_client


class TradeMonitor:
    """
    Monitors tracked wallets for new trades via ENVIO WebSocket subscription.
    Also detects insider traders (new traders with large first trades) and whale trades (all large trades).
    Enriches trades with market metadata and triggers notifications.
    Falls back to polling if subscription fails.
    """

    def __init__(
        self,
        poll_interval: int = POLL_INTERVAL,
        on_trade: Optional[Callable[[EnrichedTrade, list[tuple[int, Optional[str], float]]], Awaitable[None]]] = None,
        on_insider: Optional[Callable[[Trade, 'Market', str, list[Trade]], Awaitable[None]]] = None,
        on_whale: Optional[Callable[[EnrichedTrade], Awaitable[None]]] = None,
    ):
        self.poll_interval = poll_interval
        self.on_trade = on_trade
        self.on_insider = on_insider  # New traders with large first trades
        self.on_whale = on_whale  # All large trades
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._tracked_addresses: set[str] = set()
        self._checked_insiders: set[str] = set()  # Avoid re-checking same address for insider

    async def start(self) -> None:
        """Start the monitoring via WebSocket subscription."""
        if self._running:
            logger.warning("Trade monitor already running")
            return

        self._running = True

        # Load initial tracked addresses
        await self._refresh_tracked_addresses()

        # Start subscription task
        self._task = asyncio.create_task(self._subscription_loop())
        logger.info("Trade monitor started (WebSocket subscription mode)")

    async def stop(self) -> None:
        """Stop the monitoring."""
        self._running = False
        envio_client.subscription.stop()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Trade monitor stopped")

    async def _refresh_tracked_addresses(self) -> None:
        """Refresh the set of tracked addresses from database."""
        addresses = await db.get_all_tracked_addresses()
        self._tracked_addresses = set(addr.lower() for addr in addresses)
        logger.debug(f"Tracking {len(self._tracked_addresses)} unique addresses")

    async def _get_tracked_addresses(self) -> set[str]:
        """Get current tracked addresses (called by subscription filter)."""
        # Refresh periodically
        await self._refresh_tracked_addresses()
        return self._tracked_addresses

    async def _subscription_loop(self) -> None:
        """Main subscription loop with fallback to polling."""
        while self._running:
            try:
                # Try WebSocket subscription (no filter - we handle filtering ourselves)
                logger.info("Starting WebSocket subscription...")
                await envio_client.subscription.subscribe(
                    on_trade=self._handle_trade,
                    address_filter=None,  # Process ALL trades for whale detection
                )
            except Exception as e:
                logger.error(f"Subscription failed: {e}")

            if self._running:
                logger.warning("Subscription ended, will retry in 10s...")
                await asyncio.sleep(10)

    async def _handle_trade(self, trade: Trade) -> None:
        """Handle a new trade from subscription."""
        # Check if already processed
        if await db.is_trade_processed(trade.trade_id):
            return

        # Mark as processed early to avoid duplicates
        await db.mark_trade_processed(trade.trade_id, trade.maker)

        # 1. Check if from tracked wallet -> notify watchers
        watchers = await db.get_users_tracking_wallet(trade.maker)
        if watchers:
            logger.info(f"New trade from tracked wallet {trade.maker[:10]}... - {trade.side} ${trade.usdc_value:.0f}")
            enriched = await self._enrich_trade(trade)

            if self.on_trade:
                try:
                    await self.on_trade(enriched, watchers)
                except Exception as e:
                    logger.error(f"Notification callback failed: {e}")

        # 2. Check for insider detection (new traders with large first trades)
        if trade.usdc_value >= 1000 and self.on_insider:
            await self._check_insider(trade)

        # 3. Check for whale tracking (all large trades)
        if trade.usdc_value >= 1000 and self.on_whale:
            enriched = await self._enrich_trade(trade)
            try:
                await self.on_whale(enriched)
            except Exception as e:
                logger.error(f"Whale callback failed: {e}")

    async def _check_insider(self, trade: Trade) -> None:
        """Check if trade is from a new insider (first trades all large) and notify subscribers."""
        # Skip if we've already checked this address
        if trade.maker in self._checked_insiders:
            return

        self._checked_insiders.add(trade.maker)

        # Limit cache size
        if len(self._checked_insiders) > 10000:
            self._checked_insiders = set(list(self._checked_insiders)[-5000:])

        try:
            # Check if this is a new insider (API call)
            is_insider, trade_history = await envio_client.is_new_whale(
                trade.maker,
                min_usd=10000,  # Default, will be checked per-user in callback
                max_trades=3,
            )

            if is_insider and trade_history:
                logger.info(f"🕵️ New insider detected: {trade.maker[:10]}... ({len(trade_history)} trades)")

                # Enrich with market data
                market = await gamma_client.get_market_by_token(trade.outcome_token_id)
                outcome = None
                if market:
                    outcome = gamma_client.get_outcome_name(market, trade.outcome_token_id)

                # Trigger insider callback
                if self.on_insider:
                    await self.on_insider(trade, market, outcome, trade_history)

        except Exception as e:
            logger.error(f"Insider check failed for {trade.maker[:10]}: {e}")

    async def _enrich_trade(self, trade: Trade) -> EnrichedTrade:
        """Add market metadata to a trade."""
        market = await gamma_client.get_market_by_token(trade.outcome_token_id)

        outcome = None
        if market:
            outcome = gamma_client.get_outcome_name(market, trade.outcome_token_id)

        return EnrichedTrade(
            trade=trade,
            market=market,
            outcome=outcome,
        )

    def add_tracked_address(self, address: str) -> None:
        """Add an address to track (called when user adds wallet)."""
        self._tracked_addresses.add(address.lower())

    def remove_tracked_address(self, address: str) -> None:
        """Remove an address from tracking."""
        self._tracked_addresses.discard(address.lower())

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def tracked_count(self) -> int:
        return len(self._tracked_addresses)


# Global monitor instance (initialized in main.py)
trade_monitor: Optional[TradeMonitor] = None

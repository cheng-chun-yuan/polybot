#!/usr/bin/env python3
"""
Test script to mock the trade monitor flow.
Run with: python test_monitor.py
"""

import asyncio
import random
from datetime import datetime, timezone

from src.config import logger
from src.storage.database import db
from src.storage.models import Trade, EnrichedTrade, Market
from src.api.gamma import gamma_client


# Mock wallet addresses to track
MOCK_WALLETS = [
    ("0x1234567890abcdef1234567890abcdef12345678", "whale1"),
    ("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", "smartmoney"),
    ("0x9999888877776666555544443333222211110000", "degen"),
]

# Mock markets
MOCK_MARKETS = [
    Market(
        condition_id="0xabc123",
        question="Will Bitcoin reach $100k by end of 2025?",
        slug="bitcoin-100k-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.65", "0.35"],
        clob_token_ids=["token_yes_btc", "token_no_btc"],
        category="Crypto",
    ),
    Market(
        condition_id="0xdef456",
        question="Will Trump win 2024 election?",
        slug="trump-2024",
        outcomes=["Yes", "No"],
        outcome_prices=["0.52", "0.48"],
        clob_token_ids=["token_yes_trump", "token_no_trump"],
        category="Politics",
    ),
    Market(
        condition_id="0x789ghi",
        question="Will ETH flip BTC market cap in 2025?",
        slug="eth-flip-btc-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.12", "0.88"],
        clob_token_ids=["token_yes_flip", "token_no_flip"],
        category="Crypto",
    ),
]


def generate_mock_trade(wallet_address: str) -> Trade:
    """Generate a random mock trade."""
    market = random.choice(MOCK_MARKETS)
    is_buy = random.choice([True, False])
    outcome_idx = random.randint(0, 1)

    usdc_amount = random.randint(100, 50000) * 1_000_000  # 6 decimals
    price = float(market.outcome_prices[outcome_idx])
    token_amount = int(usdc_amount / price)

    if is_buy:
        maker_asset_id = "0"  # USDC
        taker_asset_id = market.clob_token_ids[outcome_idx]
        maker_amount = usdc_amount
        taker_amount = token_amount
    else:
        maker_asset_id = market.clob_token_ids[outcome_idx]
        taker_asset_id = "0"  # USDC
        maker_amount = token_amount
        taker_amount = usdc_amount

    tx_hash = f"0x{''.join(random.choices('0123456789abcdef', k=64))}"

    return Trade(
        id=f"{tx_hash}-{random.randint(0, 100)}",
        order_hash=f"0x{''.join(random.choices('0123456789abcdef', k=64))}",
        maker=wallet_address.lower(),
        taker=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
        maker_asset_id=maker_asset_id,
        taker_asset_id=taker_asset_id,
        maker_amount_filled=maker_amount,
        taker_amount_filled=taker_amount,
        timestamp=int(datetime.now(timezone.utc).timestamp()),
        tx_hash=tx_hash,
        log_index=random.randint(0, 100),
    )


def get_mock_market(token_id: str) -> Market | None:
    """Get mock market by token ID."""
    for market in MOCK_MARKETS:
        if token_id in market.clob_token_ids:
            return market
    return None


def format_trade_console(enriched: EnrichedTrade, label: str | None = None) -> str:
    """Format trade for console output."""
    trade = enriched.trade
    market = enriched.market

    emoji = "🟢" if trade.side == "BUY" else "🔴"
    trader = label or trade.maker[:10] + "..."
    outcome = enriched.outcome or "Unknown"
    question = market.question[:50] + "..." if market and len(market.question) > 50 else (market.question if market else "Unknown")

    return f"""
{emoji} TRADE DETECTED
├─ Trader:  {trader}
├─ Action:  {trade.side} {outcome}
├─ Amount:  ${trade.usdc_value:,.0f}
├─ Price:   {trade.price * 100:.1f}%
├─ Market:  {question}
└─ Tx:      {trade.tx_hash[:20]}...
"""


async def on_trade_event(enriched: EnrichedTrade, watchers: list[tuple[int, str | None]]) -> None:
    """Callback when trade is detected."""
    for chat_id, label in watchers:
        print(format_trade_console(enriched, label))


async def mock_trade_generator(interval: float = 3.0):
    """Generate mock trades at regular intervals."""
    print(f"\n⏳ Generating mock trades every {interval}s...\n")

    while True:
        # Pick random tracked wallet
        wallet, label = random.choice(MOCK_WALLETS)

        # Generate trade
        trade = generate_mock_trade(wallet)

        # Get market for enrichment
        market = get_mock_market(trade.outcome_token_id)
        outcome = None
        if market:
            try:
                idx = market.clob_token_ids.index(trade.outcome_token_id)
                outcome = market.outcomes[idx]
            except (ValueError, IndexError):
                pass

        enriched = EnrichedTrade(trade=trade, market=market, outcome=outcome)

        # Simulate notification
        await on_trade_event(enriched, [(0, label)])

        await asyncio.sleep(interval)


async def test_with_mock_data():
    """Test the monitor with mock data."""
    print("=" * 60)
    print("  POLYBOT TEST - Mock Trade Monitor")
    print("=" * 60)

    # Initialize database
    await db.connect()

    # Add mock wallets to tracking
    print("\n📝 Adding mock wallets to track:")
    for address, label in MOCK_WALLETS:
        await db.add_user(chat_id=12345, username="test_user")
        success = await db.add_tracked_wallet(12345, address, label)
        status = "✓" if success else "already exists"
        print(f"   {label}: {address[:10]}... [{status}]")

    # Show tracked wallets
    wallets = await db.get_tracked_wallets(12345)
    print(f"\n👀 Tracking {len(wallets)} wallets")

    # Run mock generator
    try:
        await mock_trade_generator(interval=2.0)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopped by user")
    finally:
        await db.close()


async def test_real_envio():
    """Test with real ENVIO connection (no mock)."""
    from src.api.envio import envio_client
    from src.monitor.trade_monitor import TradeMonitor

    print("=" * 60)
    print("  POLYBOT TEST - Real ENVIO Connection")
    print("=" * 60)

    # Initialize database
    await db.connect()

    # Add mock wallets
    print("\n📝 Adding wallets to track:")
    for address, label in MOCK_WALLETS:
        await db.add_user(chat_id=12345, username="test_user")
        await db.add_tracked_wallet(12345, address, label)
        print(f"   {label}: {address[:10]}...")

    # Health check
    print("\n🔍 Checking ENVIO connection...")
    if await envio_client.health_check():
        print("   ✓ ENVIO is healthy")
    else:
        print("   ✗ ENVIO connection failed")
        return

    # Fetch some recent trades
    print("\n📊 Recent trades on Polymarket:")
    trades = await envio_client.get_recent_trades(limit=5)
    for t in trades:
        print(f"   {t.side} ${t.usdc_value:,.0f} by {t.maker[:10]}...")

    # Start monitor with console callback
    async def console_callback(enriched: EnrichedTrade, watchers: list):
        for _, label in watchers:
            print(format_trade_console(enriched, label))

    monitor = TradeMonitor(on_trade=console_callback)

    print("\n🚀 Starting trade monitor (WebSocket)...")
    print("   Press Ctrl+C to stop\n")

    try:
        await monitor.start()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping...")
        await monitor.stop()
    finally:
        await envio_client.close()
        await db.close()


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "mock"

    if mode == "real":
        asyncio.run(test_real_envio())
    else:
        asyncio.run(test_with_mock_data())

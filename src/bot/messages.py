from typing import Optional
from src.storage.models import EnrichedTrade, TrackedWallet


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def short_address(address: str) -> str:
    """Shorten wallet address for display."""
    return f"{address[:6]}...{address[-4:]}"


def format_usd(amount: float) -> str:
    """Format USD amount."""
    if amount >= 1000:
        return f"${amount:,.0f}".replace(",", ",")  # Use regular comma
    return f"${amount:.2f}"


def format_price(price: float) -> str:
    """Format price as percentage."""
    return f"{price * 100:.1f}%"


# Message templates
WELCOME_MESSAGE = """
*Welcome to PolyBot\\!*

I'll help you track Polymarket traders and get notified when they make trades\\.

*Commands:*
/track `<address>` \\[label\\] \\- Track a wallet
/untrack `<address>` \\- Stop tracking
/list \\- View tracked wallets
/trades `<address>` \\- Recent trades
/status \\- Bot status
/help \\- Show this help

*Example:*
`/track 0x123...abc whale1`
"""

HELP_MESSAGE = WELCOME_MESSAGE


def format_wallet_added(address: str, label: Optional[str] = None) -> str:
    """Format wallet added confirmation."""
    addr = escape_markdown(short_address(address))
    if label:
        return f"Added *{escape_markdown(label)}* \\(`{addr}`\\) to your watchlist\\."
    return f"Added `{addr}` to your watchlist\\."


def format_wallet_removed(address: str) -> str:
    """Format wallet removed confirmation."""
    addr = escape_markdown(short_address(address))
    return f"Removed `{addr}` from your watchlist\\."


def format_wallet_list_html(wallets: list[TrackedWallet]) -> str:
    """Format list of tracked wallets with links (HTML)."""
    if not wallets:
        return "You're not tracking any wallets yet.\n\nUse /track &lt;address&gt; to start!"

    lines = ["<b>Your Tracked Wallets:</b>\n"]
    for i, w in enumerate(wallets, 1):
        addr = short_address(w.wallet_address)
        profile_link = f"https://polyoctant.com/traders/{w.wallet_address}"
        trades_link = f"https://polyoctant.com/traders/{w.wallet_address}?tab=activity"

        # Status indicator
        status = "▶️" if w.is_active else "⏸️"

        # Build wallet line with profile and trades links
        if w.label:
            line = f'{status} {i}. <b>{w.label}</b> (<a href="{profile_link}">Profile</a> | <a href="{trades_link}">Trades</a>)'
        else:
            line = f'{status} {i}. {addr} (<a href="{profile_link}">Profile</a> | <a href="{trades_link}">Trades</a>)'

        # Add min_usd constraint if set
        if w.min_usd > 0:
            line += f' >${w.min_usd:.0f}'

        lines.append(line)

    return "\n".join(lines)


def format_wallet_list(wallets: list[TrackedWallet]) -> str:
    """Format list of tracked wallets (MarkdownV2)."""
    if not wallets:
        return "You're not tracking any wallets yet\\.\n\nUse /track `<address>` to start\\!"

    lines = ["*Your Tracked Wallets:*\n"]
    for i, w in enumerate(wallets, 1):
        addr = escape_markdown(short_address(w.wallet_address))
        if w.label:
            lines.append(f"{i}\\. *{escape_markdown(w.label)}* \\- `{addr}`")
        else:
            lines.append(f"{i}\\. `{addr}`")

    return "\n".join(lines)


def format_trade_alert(
    enriched: EnrichedTrade,
    label: Optional[str] = None,
) -> str:
    """Format trade notification message using HTML."""
    trade = enriched.trade
    market = enriched.market

    # Header with emoji based on side
    emoji = "🟢" if trade.side == "BUY" else "🔴"

    # Trader display
    trader_display = label if label else short_address(trade.maker)

    # Market info
    if market:
        question = market.question[:100] + "..." if len(market.question) > 100 else market.question
        market_link = f"https://polymarket.com/event/{market.slug}"
    else:
        question = "Unknown Market"
        market_link = None

    # Outcome
    outcome = enriched.outcome or "Unknown"

    # Build message (HTML format)
    lines = [
        f"{emoji} <b>Trade Alert</b>",
        "",
        f"<b>Trader:</b> {trader_display}",
        f"<b>Action:</b> {trade.side} {outcome}",
        f"<b>Amount:</b> {format_usd(trade.usdc_value)}",
        f"<b>Price:</b> {format_price(trade.price)}",
        "",
        f"<b>Market:</b> {question}",
    ]

    # Add links
    links = []
    if market_link:
        links.append(f'<a href="{market_link}">Market</a>')

    # Trader profile link (PolyOctant)
    polyoctant_link = f"https://polyoctant.com/traders/{trade.maker}"
    links.append(f'<a href="{polyoctant_link}">Trader</a>')

    if links:
        lines.append("")
        lines.append(" | ".join(links))

    return "\n".join(lines)


def format_status(
    tracked_count: int,
    users_count: int,
    is_monitoring: bool,
) -> str:
    """Format bot status message."""
    status_emoji = "🟢" if is_monitoring else "🔴"

    return f"""
*Bot Status*

{status_emoji} Monitor: {'Running' if is_monitoring else 'Stopped'}
👥 Your tracked wallets: {tracked_count}
🌐 Total users: {users_count}
"""


def format_error(message: str) -> str:
    """Format error message."""
    return f"❌ {escape_markdown(message)}"


def format_success(message: str) -> str:
    """Format success message."""
    return f"✅ {escape_markdown(message)}"


def format_insider_alert(
    trade: 'Trade',
    market: Optional['Market'],
    outcome: Optional[str],
    trade_history: list['Trade'],
) -> str:
    """Format insider detection alert message (HTML) - new traders with large first trades."""
    # Calculate total volume from history
    total_volume = sum(t.usdc_value for t in trade_history)

    # Market info
    if market:
        question = market.question[:80] + "..." if len(market.question) > 80 else market.question
        market_link = f"https://polymarket.com/event/{market.slug}"
    else:
        question = "Unknown Market"
        market_link = None

    # Build message
    lines = [
        "🕵️ <b>INSIDER DETECTED!</b>",
        "",
        f"<b>Trader:</b> {short_address(trade.maker)}",
        f"<b>Total trades:</b> {len(trade_history)}",
        f"<b>Total volume:</b> {format_usd(total_volume)}",
        "",
        f"<b>Latest:</b> {trade.side} {outcome or 'Unknown'} - {format_usd(trade.usdc_value)} @ {format_price(trade.price)}",
        f"<b>Market:</b> {question}",
    ]

    # Add links
    polyoctant_link = f"https://polyoctant.com/traders/{trade.maker}"
    links = [f'<a href="{polyoctant_link}">Trader</a>']
    if market_link:
        links.append(f'<a href="{market_link}">Market</a>')

    lines.append("")
    lines.append(" | ".join(links))

    return "\n".join(lines)


def format_whale_alert(enriched: 'EnrichedTrade') -> str:
    """Format whale alert message (HTML) - all large trades."""
    trade = enriched.trade
    market = enriched.market
    outcome = enriched.outcome

    # Market info
    if market:
        question = market.question[:80] + "..." if len(market.question) > 80 else market.question
        market_link = f"https://polymarket.com/event/{market.slug}"
    else:
        question = "Unknown Market"
        market_link = None

    # Build message
    lines = [
        "🐋 <b>WHALE TRADE!</b>",
        "",
        f"<b>Trader:</b> {short_address(trade.maker)}",
        f"<b>Action:</b> {trade.side} {outcome or 'Unknown'}",
        f"<b>Amount:</b> {format_usd(trade.usdc_value)}",
        f"<b>Price:</b> {format_price(trade.price)}",
        f"<b>Market:</b> {question}",
    ]

    # Add links
    polyoctant_link = f"https://polyoctant.com/traders/{trade.maker}"
    links = [f'<a href="{polyoctant_link}">Trader</a>']
    if market_link:
        links.append(f'<a href="{market_link}">Market</a>')

    lines.append("")
    lines.append(" | ".join(links))

    return "\n".join(lines)

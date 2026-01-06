import re
from telegram import Update
from telegram.ext import ContextTypes

from src.config import logger
from src.storage.database import db
from src.bot.messages import (
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    format_wallet_added,
    format_wallet_removed,
    format_wallet_list,
    format_wallet_list_html,
    format_status,
    format_error,
    format_success,
    escape_markdown,
    short_address,
)

# Regex for Ethereum address
ETH_ADDRESS_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_valid_address(address: str) -> bool:
    """Check if string is a valid Ethereum address."""
    return bool(ETH_ADDRESS_REGEX.match(address))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - register user and show welcome."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    await db.add_user(chat_id, user.username)
    logger.info(f"User registered: {chat_id} (@{user.username})")

    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="MarkdownV2",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode="MarkdownV2",
    )


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /track <address> [min_usd] [label] command."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Usage: /track <address> [min_usd] [label]\n\n"
            "Examples:\n"
            "/track 0x123...abc\n"
            "/track 0x123...abc 100\n"
            "/track 0x123...abc 100 whale1",
            parse_mode="HTML",
        )
        return

    address = context.args[0].strip()

    # Extract address from Polymarket profile URL if provided
    if "polymarket.com" in address.lower() or "polyoctant.com" in address.lower():
        match = re.search(r"0x[a-fA-F0-9]{40}", address)
        if match:
            address = match.group(0)

    if not is_valid_address(address):
        await update.message.reply_text("Invalid Ethereum address. Please provide a valid 0x... address.")
        return

    # Parse optional min_usd and label
    min_usd = 0.0
    label = None
    remaining_args = context.args[1:]

    if remaining_args:
        # Check if first arg is a number (min_usd)
        try:
            min_usd = float(remaining_args[0])
            remaining_args = remaining_args[1:]
        except ValueError:
            pass  # Not a number, treat as label

        # Rest is label
        if remaining_args:
            label = " ".join(remaining_args)

    # Add to watchlist
    success = await db.add_tracked_wallet(chat_id, address, label, min_usd)

    if success:
        msg = f"Added <b>{label or short_address(address)}</b> to your watchlist."
        if min_usd > 0:
            msg += f"\nMin amount: ${min_usd:.0f}"
        await update.message.reply_text(msg, parse_mode="HTML")
        logger.info(f"User {chat_id} tracking {address} (label={label}, min=${min_usd})")
    else:
        await update.message.reply_text("You're already tracking this wallet.")


async def untrack_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /untrack <address> command."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            format_error("Please provide a wallet address.\n\nUsage: /untrack <address>"),
            parse_mode="MarkdownV2",
        )
        return

    address = context.args[0].strip()

    if not is_valid_address(address):
        await update.message.reply_text(
            format_error("Invalid Ethereum address."),
            parse_mode="MarkdownV2",
        )
        return

    success = await db.remove_tracked_wallet(chat_id, address)

    if success:
        await update.message.reply_text(
            format_wallet_removed(address),
            parse_mode="MarkdownV2",
        )
        logger.info(f"User {chat_id} untracked {address}")
    else:
        await update.message.reply_text(
            format_error("You weren't tracking this wallet."),
            parse_mode="MarkdownV2",
        )


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pause <address> command - temporarily stop notifications."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /pause <address>")
        return

    address = context.args[0].strip()
    if not is_valid_address(address):
        await update.message.reply_text("Invalid Ethereum address.")
        return

    success = await db.pause_wallet(chat_id, address)
    if success:
        await update.message.reply_text(f"⏸️ Paused notifications for {short_address(address)}")
    else:
        await update.message.reply_text("Wallet not found in your list.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume <address> command - resume notifications."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /resume <address>")
        return

    address = context.args[0].strip()
    if not is_valid_address(address):
        await update.message.reply_text("Invalid Ethereum address.")
        return

    success = await db.resume_wallet(chat_id, address)
    if success:
        await update.message.reply_text(f"▶️ Resumed notifications for {short_address(address)}")
    else:
        await update.message.reply_text("Wallet not found in your list.")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list command - show tracked wallets with links."""
    chat_id = update.effective_chat.id

    wallets = await db.get_tracked_wallets(chat_id)

    await update.message.reply_text(
        format_wallet_list_html(wallets),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    chat_id = update.effective_chat.id

    # Get user's tracked wallets count
    wallets = await db.get_tracked_wallets(chat_id)

    # Get monitor status and total users
    is_monitoring = context.bot_data.get("monitor_running", False)
    total_users = await db.get_total_users()

    await update.message.reply_text(
        format_status(len(wallets), total_users, is_monitoring),
        parse_mode="MarkdownV2",
    )


async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /trades <address> command - show recent trades."""
    from src.api.data import data_client

    chat_id = update.effective_chat.id

    if not context.args:
        # Show trades for first tracked wallet
        wallets = await db.get_tracked_wallets(chat_id)
        if not wallets:
            await update.message.reply_text(
                format_error("Please provide an address or track a wallet first."),
                parse_mode="MarkdownV2",
            )
            return
        address = wallets[0].wallet_address
    else:
        address = context.args[0].strip()
        if not is_valid_address(address):
            await update.message.reply_text(
                format_error("Invalid Ethereum address."),
                parse_mode="MarkdownV2",
            )
            return

    # Send typing indicator
    await update.message.chat.send_action("typing")

    # Fetch trades from Data API
    trades = await data_client.get_user_trades(address, limit=5)

    if not trades:
        await update.message.reply_text(
            f"No recent trades found for `{escape_markdown(short_address(address))}`\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Format trades
    lines = [f"*Recent trades for* `{escape_markdown(short_address(address))}`:\n"]

    for t in trades[:5]:
        side = t.get("side", "UNKNOWN")
        emoji = "🟢" if side == "BUY" else "🔴"
        amount = float(t.get("size", 0)) / 1_000_000
        price = float(t.get("price", 0))

        lines.append(f"{emoji} {side} \\- ${amount:,.0f} @ {price*100:.0f}%")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command - show current subscription settings."""
    chat_id = update.effective_chat.id
    sub = await db.get_subscription(chat_id)

    msg = f"""<b>⚙️ Your Subscription Settings</b>

<b>Min USD:</b> ${sub.min_usd:.0f}
<b>Side:</b> {sub.side or "ALL"}

<b>Commands:</b>
/setmin &lt;amount&gt; - Set minimum USD
/setside &lt;BUY|SELL|ALL&gt; - Filter by side"""

    await update.message.reply_text(msg, parse_mode="HTML")


async def setmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setmin <amount> command."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /setmin <amount>\nExample: /setmin 100")
        return

    try:
        amount = float(context.args[0])
        if amount < 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a number.")
        return

    await db.update_subscription_field(chat_id, "min_usd", amount)
    await update.message.reply_text(f"✅ Min USD set to ${amount:.0f}")


async def setmax_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setmax <amount> command."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /setmax <amount>\nExample: /setmax 1000 (0 = no limit)")
        return

    try:
        amount = float(context.args[0])
        if amount < 0:
            raise ValueError("Amount must be positive")
        if amount == 0:
            amount = None  # No limit
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a number.")
        return

    await db.update_subscription_field(chat_id, "max_usd", amount)
    if amount:
        await update.message.reply_text(f"✅ Max USD set to ${amount:.0f}")
    else:
        await update.message.reply_text("✅ Max USD limit removed")


async def setside_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setside <BUY|SELL|ALL> command."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /setside <BUY|SELL|ALL>")
        return

    side = context.args[0].upper()
    if side not in ["BUY", "SELL", "ALL"]:
        await update.message.reply_text("❌ Invalid side. Use BUY, SELL, or ALL.")
        return

    if side == "ALL":
        side = None

    await db.update_subscription_field(chat_id, "side", side)
    await update.message.reply_text(f"✅ Side filter set to {side or 'ALL'}")


async def cat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cat <category> command - add category filter."""
    from src.api.gamma import gamma_client

    chat_id = update.effective_chat.id

    if not context.args:
        # Fetch real categories from API
        await update.message.chat.send_action("typing")
        tags = await gamma_client.get_all_categories()
        if tags:
            import html
            # Get featured first, then fill with recent ones up to 10
            featured = [t for t in tags if t.get("forceShow")]
            # Sort rest by updatedAt (most recent first)
            others = sorted(
                [t for t in tags if not t.get("forceShow") and not t.get("forceHide")],
                key=lambda t: t.get("updatedAt", ""),
                reverse=True
            )
            # Combine: featured + recent, limit to 10
            combined = featured + others
            tags_display = combined[:10]
            tags_sorted = sorted(tags_display, key=lambda t: t.get("label", "").lower())

            cat_list = "\n".join(f"• {html.escape(t['label'])}" for t in tags_sorted)
            await update.message.reply_text(
                f"<b>Popular categories:</b>\n{cat_list}\n\n"
                "Usage: /cat &lt;category&gt;\nExample: /cat Crypto",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "<b>Common categories:</b>\n"
                "• Crypto\n• Sports\n• Politics\n• Tech\n• Pop-Culture\n\n"
                "Usage: /cat &lt;category&gt;\nExample: /cat Crypto",
                parse_mode="HTML"
            )
        return

    category = context.args[0]
    added = await db.add_category(chat_id, category)

    if added:
        await update.message.reply_text(f"✅ Added category: {category}")
    else:
        await update.message.reply_text(f"⚠️ Category already added: {category}")


async def rmcat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /rmcat <category> command - remove category filter."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: /rmcat <category>")
        return

    category = context.args[0]
    removed = await db.remove_category(chat_id, category)

    if removed:
        await update.message.reply_text(f"✅ Removed category: {category}")
    else:
        await update.message.reply_text(f"❌ Category not found: {category}")


async def clearcat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearcat command - clear all category filters."""
    chat_id = update.effective_chat.id

    await db.clear_categories(chat_id)
    await update.message.reply_text("✅ All category filters cleared (now receiving ALL markets)")


async def insider_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /insider command - detect new traders with large first trades."""
    chat_id = update.effective_chat.id
    sub = await db.get_subscription(chat_id)

    if not context.args:
        status = "ON" if sub.insider_alert else "OFF"
        msg = f"""<b>🕵️ Insider Detection</b>

<b>Status:</b> {status}
<b>Min USD:</b> ${sub.insider_min_usd:,.0f}
<b>Max Trades:</b> {sub.insider_max_trades}

Detects NEW traders whose first {sub.insider_max_trades} trades ALL exceed ${sub.insider_min_usd:,.0f}.

<b>Commands:</b>
/insider on - Enable
/insider off - Disable
/insider 10000 3 - Set min USD and max trades"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    arg = context.args[0].lower()

    if arg == "on":
        sub.insider_alert = True
        await db.set_subscription(sub)
        await update.message.reply_text(f"✅ Insider alerts enabled\nMin: ${sub.insider_min_usd:,.0f} | Max trades: {sub.insider_max_trades}")
    elif arg == "off":
        sub.insider_alert = False
        await db.set_subscription(sub)
        await update.message.reply_text("✅ Insider alerts disabled")
    else:
        try:
            min_usd = float(context.args[0])
            max_trades = int(context.args[1]) if len(context.args) > 1 else 3
            sub.insider_min_usd = min_usd
            sub.insider_max_trades = max_trades
            sub.insider_alert = True
            await db.set_subscription(sub)
            await update.message.reply_text(
                f"✅ Insider alerts configured\n"
                f"Min USD: ${min_usd:,.0f}\n"
                f"Max trades: {max_trades}\n"
                f"Status: ON"
            )
        except ValueError:
            await update.message.reply_text("Usage: /insider [on|off] or /insider <min_usd> [max_trades]")


async def whale_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /whale command - track all large trades above threshold."""
    chat_id = update.effective_chat.id
    sub = await db.get_subscription(chat_id)

    if not context.args:
        status = "ON" if sub.whale_alert else "OFF"
        msg = f"""<b>🐋 Whale Tracking</b>

<b>Status:</b> {status}
<b>Min USD:</b> ${sub.whale_min_usd:,.0f}

Get alerts for ALL trades above ${sub.whale_min_usd:,.0f} (any trader).

<b>Commands:</b>
/whale on - Enable
/whale off - Disable
/whale 5000 - Set min USD threshold"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    arg = context.args[0].lower()

    if arg == "on":
        sub.whale_alert = True
        await db.set_subscription(sub)
        await update.message.reply_text(f"✅ Whale tracking enabled (trades > ${sub.whale_min_usd:,.0f})")
    elif arg == "off":
        sub.whale_alert = False
        await db.set_subscription(sub)
        await update.message.reply_text("✅ Whale tracking disabled")
    else:
        try:
            min_usd = float(context.args[0])
            sub.whale_min_usd = min_usd
            sub.whale_alert = True
            await db.set_subscription(sub)
            await update.message.reply_text(f"✅ Whale tracking enabled (trades > ${min_usd:,.0f})")
        except ValueError:
            await update.message.reply_text("Usage: /whale [on|off] or /whale <min_usd>")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in handlers."""
    logger.error(f"Update {update} caused error: {context.error}")

    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, something went wrong. Please try again.",
        )

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.config import logger
from src.storage.database import db
from src.bot.messages import format_wallet_removed, format_error


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id

    if data.startswith("untrack:"):
        # Untrack wallet from inline button
        address = data.split(":", 1)[1]
        success = await db.remove_tracked_wallet(chat_id, address)

        if success:
            await query.edit_message_text(
                format_wallet_removed(address),
                parse_mode="MarkdownV2",
            )
            logger.info(f"User {chat_id} untracked {address} via button")
        else:
            await query.edit_message_text(
                format_error("Failed to untrack wallet."),
                parse_mode="MarkdownV2",
            )

    elif data.startswith("view_trades:"):
        # View trades for address
        address = data.split(":", 1)[1]
        # This would trigger the trades command logic
        # For now, just acknowledge
        await query.answer("Use /trades command", show_alert=True)

    else:
        logger.warning(f"Unknown callback data: {data}")
        await query.answer("Unknown action", show_alert=True)


def create_trade_buttons(address: str, tx_hash: str) -> InlineKeyboardMarkup:
    """Create inline buttons for trade notifications."""
    buttons = [
        [
            InlineKeyboardButton(
                "View Trades",
                callback_data=f"view_trades:{address}",
            ),
            InlineKeyboardButton(
                "Untrack",
                callback_data=f"untrack:{address}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

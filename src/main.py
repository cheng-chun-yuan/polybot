import asyncio
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
)

from src.config import TELEGRAM_BOT_TOKEN, logger
from src.storage.database import db
from src.storage.models import EnrichedTrade
from src.monitor.trade_monitor import TradeMonitor
from src.bot.handlers import (
    start_command,
    help_command,
    track_command,
    untrack_command,
    pause_command,
    resume_command,
    list_command,
    status_command,
    settings_command,
    setmin_command,
    setside_command,
    insider_command,
    whale_command,
    error_handler,
)
from src.bot.callbacks import handle_callback
from src.bot.messages import format_trade_alert, format_insider_alert, format_whale_alert
from src.api.envio import envio_client
from src.api.gamma import gamma_client
from src.api.data import data_client
from src.api.clob import clob_client


# Global application reference for notifications
_app: Optional[Application] = None


async def send_trade_notification(
    enriched: EnrichedTrade,
    watchers: list[tuple[int, Optional[str], float]],
) -> None:
    """Send trade notification to all users watching this wallet."""
    if not _app:
        logger.error("Application not initialized")
        return

    for chat_id, label, wallet_min_usd in watchers:
        try:
            # Check per-wallet minimum USD constraint
            if wallet_min_usd > 0 and enriched.trade.usdc_value < wallet_min_usd:
                logger.debug(f"Skipped {chat_id}: wallet min ${wallet_min_usd}, trade ${enriched.trade.usdc_value:.2f}")
                continue

            # Check user's global subscription filters
            sub = await db.get_subscription(chat_id)
            matched, reason = sub.matches_trade(enriched.trade, enriched.market)

            if not matched:
                logger.debug(f"Skipped {chat_id}: {reason}")
                continue

            message = format_trade_alert(enriched, label)
            await _app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info(f"Sent notification to {chat_id} for trade {enriched.trade.trade_id}")
        except Exception as e:
            logger.error(f"Failed to send notification to {chat_id}: {e}")


async def send_insider_notification(
    trade,
    market,
    outcome: Optional[str],
    trade_history: list,
) -> None:
    """Send insider detection alert to users with insider_alert enabled."""
    if not _app:
        logger.error("Application not initialized")
        return

    # Get all users with insider_alert enabled
    cursor = await db._conn.execute(
        "SELECT chat_id FROM subscriptions WHERE insider_alert = 1"
    )
    rows = await cursor.fetchall()

    for row in rows:
        chat_id = row["chat_id"]
        try:
            sub = await db.get_subscription(chat_id)

            # Verify trade meets user's insider criteria
            if trade.usdc_value < sub.insider_min_usd:
                continue

            # Check if ALL trades in history meet the user's min_usd
            all_qualify = all(t.usdc_value >= sub.insider_min_usd for t in trade_history)
            if not all_qualify:
                continue

            # Check max trades
            if len(trade_history) > sub.insider_max_trades:
                continue

            message = format_insider_alert(trade, market, outcome, trade_history)
            await _app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info(f"Sent insider alert to {chat_id} for trader {trade.maker[:10]}")
        except Exception as e:
            logger.error(f"Failed to send insider alert to {chat_id}: {e}")


async def send_whale_notification(enriched) -> None:
    """Send whale alert to users with whale_alert enabled for large trades."""
    if not _app:
        logger.error("Application not initialized")
        return

    trade = enriched.trade

    # Get all users with whale_alert enabled
    cursor = await db._conn.execute(
        "SELECT chat_id FROM subscriptions WHERE whale_alert = 1"
    )
    rows = await cursor.fetchall()

    for row in rows:
        chat_id = row["chat_id"]
        try:
            sub = await db.get_subscription(chat_id)

            # Check if trade meets user's whale threshold
            if trade.usdc_value < sub.whale_min_usd:
                continue

            message = format_whale_alert(enriched)
            await _app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info(f"Sent whale alert to {chat_id} for ${trade.usdc_value:.0f} trade")
        except Exception as e:
            logger.error(f"Failed to send whale alert to {chat_id}: {e}")


async def post_init(application: Application) -> None:
    """Called after the Application has been initialized."""
    global _app
    _app = application

    # Connect to database
    await db.connect()

    # Start trade monitor with trade, insider, and whale callbacks
    monitor = TradeMonitor(
        on_trade=send_trade_notification,
        on_insider=send_insider_notification,
        on_whale=send_whale_notification,
    )
    await monitor.start()

    # Store monitor in bot_data for status command
    application.bot_data["monitor"] = monitor
    application.bot_data["monitor_running"] = True

    # Health check ENVIO
    if await envio_client.health_check():
        logger.info("ENVIO connection healthy")
    else:
        logger.warning("ENVIO connection may have issues")

    logger.info("Bot initialized successfully")


async def post_shutdown(application: Application) -> None:
    """Called when the Application is shutting down."""
    # Stop trade monitor
    monitor = application.bot_data.get("monitor")
    if monitor:
        await monitor.stop()

    # Close API clients
    await envio_client.close()
    await gamma_client.close()
    await data_client.close()
    await clob_client.close()

    # Close database
    await db.close()

    logger.info("Bot shutdown complete")


def main() -> None:
    """Main entry point."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        print("Error: Please set TELEGRAM_BOT_TOKEN in .env file")
        return

    # Create application
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("untrack", untrack_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("status", status_command))

    # Subscription settings commands
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("setmin", setmin_command))
    application.add_handler(CommandHandler("setside", setside_command))
    application.add_handler(CommandHandler("insider", insider_command))
    application.add_handler(CommandHandler("whale", whale_command))

    # Register callback handler
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Register error handler
    application.add_error_handler(error_handler)

    # Run the bot
    logger.info("Starting PolyBot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

"""
main.py — Entry point for the Study Materials Telegram Bot
Initialises the database, registers all handlers, and starts polling.
"""

import logging
import os
import sys
import traceback

from telegram import Update
from telegram.ext import Application, ContextTypes

import database as db
from handlers import admin, user

# ---------------------------------------------------------------------------
# Logging — outputs to stdout so Replit/Render can capture it
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=logging.DEBUG,          # DEBUG so we see every handler error
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Silence very noisy libs but keep their errors/warnings
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)


def main():
    # -----------------------------------------------------------------------
    # Read required environment variables
    # -----------------------------------------------------------------------
    bot_token = (
        os.environ.get("BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
    )
    if not bot_token:
        logger.critical("BOT_TOKEN environment variable is not set. Exiting.")
        sys.exit(1)

    paystack_key = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not paystack_key:
        logger.warning("PAYSTACK_SECRET_KEY is not set — payments will fail.")

    admin_id = (
        os.environ.get("ADMIN_CHAT_ID")
        or os.environ.get("ADMIN_TELEGRAM_ID", "")
    )
    if not admin_id:
        logger.warning("ADMIN_CHAT_ID is not set — admin notifications disabled.")

    # -----------------------------------------------------------------------
    # Initialise SQLite database (creates tables + seeds sample materials)
    # -----------------------------------------------------------------------
    db.init_db()
    logger.info("Database initialised at %s", db.DB_PATH)

    # -----------------------------------------------------------------------
    # Build the bot Application
    # -----------------------------------------------------------------------
    app = Application.builder().token(bot_token).build()

    # Global error handler — logs full traceback for every unhandled exception
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(
            "Exception while handling update:\n%s",
            "".join(traceback.format_exception(
                type(context.error), context.error, context.error.__traceback__
            )),
        )
        # Try to tell the user something went wrong
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ Something went wrong. Please type /start and try again."
                )
            except Exception:
                pass

    app.add_error_handler(error_handler)

    # Register handlers — admin first so its ConversationHandlers take priority
    admin.register(app)
    user.register(app)

    # -----------------------------------------------------------------------
    # Start polling (simple, no webhook server needed)
    # -----------------------------------------------------------------------
    logger.info("Bot is running — polling for updates…")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=False,  # process messages sent while bot was restarting
    )


if __name__ == "__main__":
    main()

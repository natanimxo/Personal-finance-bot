import logging
import os
from datetime import time, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

from app import config
from app.config import BOT_TOKEN
from app.db import init_db
from app.bot.keyboards import *  # noqa: F401,F403
from app.bot.membership import recheck_sub_callback
from app.bot.handlers import *  # noqa: F401,F403
from app.services.recap import send_weekly_recap

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")
    init_db()
    logger.info("Database: %s", os.path.abspath(config.DB_PATH))
    app = Application.builder().token(BOT_TOKEN).build()

    flow_fallbacks = [
        CommandHandler("cancel", cancel),
        MessageHandler(filters.Text([BTN_CANCEL]), cancel),
        CommandHandler("start", leave_flow_for_menu),
        MessageHandler(filters.Text(MENU_BUTTONS), leave_flow_for_menu),
    ]
    timeout_state = {
        ConversationHandler.TIMEOUT: [
            MessageHandler(filters.ALL, conversation_timeout),
            CallbackQueryHandler(conversation_timeout),
        ]
    }
    FLOW_TIMEOUT = 15 * 60  # seconds

    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD}$"), add_start)],
        states={
            ASK_AMOUNT: [MessageHandler(FLOW_TEXT, add_amount_received)],
            ASK_CATEGORY: [CallbackQueryHandler(add_category_chosen, pattern="^addcat_")],
            ASK_ACCOUNT: [CallbackQueryHandler(add_account_chosen, pattern="^addacc_")],
            ASK_NOTE: [
                MessageHandler(FLOW_TEXT, add_note_received),
                CallbackQueryHandler(add_note_skipped, pattern="^skip_note$"),
            ],
            **timeout_state,
        },
        fallbacks=flow_fallbacks,
        conversation_timeout=FLOW_TIMEOUT,
    )
    app.add_handler(add_conv)

    add_income_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD_INCOME}$"), add_income_start)],
        states={
            ASK_INCOME_AMOUNT: [MessageHandler(FLOW_TEXT, add_income_amount_received)],
            ASK_INCOME_CATEGORY: [CallbackQueryHandler(add_income_category_chosen, pattern="^inccat_")],
            ASK_INCOME_ACCOUNT: [CallbackQueryHandler(add_income_account_chosen, pattern="^incacc_")],
            ASK_INCOME_NOTE: [
                MessageHandler(FLOW_TEXT, add_income_note_received),
                CallbackQueryHandler(add_income_note_skipped, pattern="^skip_income_note$"),
            ],
            **timeout_state,
        },
        fallbacks=flow_fallbacks,
        conversation_timeout=FLOW_TIMEOUT,
    )
    app.add_handler(add_income_conv)

    budget_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(budget_start, pattern="^set_budget_start$")],
        states={
            BUDGET_CATEGORY: [CallbackQueryHandler(budget_category_chosen, pattern="^budgetcat_")],
            BUDGET_AMOUNT: [MessageHandler(FLOW_TEXT, budget_amount_received)],
            **timeout_state,
        },
        fallbacks=flow_fallbacks,
        conversation_timeout=FLOW_TIMEOUT,
    )
    app.add_handler(budget_conv)

    # Plain menu screens. Registered AFTER the flows on purpose: a menu button tapped
    # mid-flow must reach the flow's fallback (which ends the flow) first.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HISTORY}$"), history_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SUMMARY}$"), summary_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BUDGETS}$"), budgets_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_ACCOUNTS}$"), accounts_view))

    app.add_handler(CallbackQueryHandler(recheck_sub_callback, pattern="^recheck_sub$"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(summary_callback, pattern="^sum_"))
    app.add_handler(CallbackQueryHandler(set_default_account_start, pattern="^set_default_account_start$"))
    app.add_handler(CallbackQueryHandler(set_default_account_callback, pattern="^setdefacc_"))

    app.job_queue.run_daily(
        # python-telegram-bot 20+ numbers days 0=Sunday ... 6=Saturday, so Monday is 1.
        send_weekly_recap, time=time(hour=9, tzinfo=timezone.utc), days=(1,)
    )

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

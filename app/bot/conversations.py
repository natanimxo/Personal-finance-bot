"""Registers every bot handler on the Application."""
import warnings

from telegram.ext import (
    CallbackQueryHandler,
    TypeHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

from app.bot import handlers as h
from app.bot import quick
from app.bot.keyboards import (
    BTN_ACCOUNTS, BTN_ADD, BTN_ADD_INCOME, BTN_BUDGETS, BTN_CANCEL, BTN_HELP, BTN_HISTORY, BTN_SUMMARY,
    CB_FLOW_CANCEL, FLOW_TEXT, MENU_BUTTONS,
)
from app.bot.errors import on_error
from app.bot.membership import recheck_sub_callback, track_activity

FLOW_TIMEOUT = 10 * 60  # seconds an unfinished entry stays open

# Buttons that open a plain screen. Add Expense / Add Income are entry points of the
# flow itself, so tapping them mid-flow restarts the flow with that type (allow_reentry).
SCREEN_BUTTONS = [BTN_HISTORY, BTN_SUMMARY, BTN_BUDGETS, BTN_ACCOUNTS, BTN_HELP]


def build_flows(timeout: int = FLOW_TIMEOUT) -> ConversationHandler:
    """One conversation for adding expenses, income and budgets, so any menu
    button can end whichever flow is open and run its own action."""
    with warnings.catch_warnings():
        # The flow mixes message and button steps; per-chat tracking is what we want.
        warnings.filterwarnings("ignore", message=r"If 'per_message=False'", category=PTBUserWarning)
        return ConversationHandler(
            entry_points=[
                MessageHandler(filters.Text([BTN_ADD]), h.add_start),
                MessageHandler(filters.Text([BTN_ADD_INCOME]), h.add_income_start),
                CallbackQueryHandler(h.budget_start, pattern="^set_budget_start$"),
            ],
            states={
                h.ASK_AMOUNT: [MessageHandler(FLOW_TEXT, h.add_amount_received)],
                h.ASK_CATEGORY: [CallbackQueryHandler(h.add_category_chosen, pattern="^addcat_")],
                h.ASK_ACCOUNT: [CallbackQueryHandler(h.add_account_chosen, pattern="^addacc_")],
                h.ASK_NOTE: [
                    MessageHandler(FLOW_TEXT, h.add_note_received),
                    CallbackQueryHandler(h.add_note_skipped, pattern="^skip_note$"),
                ],
                h.ASK_INCOME_AMOUNT: [MessageHandler(FLOW_TEXT, h.add_income_amount_received)],
                h.ASK_INCOME_CATEGORY: [CallbackQueryHandler(h.add_income_category_chosen, pattern="^inccat_")],
                h.ASK_INCOME_ACCOUNT: [CallbackQueryHandler(h.add_income_account_chosen, pattern="^incacc_")],
                h.ASK_INCOME_NOTE: [
                    MessageHandler(FLOW_TEXT, h.add_income_note_received),
                    CallbackQueryHandler(h.add_income_note_skipped, pattern="^skip_income_note$"),
                ],
                h.BUDGET_CATEGORY: [CallbackQueryHandler(h.budget_category_chosen, pattern="^budgetcat_")],
                h.BUDGET_AMOUNT: [MessageHandler(FLOW_TEXT, h.budget_amount_received)],
                ConversationHandler.TIMEOUT: [
                    MessageHandler(filters.ALL, h.conversation_timeout),
                    CallbackQueryHandler(h.conversation_timeout),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", h.cancel),
                MessageHandler(filters.Text([BTN_CANCEL]), h.cancel),
                CallbackQueryHandler(h.cancel, pattern=f"^{CB_FLOW_CANCEL}$"),
                CommandHandler("start", h.leave_flow_for_menu),
                MessageHandler(filters.Text(SCREEN_BUTTONS), h.leave_flow_for_menu),
            ],
            allow_reentry=True,
            conversation_timeout=timeout,
            name="flows",
        )


def register_handlers(app, flow_timeout: int = FLOW_TIMEOUT):
    # Group -1 runs before everything else: marks the sender active (a user who
    # blocked the bot and comes back gets recaps again).
    from telegram import Update
    app.add_handler(TypeHandler(Update, track_activity), group=-1)
    app.add_error_handler(on_error)

    # The flow goes first: a menu button tapped mid-flow must reach its fallback
    # (which ends the flow) before the plain screen handlers below see it.
    app.add_handler(build_flows(flow_timeout))

    app.add_handler(CommandHandler("start", h.start))
    app.add_handler(CommandHandler("help", h.help_view))
    app.add_handler(CommandHandler("recap_now", h.recap_now))
    app.add_handler(CommandHandler("backup_now", h.backup_now))
    app.add_handler(MessageHandler(filters.Text([BTN_HELP]), h.help_view))
    app.add_handler(MessageHandler(filters.Text([BTN_HISTORY]), h.history_view))
    app.add_handler(MessageHandler(filters.Text([BTN_SUMMARY]), h.summary_view))
    app.add_handler(MessageHandler(filters.Text([BTN_BUDGETS]), h.budgets_view))
    app.add_handler(MessageHandler(filters.Text([BTN_ACCOUNTS]), h.accounts_view))

    app.add_handler(CallbackQueryHandler(recheck_sub_callback, pattern="^recheck_sub$"))
    app.add_handler(CallbackQueryHandler(h.delete_callback, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(h.summary_callback, pattern="^sum_"))
    app.add_handler(CallbackQueryHandler(h.set_default_account_start, pattern="^set_default_account_start$"))
    app.add_handler(CallbackQueryHandler(h.set_default_account_callback, pattern="^setdefacc_"))
    app.add_handler(CallbackQueryHandler(h.change_account_start, pattern=r"^chacc:\d+$"))
    app.add_handler(CallbackQueryHandler(h.change_account_chosen, pattern=r"^setacc:\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(h.stale_cancel, pattern=f"^{CB_FLOW_CANCEL}$"))

    # Quick entry: a plain message that starts with an amount ("500 food lunch").
    # Registered after the flows, so a number typed as a flow's answer goes to the flow.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*\+?\s*\.?\d"),
                                   quick.quick_entry_message))
    app.add_handler(CallbackQueryHandler(quick.quick_category_chosen, pattern="^qcat_"))
    app.add_handler(CallbackQueryHandler(quick.undo_callback, pattern=r"^undo:\d+$"))

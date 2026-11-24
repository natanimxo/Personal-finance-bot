"""Bot screens and the guided add-entry / budget flows.

Every message goes out as HTML (the Application's default parse mode), and every
dynamic value (notes, labels, links) is passed through esc() first.
"""
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app import config
from app.bot.keyboards import (
    BTN_ACCOUNTS, BTN_ADD, BTN_ADD_INCOME, BTN_BUDGETS, BTN_CANCEL, BTN_HELP, BTN_HISTORY, BTN_SETTINGS, BTN_SUMMARY,
    ACCOUNTS, MINUS,
    account_keyboard, account_label, cancel_keyboard, category_keyboard, esc,
    MAX_NOTE_LENGTH, label_for, main_menu_keyboard, note_keyboard, parse_amount,
)
from app.bot.membership import is_subscribed, require_subscription, send_gate, touch_user
from app.db import db_call
from app.services import accounts, budgets, categories, periods, prefs, summaries, transactions, users
from app.services.money import fmt
from app.services.backup import run_backup
from app.services.validation import ValidationError, check_date, to_minor
from app.services.recap import recap_text
from app.strings import t

logger = logging.getLogger(__name__)

ASK_AMOUNT, ASK_CATEGORY, ASK_ACCOUNT, ASK_NOTE = range(4)
ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_ACCOUNT, ASK_INCOME_NOTE = range(10, 14)
BUDGET_CATEGORY, BUDGET_AMOUNT = range(20, 22)

PENDING_KEYS = ("pending_amount", "pending_category", "pending_account", "used_default", "pending_budget_category",
                "editing", "pending_day", "day_choice", "flow_type", "account_naming", "transfer",
                "category_naming")


def clear_pending(context: ContextTypes.DEFAULT_TYPE):
    for key in PENDING_KEYS:
        context.user_data.pop(key, None)


# ---------------------------------------------------------------------------
# Start / Help
# ---------------------------------------------------------------------------
@require_subscription
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(welcome_text(), reply_markup=main_menu_keyboard())


def welcome_text() -> str:
    return t("start.welcome", add=BTN_ADD, add_income=BTN_ADD_INCOME, history=BTN_HISTORY, summary=BTN_SUMMARY,
             budgets=BTN_BUDGETS, accounts=BTN_ACCOUNTS, settings=BTN_SETTINGS)


@require_subscription
async def help_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        t("help.text", add=BTN_ADD, add_income=BTN_ADD_INCOME, cancel=BTN_CANCEL), reply_markup=main_menu_keyboard())


# ---------------------------------------------------------------------------
# Add expense / income — one guided flow, parameterised by type
# ---------------------------------------------------------------------------
FLOW = {
    "expense": {
        "ask": t("flow.ask_expense"),
        "example": t("flow.example_expense"),
        "cat_prefix": "addcat", "acc_prefix": "addacc", "skip": "skip_note",
        "states": (ASK_AMOUNT, ASK_CATEGORY, ASK_ACCOUNT, ASK_NOTE),
    },
    "income": {
        "ask": t("flow.ask_income"),
        "example": t("flow.example_income"),
        "cat_prefix": "inccat", "acc_prefix": "incacc", "skip": "skip_income_note",
        "states": (ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_ACCOUNT, ASK_INCOME_NOTE),
    },
}


async def _flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    user_id = update.effective_user.id
    if not await is_subscribed(context, user_id):
        await send_gate(update)
        return ConversationHandler.END
    await touch_user(user_id)
    clear_pending(context)
    await update.message.reply_text(FLOW[type_]["ask"], reply_markup=cancel_keyboard())
    return FLOW[type_]["states"][0]


async def _flow_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    cfg = FLOW[type_]
    try:
        amount = parse_amount(update.message.text)
    except ValueError as e:
        await update.message.reply_text(t("flow.bad_amount", error=esc(e), example=cfg["example"]))
        return cfg["states"][0]
    context.user_data["pending_amount"] = amount
    options = await db_call(categories.choices, update.effective_user.id, type_)
    await update.message.reply_text(t("flow.pick_category"), reply_markup=category_keyboard(cfg["cat_prefix"], options))
    return cfg["states"][1]


ASK_DATE = 40  # typed date for "📅 Other date" (either flow; the type is in user_data)


def _note_prompt(context) -> str:
    day = context.user_data.get("pending_day")
    when = t("flow.today") if day is None else t("flow.day", day=day)
    return t("flow.note_prompt", when=when)


async def _ask_note(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    context.user_data["flow_type"] = type_
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=_note_prompt(context),
        reply_markup=note_keyboard(FLOW[type_]["skip"], context.user_data.get("day_choice", "today")),
    )
    return FLOW[type_]["states"][3]


async def flow_date_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Today / Yesterday / Other date on the note step."""
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    type_ = context.user_data.get("flow_type", "expense")
    if choice == "other":
        await query.edit_message_text(t("flow.type_date"))
        return ASK_DATE
    context.user_data["day_choice"] = choice
    context.user_data["pending_day"] = None if choice == "today" else periods.today() - timedelta(days=1)
    await query.edit_message_text(_note_prompt(context), reply_markup=note_keyboard(FLOW[type_]["skip"], choice))
    return FLOW[type_]["states"][3]


async def flow_date_typed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    type_ = context.user_data.get("flow_type", "expense")
    try:
        day = check_date(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(t("common.try_again", error=esc(e), cancel=BTN_CANCEL))
        return ASK_DATE
    context.user_data["pending_day"] = None if day == periods.today() else day
    context.user_data["day_choice"] = "today" if day == periods.today() else "other"
    return await _ask_note(update, context, type_)


async def _flow_category(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    cfg = FLOW[type_]
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_category"] = category_key
    label = await db_call(categories.label, update.effective_user.id, type_, category_key)
    await query.edit_message_text(t("flow.category_chosen", label=esc(label)))

    default = await db_call(accounts.get_default_account, update.effective_user.id)
    if default:
        # A default account is set: skip the account step. The confirmation
        # offers "Change account" instead.
        context.user_data["pending_account"] = default
        context.user_data["used_default"] = True
        return await _ask_note(update, context, type_)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t("flow.which_account"),
        reply_markup=account_keyboard(cfg["acc_prefix"], await db_call(accounts.choices, update.effective_user.id)),
    )
    return cfg["states"][2]


async def _flow_account(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    context.user_data["pending_account"] = account_key
    names = await db_call(accounts.names, update.effective_user.id)
    await query.edit_message_text(t("flow.account_chosen", name=esc(names.get(account_key, account_key))))
    return await _ask_note(update, context, type_)


def account_name(entry) -> str:
    """The entry's account as the user named it (falls back to the original labels)."""
    return entry.get("account_name") or account_label(entry["account"])


def entry_line(entry) -> str:
    if entry["type"] == "transfer":
        to_name = entry.get("to_account_name") or account_label(entry["to_account"])
        text = t("entry.moved", amount=fmt(entry["amount_minor"], entry["currency"]),
                 from_account=esc(account_name(entry)), to_account=esc(to_name))
        return text + _date_and_note(entry)
    type_ = entry["type"]
    signed = entry["amount_minor"] if type_ == "income" else -entry["amount_minor"]
    icon = "💵" if type_ == "income" else "✅"
    text = t("entry.logged", icon=icon, amount=fmt(signed, entry["currency"], sign=True),
             category=esc(entry["category_name"]), account=esc(account_name(entry)))
    return text + _date_and_note(entry)


def _date_and_note(entry) -> str:
    text = ""
    day = periods.local_date_of(entry["occurred_at"])
    if day != periods.today():
        text += t("entry.date_line", day=day)
    if entry["note"]:
        text += t("entry.note_line", note=esc(entry["note"]))
    return text


def change_account_keyboard(entry_id: int):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("entry.change_account"), callback_data=f"chacc:{entry_id}")]]
    )


def budget_warning_text(warning) -> str:
    """The bot's wording for a warning from budgets.warning_for (shared with the Mini App)."""
    if not warning:
        return ""
    label = esc(warning["label"])
    currency = warning.get("currency")
    used = f"{fmt(warning['spent_minor'], currency)} / {fmt(warning['limit_minor'], currency)}"
    if warning["level"] == "over":
        return t("budget.over", label=label, used=used)
    return t("budget.near", percent=warning["percent"], label=label, used=used)


async def _finalize(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str, type_: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    amount = context.user_data.pop("pending_amount")
    category_key = context.user_data.pop("pending_category")
    account_key = context.user_data.pop("pending_account", "cash")
    used_default = context.user_data.pop("used_default", False)
    day = context.user_data.pop("pending_day", None)
    context.user_data.pop("day_choice", None)
    entry, warning = await db_call(
        transactions.add_entry, user_id, to_minor(amount), type_, category_key, account_key, note, day
    )
    entry_id = entry["id"]
    text = entry_line(entry)
    if warning:
        text += "\n\n" + budget_warning_text(warning)

    if used_default:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=change_account_keyboard(entry_id))
        await context.bot.send_message(chat_id=chat_id, text=t("menu.hint"), reply_markup=main_menu_keyboard())
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def _flow_note_typed(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    note = update.message.text.strip()
    if len(note) > MAX_NOTE_LENGTH:
        await update.message.reply_text(
            t("flow.note_too_long", max=MAX_NOTE_LENGTH, length=len(note)),
            reply_markup=note_keyboard(FLOW[type_]["skip"], context.user_data.get("day_choice", "today")),
        )
        return FLOW[type_]["states"][3]
    return await _finalize(update, context, note, type_)


async def _flow_note_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("flow.no_note"))
    return await _finalize(update, context, "", type_)


def _bind(fn, type_):
    async def handler(update, context):
        return await fn(update, context, type_)
    handler.__name__ = f"{fn.__name__}_{type_}"
    return handler


add_start = _bind(_flow_start, "expense")
add_amount_received = _bind(_flow_amount, "expense")
add_category_chosen = _bind(_flow_category, "expense")
add_account_chosen = _bind(_flow_account, "expense")
add_note_received = _bind(_flow_note_typed, "expense")
add_note_skipped = _bind(_flow_note_skipped, "expense")

add_income_start = _bind(_flow_start, "income")
add_income_amount_received = _bind(_flow_amount, "income")
add_income_category_chosen = _bind(_flow_category, "income")
add_income_account_chosen = _bind(_flow_account, "income")
add_income_note_received = _bind(_flow_note_typed, "income")
add_income_note_skipped = _bind(_flow_note_skipped, "income")


# ---------------------------------------------------------------------------
# Change the account of a saved entry (the default-account shortcut's undo)
# ---------------------------------------------------------------------------
async def change_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":", 1)[1])
    entry = await db_call(transactions.get_entry, update.effective_user.id, entry_id)
    if not entry:
        await query.answer(t("common.entry_deleted"), show_alert=True)
        return
    await query.answer()
    options = await db_call(accounts.choices, update.effective_user.id)
    await query.edit_message_reply_markup(
        reply_markup=account_keyboard(f"setacc:{entry_id}", options, default=entry["account"], with_cancel=False, sep=":")
    )


async def change_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, account_key = query.data.split(":", 2)
    entry_id = int(entry_id)
    user_id = update.effective_user.id
    try:
        moved = await db_call(transactions.set_account, user_id, entry_id, account_key)
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    if not moved:
        await query.answer(t("common.entry_deleted"), show_alert=True)
        return
    entry = await db_call(transactions.get_entry, user_id, entry_id)
    await query.answer(t("entry.moved_to", name=account_name(entry)))
    await query.edit_message_text(entry_line(entry), reply_markup=change_account_keyboard(entry_id))


# ---------------------------------------------------------------------------
# Leaving a flow
# ---------------------------------------------------------------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_pending(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(t("flow.cancelled_inline"))
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=t("flow.cancelled"), reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def stale_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A Cancel button from a flow that already ended."""
    await update.callback_query.answer(t("flow.nothing_to_cancel"))
    await update.callback_query.edit_message_reply_markup(reply_markup=None)


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_pending(context)
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t("flow.timed_out"),
            reply_markup=main_menu_keyboard(),
        )


async def leave_flow_for_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A menu button (or /start) tapped mid-flow: drop the half-finished entry and run that button."""
    clear_pending(context)
    text = update.message.text if update.message else ""
    from app.bot.settings_ui import settings_view

    view = {
        BTN_HISTORY: history_view,
        BTN_SUMMARY: summary_view,
        BTN_BUDGETS: budgets_view,
        BTN_ACCOUNTS: accounts_view,
        BTN_SETTINGS: settings_view,
        BTN_HELP: help_view,
    }.get(text, start)
    if view is not start and view is not help_view:
        # These screens carry inline buttons, so bring the main keyboard back first.
        await update.message.reply_text(t("flow.dropped"), reply_markup=main_menu_keyboard())
    await view(update, context)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.bot.history import history_view as paged

    await paged(update, context)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    expense_id = int(query.data.split("_", 1)[1])
    ok = await db_call(transactions.delete_expense, update.effective_user.id, expense_id)
    await query.answer(t("history.deleted_toast") if ok else t("history.gone_toast"))
    if ok:
        await query.edit_message_text(t("history.deleted"))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
@require_subscription
async def summary_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("summary.this_week_button"), callback_data="sum_week"),
          InlineKeyboardButton(t("summary.this_month_button"), callback_data="sum_month")]]
    )
    await update.effective_message.reply_text(t("summary.pick_period"), reply_markup=kb)


def format_summary(data: dict) -> str:
    since = datetime.fromisoformat(data["from"])
    title = t("summary.this_month") if data["period"] == "month" else t("summary.this_week")
    c = data["currency"]
    lines = [
        t("summary.header", title=title, since=since),
        t("summary.income", amount=fmt(data["income_minor"], c)),
        t("summary.expenses", amount=fmt(data["expense_minor"], c)),
        t("summary.net", amount=fmt(data["net_minor"], c, sign=True)),
    ]
    if data["savings_rate"] is not None:
        lines.append(t("summary.savings_rate", rate=data["savings_rate"]))
    lines.append("")
    if data["by_category"]:
        lines.append(t("summary.by_category"))
        for cat in data["by_category"]:
            lines.append(t("summary.category_line", label=esc(cat["label"]), amount=fmt(cat["total_minor"], c),
                           count=cat["count"]))
    else:
        lines.append(t("summary.no_expenses"))
    return "\n".join(lines)


async def summary_text(user_id: int, period: str) -> str:
    return format_summary(await db_call(summaries.summary, user_id, period))


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    period = query.data.split("_", 1)[1]
    await query.edit_message_text(await summary_text(update.effective_user.id, period))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@require_subscription
async def accounts_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await accounts_screen(update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=kb)


async def accounts_screen(user_id: int):
    rows = await db_call(accounts.overview, user_id)
    c = (await db_call(prefs.get_prefs, user_id))["currency"]
    active = [r for r in rows if not r["archived"]]
    archived = [r for r in rows if r["archived"]]
    lines = [t("accounts.title")]
    for r in active:
        lines.append(t("accounts.line", label=esc(r["label"]), amount=fmt(r["balance_minor"], c))
                     + (t("accounts.default_mark") if r["is_default"] else ""))
    if archived:
        lines.append(t("accounts.archived"))
        lines += [t("accounts.line", label=esc(r["label"]), amount=fmt(r["balance_minor"], c)) for r in archived]
    if any(r["is_default"] for r in active):
        lines.append(t("accounts.default_note"))
    else:
        lines.append(t("accounts.no_default"))
    buttons = [
        [InlineKeyboardButton(t("accounts.transfer_button"), callback_data="acc:transfer"),
         InlineKeyboardButton(t("accounts.default_button"), callback_data="set_default_account_start")],
        [InlineKeyboardButton(t("accounts.add_button"), callback_data="acc:add"),
         InlineKeyboardButton(t("accounts.rename_button"), callback_data="acc:ren"),
         InlineKeyboardButton(t("accounts.archive_button"), callback_data="acc:arch")],
    ]
    if archived:
        buttons.append([InlineKeyboardButton(t("accounts.restore_button"), callback_data="acc:restore")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def set_default_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("accounts.pick_default"))
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t("accounts.choose_one"),
        reply_markup=account_keyboard(
            "setdefacc", await db_call(accounts.choices, update.effective_user.id),
            default=await db_call(accounts.get_default_account, update.effective_user.id), with_cancel=False
        ),
    )


async def set_default_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    try:
        await db_call(accounts.set_default_account, update.effective_user.id, account_key)
    except ValidationError as e:
        await query.edit_message_text(esc(e))
        return
    names = await db_call(accounts.names, update.effective_user.id)
    await query.edit_message_text(t("accounts.default_set", name=esc(names.get(account_key, account_key))))


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@require_subscription
async def budgets_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db_call(budgets.get_budgets, update.effective_user.id)
    lines = [t("budgets.title")]
    if rows:
        c = (await db_call(prefs.get_prefs, update.effective_user.id))["currency"]
        labels = await db_call(categories.names, update.effective_user.id, "expense")
        lines += [t("budgets.line", label=esc(labels.get(r["category"], label_for(r["category"], "expense"))),
                    amount=fmt(round(r["amount"] * 100), c)) for r in rows]
    else:
        lines.append(t("budgets.none"))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("budgets.set_button"), callback_data="set_budget_start")]])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


async def budget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_subscribed(context, query.from_user.id):
        await query.answer()
        await send_gate(update)
        return ConversationHandler.END
    clear_pending(context)
    await query.answer()
    await query.edit_message_text(t("budgets.pick_category"))
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=t("accounts.choose_one"),
        reply_markup=category_keyboard("budgetcat", await db_call(categories.choices, update.effective_user.id, "expense"))
    )
    return BUDGET_CATEGORY


async def budget_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_budget_category"] = category_key
    await query.edit_message_text(t(
        "flow.category_chosen", label=esc(await db_call(categories.label, update.effective_user.id, "expense", category_key))))
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t("budgets.type_limit"),
        reply_markup=cancel_keyboard(),
    )
    return BUDGET_AMOUNT


async def budget_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except ValueError as e:
        await update.message.reply_text(t("budgets.bad_amount", error=esc(e)))
        return BUDGET_AMOUNT
    category_key = context.user_data.pop("pending_budget_category")
    await db_call(budgets.set_budget, update.effective_user.id, category_key, amount)
    await update.message.reply_text(
        t("budgets.saved", label=esc(await db_call(categories.label, update.effective_user.id, "expense", category_key)),
          amount=fmt(to_minor(amount), (await db_call(prefs.get_prefs, update.effective_user.id))["currency"])),
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
def is_admin(update: Update) -> bool:
    admin = config.ADMIN_CHAT_ID
    return admin is not None and admin in (update.effective_user.id, update.effective_chat.id)


async def recap_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: send the admin's own last-week recap (/recap_now month: last month's)
    to ADMIN_CHAT_ID, nobody else."""
    if not is_admin(update):
        return
    kind = "monthly" if context.args and context.args[0].lower().startswith("month") else "weekly"
    start, end = periods.previous_month() if kind == "monthly" else periods.previous_week()
    text = await db_call(recap_text, update.effective_user.id, start, end, kind) or t(
        "admin.recap_empty", start=start, end=end)
    await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=text)


async def gate_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: is the gate on, the channels, whether the bot is admin in each, and
    how many users are in their free month or on each channel right now."""
    if not is_admin(update):
        return
    from app.bot.membership import channel_name, check_channels
    from app.services import gate

    lines = [t("gate.status_title", state=t("gate.status_on") if gate.enabled() else t("gate.status_off")), ""]
    rows = await check_channels(context.bot)
    counts = await db_call(gate.stats)
    if not rows:
        lines.append(t("gate.status_none"))
    for row, users_now in zip(rows, counts["channels"]):
        channel = row["channel"]
        admin = {True: "gate.status_admin_yes", False: "gate.status_admin_no", None: "gate.status_admin_unknown"}
        lines.append(t("gate.status_channel", number=channel.number, name=esc(channel_name(channel)),
                       chat_id=esc(channel.chat_id), admin=t(admin[row["admin"]]), users=users_now))
    lines += ["", t("gate.status_free", users=counts["free"]),
              t("gate.status_rules", free=gate.FREE_DAYS, period=gate.PERIOD_DAYS)]
    lines += [t("gate.status_problem", problem=esc(p)) for p in gate.problems()]
    await update.effective_message.reply_text("\n".join(lines))


async def backup_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: make a backup now and send it to ADMIN_CHAT_ID."""
    if not is_admin(update):
        return
    path = await run_backup(context.bot)
    await update.effective_message.reply_text(t("admin.backup_written", path=esc(path)))


RESTORE_MAX_BYTES = 20 * 1024 * 1024  # what a bot can download from Telegram


async def restore_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: a .db / .db.gz file sent with the caption /restore replaces the
    database (after a safety copy). Used to bring rescued data onto a new volume."""
    if not is_admin(update):
        return
    from app.services.backup import restore_live

    doc = update.message.document
    if doc.file_size and doc.file_size > RESTORE_MAX_BYTES:
        await update.message.reply_text(t("admin.restore_too_big"))
        return
    await update.message.reply_text(t("admin.restore_checking"))
    data = bytes(await (await doc.get_file()).download_as_bytearray())
    try:
        result = await db_call(restore_live, data)
    except ValueError as e:
        await update.message.reply_text(t("admin.restore_failed", error=esc(e)))
        return
    c = result["counts"]
    await update.message.reply_text(
        t("admin.restored", expenses=c["expenses"], users=c["users"], budgets=c["budgets"],
          migrations=len(result["migrations"]))
        + (t("admin.restore_safety_copy", path=esc(result["safety_copy"])) if result["safety_copy"] else "")
    )


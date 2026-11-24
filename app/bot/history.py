"""📋 History in the bot: one message, 10 entries a page, Newer / Older, a type
filter, and a number button per entry that opens it with Edit and Delete.

Pages use the same newest-first cursor as the Mini App. The cursors seen so
far are kept in user_data so ⬅️ Newer can step back; if they're gone (after a
restart) the list starts again from the newest.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.handlers import account_name, entry_line
from app.bot.keyboards import BTN_ADD, BTN_ADD_INCOME, esc
from app.bot.membership import require_subscription
from app.db import db_call
from app.services import periods, transactions
from app.services.money import fmt
from app.strings import t

PAGE = 10
FILTERS = [(key, t(f"history.{key}")) for key in ("all", "expense", "income", "transfer")]


def _line(n: int, e) -> str:
    day = periods.local_date_of(e["occurred_at"])
    if e["type"] == "transfer":
        what = t("history.transfer_what", amount=fmt(e["amount_minor"], e["currency"]),
                 from_account=esc(account_name(e)), to_account=esc(e.get("to_account_name") or e["to_account"]))
    else:
        signed = e["amount_minor"] if e["type"] == "income" else -e["amount_minor"]
        what = t("history.entry_what", amount=fmt(signed, e["currency"], sign=True), category=esc(e["category_name"]))
    note = t("history.note", note=esc(e["note"])) if e["note"] else ""
    return t("history.line", n=n, day=day, what=what, note=note)


async def render_page(context: ContextTypes.DEFAULT_TYPE, user_id: int, type_: str, index: int):
    """(text, keyboard) for page `index` of the list filtered by `type_`."""
    state = context.user_data.get("history")
    if not state or state.get("type") != type_ or index >= len(state["cursors"]):
        state = {"type": type_, "cursors": [None]}
        index = 0
    context.user_data["history"] = state
    entries, next_cursor = await db_call(
        transactions.list_entries, user_id, state["cursors"][index], None if type_ == "all" else type_, limit=PAGE
    )
    if next_cursor and len(state["cursors"]) == index + 1:
        state["cursors"].append(next_cursor)

    label = dict(FILTERS)[type_]
    if not entries:
        if type_ == "all":
            text = t("history.empty", add=BTN_ADD, add_income=BTN_ADD_INCOME)
        else:
            text = t(f"history.empty_{type_}")
    else:
        first = index * PAGE + 1
        text = "\n".join([t("history.header", label=label, first=first, last=first + len(entries) - 1), ""]
                         + [_line(first + i, e) for i, e in enumerate(entries)]
                         + ["", t("history.tap_number")])

    numbers = [InlineKeyboardButton(str(index * PAGE + i + 1), callback_data=f"hopen:{e['id']}:{type_}:{index}")
               for i, e in enumerate(entries)]
    rows = [numbers[:5], numbers[5:]]
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(t("history.newer"), callback_data=f"hpg:{type_}:{index - 1}"))
    if next_cursor:
        nav.append(InlineKeyboardButton(t("history.older"), callback_data=f"hpg:{type_}:{index + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(("• " if key == type_ else "") + name, callback_data=f"hpg:{key}:0")
                 for key, name in FILTERS])
    return text, InlineKeyboardMarkup([r for r in rows if r])


@require_subscription
async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("history", None)
    text, kb = await render_page(context, update.effective_user.id, "all", 0)
    await update.effective_message.reply_text(text, reply_markup=kb)


async def page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, type_, index = query.data.split(":")
    await query.answer()
    text, kb = await render_page(context, update.effective_user.id, type_, int(index))
    await query.edit_message_text(text, reply_markup=kb)


async def open_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, type_, index = query.data.split(":")
    entry = await db_call(transactions.get_entry, update.effective_user.id, int(entry_id))
    if entry is None:
        await query.answer(t("common.entry_deleted"), show_alert=True)
        text, kb = await render_page(context, update.effective_user.id, type_, int(index))
        await query.edit_message_text(text, reply_markup=kb)
        return
    await query.answer()
    back = f"hpg:{type_}:{index}"
    text = entry_line(entry).replace(t("entry.word_logged"), t("entry.word_entry"), 1)
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("history.edit"), callback_data=f"edit:{entry_id}"),
         InlineKeyboardButton(t("history.delete"), callback_data=f"hdel:{entry_id}:{type_}:{index}")],
        [InlineKeyboardButton(t("history.back_to_list"), callback_data=back)],
    ]))


async def delete_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, type_, index = query.data.split(":")
    ok = await db_call(transactions.delete_entry, update.effective_user.id, int(entry_id))
    await query.answer(t("history.deleted_toast") if ok else t("history.gone_toast"))
    # The list moved under the cursors; start the pages again at the same filter.
    context.user_data.pop("history", None)
    text, kb = await render_page(context, update.effective_user.id, type_, 0)
    await query.edit_message_text((t("history.deleted") + "\n\n" if ok else "") + text, reply_markup=kb)

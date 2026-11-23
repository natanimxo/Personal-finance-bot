"""📋 History in the bot: one message, 10 entries a page, Newer / Older, a type
filter, and a number button per entry that opens it with Edit and Delete.

Pages use the same newest-first cursor as the Mini App. The cursors seen so
far are kept in user_data so ⬅️ Newer can step back; if they're gone (after a
restart) the list starts again from the newest.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.handlers import account_name, entry_line
from app.bot.keyboards import BTN_ADD, BTN_ADD_INCOME, esc, label_for
from app.bot.membership import require_subscription
from app.db import db_call
from app.services import periods, transactions
from app.services.money import fmt

PAGE = 10
FILTERS = [("all", "All"), ("expense", "Expenses"), ("income", "Income"), ("transfer", "Transfers")]


def _line(n: int, e) -> str:
    day = f"{periods.local_date_of(e['occurred_at']):%d %b}"
    if e["type"] == "transfer":
        what = f"🔁 {fmt(e['amount_minor'], e['currency'])} {esc(account_name(e))} → " \
               f"{esc(e.get('to_account_name') or e['to_account'])}"
    else:
        signed = e["amount_minor"] if e["type"] == "income" else -e["amount_minor"]
        what = f"{fmt(signed, e['currency'], sign=True)} {esc(label_for(e['category'], e['type']))}"
    note = f" — {esc(e['note'])}" if e["note"] else ""
    return f"<b>{n}.</b> {day}  {what}{note}"


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
        text = ("📋 No transactions yet. Tap {} or {}, or just send <code>500 food lunch</code>.".format(BTN_ADD, BTN_ADD_INCOME)
                if type_ == "all" and index == 0 else f"📋 No {label.lower()} yet.")
    else:
        first = index * PAGE + 1
        text = "\n".join([f"📋 <b>{label}</b> · {first}–{first + len(entries) - 1}, newest first", ""]
                         + [_line(first + i, e) for i, e in enumerate(entries)]
                         + ["", "Tap a number to edit or delete it."])

    numbers = [InlineKeyboardButton(str(index * PAGE + i + 1), callback_data=f"hopen:{e['id']}:{type_}:{index}")
               for i, e in enumerate(entries)]
    rows = [numbers[:5], numbers[5:]]
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("⬅️ Newer", callback_data=f"hpg:{type_}:{index - 1}"))
    if next_cursor:
        nav.append(InlineKeyboardButton("Older ➡️", callback_data=f"hpg:{type_}:{index + 1}"))
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
        await query.answer("That entry was deleted.", show_alert=True)
        text, kb = await render_page(context, update.effective_user.id, type_, int(index))
        await query.edit_message_text(text, reply_markup=kb)
        return
    await query.answer()
    back = f"hpg:{type_}:{index}"
    await query.edit_message_text(entry_line(entry).replace("Logged", "Entry", 1), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{entry_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"hdel:{entry_id}:{type_}:{index}")],
        [InlineKeyboardButton("↩️ Back to the list", callback_data=back)],
    ]))


async def delete_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, type_, index = query.data.split(":")
    ok = await db_call(transactions.delete_entry, update.effective_user.id, int(entry_id))
    await query.answer("Deleted" if ok else "Already gone")
    # The list moved under the cursors; start the pages again at the same filter.
    context.user_data.pop("history", None)
    text, kb = await render_page(context, update.effective_user.id, type_, 0)
    await query.edit_message_text(("🗑️ Deleted.\n\n" if ok else "") + text, reply_markup=kb)

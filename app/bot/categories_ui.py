"""⚙️ Settings → 🏷️ Categories in the bot: add, rename, hide and unhide categories
for expenses and for income. Naming is typed (a step in the main flow handler)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import BTN_CANCEL, cancel_keyboard, esc, main_menu_keyboard
from app.db import db_call
from app.services import categories
from app.services.validation import ValidationError

CATEGORY_NAME = 70
TITLES = {"expense": "Expense", "income": "Income"}


async def screen(user_id: int, type_: str):
    items = await db_call(categories.list_categories, user_id, type_, True)
    visible = [c for c in items if not c["hidden"]]
    hidden = [c for c in items if c["hidden"]]
    other = "income" if type_ == "expense" else "expense"
    lines = [f"🏷️ <b>{TITLES[type_]} categories</b>", ""] + [f"• {esc(c['name'])}" for c in visible]
    if hidden:
        lines += ["", "<b>Hidden</b> (past entries still count in summaries):"] + [f"• {esc(c['name'])}" for c in hidden]
    rows = [
        [InlineKeyboardButton("➕ Add", callback_data=f"cat:add:{type_}"),
         InlineKeyboardButton("✏️ Rename", callback_data=f"cat:pick:ren:{type_}"),
         InlineKeyboardButton("🙈 Hide", callback_data=f"cat:pick:hide:{type_}")],
    ]
    if hidden:
        rows.append([InlineKeyboardButton("👁️ Show a hidden one", callback_data=f"cat:pick:show:{type_}")])
    rows.append([InlineKeyboardButton(f"↔️ {TITLES[other]} categories", callback_data=f"cat:list:{other}"),
                 InlineKeyboardButton("↩️ Settings", callback_data="set:back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def list_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    type_ = query.data.split(":")[2] if query.data.count(":") >= 2 else "expense"
    await query.answer()
    text, kb = await screen(update.effective_user.id, type_)
    await query.edit_message_text(text, reply_markup=kb)


async def pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, action, type_ = query.data.split(":")
    items = await db_call(categories.list_categories, update.effective_user.id, type_, True)
    wanted = [c for c in items if c["hidden"] == (action == "show")]
    titles = {"ren": "✏️ Rename which category?", "hide": "🙈 Hide which category? Its past entries still count.",
              "show": "👁️ Show which category again?"}
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"cat:{action}:{type_}:{c['key']}")] for c in wanted]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=f"cat:list:{type_}")])
    await query.answer()
    await query.edit_message_text(titles[action], reply_markup=InlineKeyboardMarkup(rows))


async def hide_or_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, type_, key = query.data.split(":", 3)
    try:
        await db_call(categories.set_hidden, update.effective_user.id, type_, key, action == "hide")
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    await query.answer("Hidden" if action == "hide" else "Visible again")
    text, kb = await screen(update.effective_user.id, type_)
    await query.edit_message_text(text, reply_markup=kb)


async def name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """cat:add:<type> or cat:ren:<type>:<key>"""
    query = update.callback_query
    parts = query.data.split(":", 3)
    type_ = parts[2]
    key = parts[3] if parts[1] == "ren" else None
    context.user_data["category_naming"] = {"type": type_, "key": key}
    await query.answer()
    if key:
        current = await db_call(categories.label, update.effective_user.id, type_, key)
        prompt = f"✏️ New name for {esc(current)}? Its past entries keep it. Emoji welcome, e.g. <i>🏠 Rent</i>."
    else:
        prompt = f"➕ Name the new {type_} category, e.g. <i>🏠 Rent</i> or <i>📚 School fees</i>."
    await query.edit_message_text(prompt)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"(Tap {BTN_CANCEL} to stop.)",
                                   reply_markup=cancel_keyboard())
    return CATEGORY_NAME


async def name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    naming = context.user_data.get("category_naming")
    if not naming:
        return ConversationHandler.END
    try:
        if naming["key"]:
            c = await db_call(categories.rename_category, update.effective_user.id, naming["type"], naming["key"],
                              update.message.text)
            done = f"✅ Renamed to {esc(c['name'])}."
        else:
            c = await db_call(categories.add_category, update.effective_user.id, naming["type"], update.message.text)
            done = f"✅ Added {esc(c['name'])}."
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} Try another name, or tap {BTN_CANCEL}.")
        return CATEGORY_NAME
    context.user_data.pop("category_naming", None)
    await update.message.reply_text(done, reply_markup=main_menu_keyboard())
    text, kb = await screen(update.effective_user.id, naming["type"])
    await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END

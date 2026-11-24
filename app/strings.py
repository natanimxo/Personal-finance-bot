"""Every piece of text the bot (and the API) shows to users, in one place.

Code never writes user-facing text inline: it calls t("key", name=value). To
translate the bot, copy EN to a new table (say FR), translate the values and
keep the {placeholders}, then add it to LANGUAGES. The keys are grouped by
screen. Values are Telegram HTML: keep the tags, and pass dynamic values in
already escaped (the callers do).

Placeholders use str.format, so dates can carry their own format:
"{day:%a %d %b}". tests/test_strings.py checks every key the code uses exists,
and that every translation has the same keys and placeholders as EN.
"""
import string

EN = {}

# --- the main menu -------------------------------------------------------------------
EN.update({
    "menu.add": "➕ Add Expense",
    "menu.add_income": "💵 Add Income",
    "menu.history": "📋 History",
    "menu.summary": "📊 Summary",
    "menu.budgets": "💰 Budgets",
    "menu.accounts": "🏦 Accounts",
    "menu.help": "❓ Help",
    "menu.settings": "⚙️ Settings",
    "menu.cancel": "❌ Cancel",
    "menu.open_app": "📱 Open app",
    "menu.button": "Open app",  # Telegram's menu button next to the message box
    "menu.hint": "👇 Menu",
})

# --- words and replies used on many screens ------------------------------------------
EN.update({
    "common.back": "↩️ Back",
    "common.try_again": "{error} Try again, or tap {cancel}.",
    "common.try_another_name": "{error} Try another name, or tap {cancel}.",
    "common.tap_cancel": "(Tap {cancel} to stop.)",
    "common.entry_deleted": "That entry was deleted.",
    "common.saved": "Saved",
    "common.saved_line": "✅ Saved.",
    "common.ok": "👍",
    "common.on": "on",
    "common.off": "off",
})

# --- first start: currency and timezone ----------------------------------------------
EN.update({
    "onboard.currency": (
        "👋 <b>Welcome!</b> Two quick questions so your numbers look right.\n\n"
        "<b>1/2 · 💱 Which currency do you use?</b>\n"
        "Pick one below, or tap ✏️ Other to type any 3-letter code."
    ),
    "onboard.other_currency": "✏️ Other",
    "onboard.type_currency": "✏️ Type your 3-letter currency code, e.g. <code>USD</code>, <code>EUR</code> or <code>INR</code>.",
    "onboard.currency_set": "✅ Currency: <b>{code}</b> (amounts look like {example})",
    "onboard.timezone": (
        "<b>2/2 · 🕐 What's your timezone?</b>\n"
        "It decides when your week and month start and when recaps arrive.\n\n"
        "Tap <b>📍 Share my location</b> below, pick from the list, or type a city "
        "(<code>London</code>, <code>Lagos</code>) or an offset (<code>UTC+3</code>)."
    ),
    "onboard.share_location": "📍 Share my location",
    "onboard.pick_region": "Or pick a region:",
    "onboard.pick_zone": "🕐 Pick your city (or one with the same time):",
    "onboard.regions": "↩️ Regions",
    "onboard.unknown_timezone": (
        "I couldn't find that timezone. Type a city like <code>Berlin</code> or <code>New York</code>, "
        "an offset like <code>UTC-5</code>, or tap 📍 Share my location."
    ),
    "onboard.timezone_set": "✅ Timezone: <b>{zone}</b> ({offset}, it's {time} there now)",
    "onboard.fixed_offset": " · a fixed offset, so no daylight saving",
    "onboard.done": "🎉 All set! Your week starts on Monday and recaps arrive at 08:00 your time.",
    "region.africa": "🌍 Africa",
    "region.americas": "🌎 Americas",
    "region.asia": "🌏 Asia",
    "region.europe": "🇪🇺 Europe",
    "region.oceania": "🌊 Oceania",
    "region.utc": "UTC",
})

# --- /start and Help -----------------------------------------------------------------
EN.update({
    "start.welcome": (
        "👋 <b>Welcome!</b>\n\n"
        "I'm your expense tracker. Everything works through the buttons below "
        "— no typing commands needed.\n\n"
        "{add} — log a spend in 3 taps\n"
        "{add_income} — log income in 3 taps\n"
        "{history} — see your recent transactions\n"
        "{summary} — income, expenses, net and savings rate\n"
        "{budgets} — set spending limits &amp; get warned\n"
        "{accounts} — balances per account; add, rename or archive accounts\n"
        "{settings} — currency, timezone, recaps, categories, recurring entries, export\n\n"
        "I'll also message you every Monday at 08:00 your time with last week's recap, "
        "and on the 1st with last month's."
    ),
    "help.text": (
        "<b>How this works</b>\n\n"
        "1️⃣ Tap {add} or {add_income}\n"
        "2️⃣ Type the amount\n"
        "3️⃣ Tap a category button\n"
        "4️⃣ Tap an account. If you set a ⭐ default account, this step is skipped\n"
        "5️⃣ Add a note, or skip it\n\n"
        "Changed your mind? Tap {cancel} at any step, or any menu button.\n\n"
        "Use the other buttons any time to check your history, totals, or budgets.\n\n"
        "Faster: just send <code>500 food lunch</code> or <code>+2000 salary</code>."
    ),
})

# --- the add-expense / add-income flow -----------------------------------------------
EN.update({
    "flow.ask_expense": "💵 How much did you spend? (just type the number, e.g. 12.50)",
    "flow.ask_income": "💵 How much did you receive? (just type the number, e.g. 500)",
    "flow.example_expense": "12.50",
    "flow.example_income": "500",
    "flow.bad_amount": "{error} Try again, e.g. {example}",
    "flow.pick_category": "Pick a category:",
    "flow.note_prompt": "📅 Date: <b>{when}</b>\nWant to add a quick note? Type it, or tap Skip.",
    "flow.today": "today",
    "flow.day": "{day:%a %d %b %Y}",
    "flow.type_date": "📅 Type the date, e.g. <code>22/11</code> or <code>2026-11-22</code>.",
    "flow.category_chosen": "Category: {label}",
    "flow.which_account": "Which account?",
    "flow.account_chosen": "Account: {name}",
    "flow.note_too_long": "Notes can be up to {max} characters; yours has {length}. Send a shorter one, or tap Skip.",
    "flow.no_note": "⏭️ No note added.",
    "flow.cancelled_inline": "❌ Cancelled.",
    "flow.cancelled": "Cancelled. Nothing was saved.",
    "flow.nothing_to_cancel": "Nothing to cancel.",
    "flow.timed_out": "⌛ That entry timed out and wasn't saved.",
    "flow.dropped": "↩️ Unfinished entry dropped.",
    "date.today": "Today",
    "date.yesterday": "Yesterday",
    "date.other": "📅 Other date",
    "flow.skip": "⏭️ Skip",
})

# --- one saved entry -----------------------------------------------------------------
EN.update({
    "entry.moved": "🔁 Moved {amount} — {from_account} → {to_account}",
    "entry.logged": "{icon} Logged {amount} — {category} ({account})",
    "entry.date_line": "\n📅 {day:%a %d %b %Y}",
    "entry.note_line": "\n📝 {note}",
    "entry.word_logged": "Logged",
    "entry.word_saved": "Saved",
    "entry.word_entry": "Entry",
    "entry.transfer_category": "🔁 Transfer",
    "entry.change_account": "🔁 Change account",
    "entry.moved_to": "Moved to {name}",
    "budget.over": "🚨 You're over budget on {label}: {used}",
    "budget.near": "⚠️ {percent}% of your {label} budget used ({used})",
})

# --- 📊 Summary -----------------------------------------------------------------------
EN.update({
    "summary.pick_period": "Pick a period:",
    "summary.this_week_button": "This Week",
    "summary.this_month_button": "This Month",
    "summary.this_week": "This week",
    "summary.this_month": "This month",
    "summary.header": "📊 <b>{title}</b> (since {since:%a %d %b})",
    "summary.income": "💵 Income: {amount}",
    "summary.expenses": "💸 Expenses: {amount}",
    "summary.net": "⚖️ Net: {amount}",
    "summary.savings_rate": "💹 Savings rate: {rate:.0f}%",
    "summary.by_category": "<b>Expenses by category:</b>",
    "summary.category_line": "• {label}: {amount} ({count}x)",
    "summary.no_expenses": "No expenses in this period.",
})

# --- 🏦 Accounts and transfers ---------------------------------------------------------
EN.update({
    "accounts.title": "🏦 <b>Account balances:</b>",
    "accounts.line": "• {label}: {amount}",
    "accounts.default_mark": " ⭐",
    "accounts.archived": "\n<b>Archived:</b>",
    "accounts.default_note": "\n⭐ = your default account. New entries go there without asking.",
    "accounts.no_default": "\nSet a default account and new entries skip the account step.",
    "accounts.transfer_button": "🔁 Transfer",
    "accounts.default_button": "⭐ Set default",
    "accounts.add_button": "➕ Add",
    "accounts.rename_button": "✏️ Rename",
    "accounts.archive_button": "🗄️ Archive",
    "accounts.restore_button": "♻️ Restore an archived account",
    "accounts.pick_default": "Pick your default account:",
    "accounts.choose_one": "Choose one:",
    "accounts.default_set": "⭐ Default account set to {name}",
    "accounts.which_restore": "♻️ Which account do you want back?",
    "accounts.which_rename": "✏️ Which account do you want to rename?",
    "accounts.which_archive": "🗄️ Which account do you want to archive? Its history and balance stay.",
    "accounts.archived_toast": "Archived",
    "accounts.restored_toast": "Restored",
    "accounts.archived_done": "🗄️ Archived {name}.",
    "accounts.restored_done": "♻️ {name} is back.",
    "accounts.new_prompt": "➕ What's the new account called? (e.g. <i>Savings</i> or <i>PayPal</i>)",
    "accounts.rename_prompt": "✏️ New name for {name}? Its history and balance stay.",
    "accounts.added": "✅ Added {name}.",
    "accounts.renamed": "✅ Renamed to {name}.",
    "transfer.need_two": "You need two accounts to move money between. Add one first.",
    "transfer.from": "🔁 <b>Transfer</b>\nMove money <b>from</b> which account?",
    "transfer.to": "🔁 From <b>{name}</b> <b>to</b> which account?",
    "transfer.pair": "🔁 {from_account} → {to_account}",
    "transfer.how_much": "How much? (e.g. 500)",
})

# --- 💰 Budgets -------------------------------------------------------------------------
EN.update({
    "budgets.title": "💰 <b>Your monthly budgets:</b>",
    "budgets.line": "• {label}: {amount}",
    "budgets.none": "None set yet.",
    "budgets.set_button": "➕ Set a budget",
    "budgets.pick_category": "Pick a category to set a budget for:",
    "budgets.type_limit": "Type the monthly limit, e.g. 200",
    "budgets.bad_amount": "{error} Try again, e.g. 200",
    "budgets.saved": "✅ Budget for {label} set to {amount} a month",
})

# --- 📋 History ----------------------------------------------------------------------
EN.update({
    "history.all": "All",
    "history.expense": "Expenses",
    "history.income": "Income",
    "history.transfer": "Transfers",
    "history.empty": "📋 No transactions yet. Tap {add} or {add_income}, or just send <code>500 food lunch</code>.",
    "history.empty_expense": "📋 No expenses yet.",
    "history.empty_income": "📋 No income yet.",
    "history.empty_transfer": "📋 No transfers yet.",
    "history.header": "📋 <b>{label}</b> · {first}–{last}, newest first",
    "history.tap_number": "Tap a number to edit or delete it.",
    "history.line": "<b>{n}.</b> {day:%d %b}  {what}{note}",
    "history.transfer_what": "🔁 {amount} {from_account} → {to_account}",
    "history.entry_what": "{amount} {category}",
    "history.note": " — {note}",
    "history.newer": "⬅️ Newer",
    "history.older": "Older ➡️",
    "history.edit": "✏️ Edit",
    "history.delete": "🗑️ Delete",
    "history.back_to_list": "↩️ Back to the list",
    "history.deleted": "🗑️ Deleted.",
    "history.deleted_toast": "Deleted",
    "history.gone_toast": "Already gone",
})

# --- ✏️ Editing an entry -----------------------------------------------------------------
EN.update({
    "edit.to": "➡️ To",
    "edit.category": "🏷️ Category",
    "edit.amount": "💵 Amount",
    "edit.from": "⬅️ From",
    "edit.account": "🏦 Account",
    "edit.date": "📅 Date",
    "edit.note": "📝 Note",
    "edit.repeat": "🔁 Repeat",
    "edit.done": "✅ Done",
    "edit.editing": "✏️ <b>Editing</b>\n{line}{extra}\n\nWhat do you want to change?",
    "edit.prompt_amount": "Type the new amount (now {amount}).",
    "edit.prompt_note": "Type the new note (up to {max} characters), or send <code>-</code> to clear it.",
    "edit.prompt_date": "Type the date it happened, e.g. <code>22/11</code> or <code>2026-11-22</code>.",
})

# --- quick entry ("500 food lunch") -------------------------------------------------------
EN.update({
    "quick.undo": "↩️ Undo",
    "quick.bad": "{error} For example: <code>500 food lunch</code>",
    "quick.which_category": "{amount}: which category?",
    "quick.not_waiting": "That entry is no longer waiting. Send it again.",
    "quick.already_removed": "Already removed.",
    "quick.undone_toast": "Undone",
    "quick.undone": "↩️ Undone: {line}",
})

# --- 🔁 Recurring entries ------------------------------------------------------------------
EN.update({
    "recurring.weekly": "Weekly",
    "recurring.monthly": "Monthly",
    "recurring.every_weekly": "every week",
    "recurring.every_monthly": "every month",
    "recurring.repeating_toast": "Repeating",
    "recurring.now_repeats": (
        "🔁 This now repeats {every}. The next one is logged on {day:%a %d %b %Y}.\n"
        "Manage repeats in ⚙️ Settings → 🔁 Recurring."
    ),
    "recurring.rule_line": "{amount} {label}{note}, {every} (next {day:%d %b})",
    "recurring.title": "🔁 <b>Recurring entries</b>",
    "recurring.empty": (
        "🔁 <b>Recurring entries</b>\n\nNone yet. To repeat an entry (rent, salary, a subscription), "
        "open it from 📋 History → ✏️ Edit → 🔁 Repeat."
    ),
    "recurring.stop": "🗑️ Stop #{n}",
    "recurring.stopped": "Stopped. Past entries stay.",
    "recurring.already_stopped": "Already stopped.",
    "recurring.logged": "🔁 <b>Recurring</b>\n{line}",
})

# --- ⚙️ Settings ---------------------------------------------------------------------------
EN.update({
    "settings.screen": (
        "⚙️ <b>Settings</b>\n\n"
        "💱 Currency: <b>{currency}</b> (amounts look like {example})\n"
        "🕐 Timezone: <b>{zone}</b> ({offset}, now {time})\n"
        "🔔 Weekly recap (Monday 08:00): <b>{weekly}</b>\n"
        "🗓️ Monthly recap (the 1st): <b>{monthly}</b>"
    ),
    "settings.not_set": "not set",
    "settings.currency_button": "💱 Change currency",
    "settings.timezone_button": "🕐 Change timezone",
    "settings.weekly_button": "🔔 Weekly recap {state}",
    "settings.monthly_button": "🗓️ Monthly recap {state}",
    "settings.categories_button": "🏷️ Categories",
    "settings.recurring_button": "🔁 Recurring entries",
    "settings.export_button": "📤 Export CSV",
    "settings.pick_currency": "💱 Pick your currency:",
    "settings.another_code": "✏️ Another code",
    "settings.currency_toast": "Currency: {code}",
    "settings.currency_set": "✅ Currency set to {code}.",
    "settings.weekly_on": "Weekly recap on",
    "settings.weekly_off": "Weekly recap off",
    "settings.monthly_on": "Monthly recap on",
    "settings.monthly_off": "Monthly recap off",
    "settings.type_currency": "✏️ Type the 3-letter currency code, e.g. <code>USD</code> or <code>MXN</code>.",
    "settings.export_caption": "📤 All your entries. Opens in Excel and Google Sheets.",
    "settings.export_preparing": "Preparing your file…",
})

# --- 🏷️ Categories -----------------------------------------------------------------------
EN.update({
    "categories.expense": "Expense",
    "categories.income": "Income",
    "categories.title": "🏷️ <b>{kind} categories</b>",
    "categories.line": "• {name}",
    "categories.hidden": "<b>Hidden</b> (past entries still count in summaries):",
    "categories.add_button": "➕ Add",
    "categories.rename_button": "✏️ Rename",
    "categories.hide_button": "🙈 Hide",
    "categories.show_button": "👁️ Show a hidden one",
    "categories.other_button": "↔️ {kind} categories",
    "categories.settings_button": "↩️ Settings",
    "categories.which_rename": "✏️ Rename which category?",
    "categories.which_hide": "🙈 Hide which category? Its past entries still count.",
    "categories.which_show": "👁️ Show which category again?",
    "categories.hidden_toast": "Hidden",
    "categories.visible_toast": "Visible again",
    "categories.rename_prompt": "✏️ New name for {name}? Its past entries keep it. Emoji welcome, e.g. <i>🏠 Rent</i>.",
    "categories.new_prompt_expense": "➕ Name the new expense category, e.g. <i>🏠 Rent</i> or <i>📚 School fees</i>.",
    "categories.new_prompt_income": "➕ Name the new income category, e.g. <i>🏠 Rent</i> or <i>📚 School fees</i>.",
    "categories.added": "✅ Added {name}.",
    "categories.renamed": "✅ Renamed to {name}.",
})

# --- the channel gate ----------------------------------------------------------------------
EN.update({
    "gate.text": (
        "🔒 <b>This period's channel: {name} — {days} days left</b>\n\n"
        "The bot is free. Every 30 days there's one channel everyone needs to be in, "
        "and you only need the current one.\n\n"
        "Tap 📢 Join, then ✅ I've joined."
    ),
    "gate.text_left": (
        "🔒 <b>You left {name}.</b> Rejoin to keep using the bot.\n\n"
        "This period's channel: {name} — {days} days left. Your entries are all still here.\n\n"
        "Tap 📢 Join, then ✅ I've joined."
    ),
    "gate.join": "📢 Join {name}",
    "gate.subscribed": "✅ I've joined",
    "gate.youre_in": "You're in! 🎉",
    "gate.confirmed": "✅ You're in this period's channel. Here's your menu 👇",
    "gate.get_started": "Tap a button to get started.",
    "gate.still_not": "Not in this period's channel yet. Join it first, then tap ✅ again.",
    "gate.alert_not_admin": (
        "⚠️ <b>Channel gate</b>: the bot isn't an administrator of {channels} (or can't see the "
        "channel at all), so it can't check who joined. Users are let through until you add the bot "
        "as an admin there."
    ),
    "gate.alert_no_invite": (
        "⚠️ <b>Channel gate</b>: the bot can't make an invite link for {channels}. Give it the "
        "\"Invite users via link\" admin right there, then send /gate_on again. Until then the join "
        "screen has no Join button."
    ),
    "gate.status_title": "🔐 <b>Channel gate</b>: {state}",
    "gate.status_on": "on",
    "gate.status_off": "off (nobody is checked; /gate_on to start)",
    "gate.stats_title": "📈 <b>Channel gate, last {days} day(s)</b>",
    "gate.stats_how": "Send /gate_stats followed by a number of days, e.g. <code>/gate_stats 30</code>.",
    "gate.list_line": "{number}. {title} (<code>{chat_id}</code>) · bot admin {admin} · invite link {invite}",
    "gate.yes": "✅",
    "gate.no": "❌",
    "gate.unknown": "❓",
    "gate.count_title": "<b>{number}. {title}</b>",
    "gate.count_line": (
        "   required now {required} · shown {shown} · joined via bot {joined_via_bot} · "
        "already members {already_member} · left {left} · rejoined {rejoined} · subscribed now {subscribed}"
    ),
    "gate.rules": (
        "One schedule for everyone, no free period: each {period}-day period has one channel, "
        "in list order from the start channel, round again."
    ),
    "gate.current": (
        "📅 <b>Now:</b> {title} · period {n}, {start:%d %b %Y %H:%M} – {end:%d %b %Y %H:%M}, {days} days left\n"
        "⏭️ <b>Next:</b> {next}"
    ),
    "gate.schedule_title": "🗓️ <b>Channel schedule</b> (times in {zone})",
    "gate.schedule_line": "{n}. {title}: {start:%d %b %Y %H:%M} – {end:%d %b %Y %H:%M}",
    "gate.schedule_now": " ← now, {days} days left",
    "gate.list_empty": "No channels yet. Forward a post from a channel to me, then reply to it with /gate_add.",
    "gate.list_help": "/gate_schedule · /gate_status · /gate_stats n · /gate_add (reply to a forwarded channel post) · /gate_remove n · /gate_on · /gate_off",
    "gate.add_how": "Forward any post from the channel to me, then reply to that forwarded post with /gate_add. (Or: /gate_add -100…)",
    "gate.add_not_numeric": "Channels are added by their numeric id, like <code>-1001234567890</code>. Forward a post from the channel and reply to it with /gate_add.",
    "gate.add_already": "That channel is already in the rotation.",
    "gate.add_full": "The rotation already has {max} channels. Remove one first with /gate_remove n.",
    "gate.add_not_admin": "❌ I'm not an administrator of {title} (<code>{chat_id}</code>), so I can't check who joined. Add me as an admin there, then try again.",
    "gate.added": "✅ Added {title} (<code>{chat_id}</code>) as channel {number}.",
    "gate.remove_how": "Send /gate_remove followed by the channel's number from /gate_list, e.g. <code>/gate_remove 2</code>.",
    "gate.removed": "🗑️ Removed {title} (<code>{chat_id}</code>). The channels after it moved up.",
    "gate.turned_on": "🔐 Channel gate is <b>on</b>.",
    "gate.turned_off": "🔓 Channel gate is <b>off</b>. Nobody is checked.",
    "gate.on_without_channels": "⚠️ There are no channels yet, so nobody is checked until you add one with /gate_add.",
})

# --- recaps --------------------------------------------------------------------------------
EN.update({
    "recap.monthly_title": "🗓️ <b>Your {start:%B} recap</b>",
    "recap.weekly_title": "📊 <b>Your weekly recap</b> ({start:%a %d %b} – {last:%a %d %b})",
    "recap.week": "week",
    "recap.month": "month",
    "recap.same": " (same as the {period} before)",
    "recap.up": " (↑ {pct}% vs the {period} before)",
    "recap.down": " (↓ {pct}% vs the {period} before)",
    "recap.income": "💵 Income: {amount}{change}",
    "recap.expenses": "💸 Expenses: {amount}{change}",
    "recap.net": "⚖️ Net: {amount}",
    "recap.savings_rate": "💹 Savings rate: {rate:.0f}%",
    "recap.top": "🏆 Top category: {label}, {amount} ({share}% of spending)",
    "recap.all_categories": "<b>All categories:</b>",
    "recap.category_line": "• {label}: {amount} ({count}x)",
})

# --- admin commands, backups and alerts ----------------------------------------------------
EN.update({
    "admin.recap_empty": "📊 Recap preview: nothing logged between {start:%a %d %b} and {end:%a %d %b}.",
    "admin.backup_written": "🗄️ Backup written: <code>{path}</code>",
    "admin.backup_caption": "🗄️ Database backup {name} ({size_kb:.0f} KB before compression)",
    "admin.restore_too_big": "That file is over 20 MB, which bots can't download. Use the restore command on the server.",
    "admin.restore_checking": "⏳ Checking the file…",
    "admin.restore_failed": "❌ Not restored: {error}. Nothing was changed.",
    "admin.restored": "✅ Restored: {expenses} entries, {users} users, {budgets} budgets.\nMigrations applied: {migrations}.\n",
    "admin.restore_safety_copy": "The previous database was saved first: <code>{path}</code>",
    "admin.error_alert": "⚠️ <b>Bot error</b>{where}\n<code>{error}</code>{skipped}\nFull traceback in the Railway logs.",
    "admin.error_where": " (user {user_id})",
    "admin.error_skipped": "\n{n} more error(s) since the last alert.",
})

# --- rules shared by the bot and the Mini App (validation errors) --------------------------
EN.update({
    "error.not_amount": "That doesn't look like an amount.",
    "error.amount_zero": "The amount has to be more than 0.",
    "error.decimals": "Use at most 2 decimal places.",
    "error.amount_max": "That's more than the maximum of {max:,}.",
    "error.invalid_amount": "Invalid amount.",
    "error.type": "Type must be expense or income.",
    "error.note_length": "Notes can be up to {max} characters.",
    "error.currency": "Currency must be a 3-letter code, like USD or EUR.",
    "error.timezone": "Unknown timezone. Use a name like Europe/Berlin, or a city.",
    "error.date_format": "Use a date like 22/11 or 2026-11-22.",
    "error.date_future": "The date can't be in the future.",
    "error.date_too_old": "That date is too far back.",
    "error.unknown_account": "Unknown account.",
    "error.account_name_empty": "Give the account a name.",
    "error.account_name_length": "Account names can be up to {max} characters.",
    "error.account_name_taken": "You already have an account with that name.",
    "error.account_limit": "You can have up to {max} accounts.",
    "error.last_account": "You need at least one account that isn't archived.",
    "error.same_accounts": "Pick two different accounts.",
    "error.transfer_type": "A transfer can't become income or an expense (or the other way).",
    "error.unknown_category_expense": "Unknown expense category.",
    "error.unknown_category_income": "Unknown income category.",
    "error.unknown_category": "Unknown category.",
    "error.category_name_empty": "Give the category a name.",
    "error.category_name_length": "Category names can be up to {max} characters.",
    "error.category_name_taken": "You already have a category with that name.",
    "error.category_limit_expense": "You can have up to {max} expense categories.",
    "error.category_limit_income": "You can have up to {max} income categories.",
    "error.last_category": "Keep at least one category visible.",
    "error.repeat": "Repeat weekly or monthly.",
    "error.no_entry": "No such entry.",
    "error.repeat_type": "Only income and expenses can repeat.",
    "error.rule_limit": "You can have up to {max} recurring entries.",
    "error.no_rule": "No such recurring entry.",
    "error.cursor": "Invalid cursor.",
})

# --- the Mini App's API ------------------------------------------------------------------------
EN.update({
    "api.open_from_telegram": "Open this page from the bot in Telegram.",
    "api.session_expired": "Your session is invalid or expired. Reopen the app.",
    "api.bad_dates": "Dates must look like 2026-11-23.",
    "api.quick_needs_amount": "Start with an amount, like: 500 food lunch",
    "api.server_error": "Something went wrong. Try again.",
})

# --- the CSV export --------------------------------------------------------------------------------
EN.update({
    "csv.header": "Date,Type,Category,Account,To account,Amount,Currency,Note",
    "csv.transfer": "Transfer",
    "csv.expense": "Expense",
    "csv.income": "Income",
    "csv.filename": "expenses-{day}.csv",
})

LANGUAGES = {"en": EN}
DEFAULT_LANGUAGE = "en"


def t(key: str, lang: str = None, **values) -> str:
    """The text for `key`, with {placeholders} filled in. Falls back to English for
    a key a translation hasn't covered yet."""
    table = LANGUAGES.get(lang or DEFAULT_LANGUAGE, EN)
    text = table.get(key)
    if text is None:
        text = EN[key]  # a KeyError here means a typo in the key: tests/test_strings.py catches it
    return text.format(**values) if values else text


def placeholders(text: str) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}

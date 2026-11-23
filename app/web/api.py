"""JSON API for the Mini App. Every endpoint is scoped to the user proven by initData."""
import logging
from types import SimpleNamespace
from typing import Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import config
from app.bot.handlers import budget_warning_text
from app.bot.membership import is_subscribed, touch_user
from app.db import db_call
from app.services import accounts, budgets, catalog, periods, prefs, quick_entry, summaries, transactions
from app.services.validation import ValidationError, check_category, parse_amount_minor
from app.web.auth import InitDataError, validate_init_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

Amount = Union[str, float, int]


class CurrentUser(SimpleNamespace):
    id: int


async def current_user(request: Request, authorization: str = Header(default="")) -> CurrentUser:
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != "tma" or not init_data:
        raise HTTPException(401, detail={"error": "Open this page from the bot in Telegram."})
    try:
        tg_user = validate_init_data(init_data, config.BOT_TOKEN)
    except InitDataError as e:
        raise HTTPException(401, detail={"error": "Your session is invalid or expired. Reopen the app.", "reason": str(e)})
    user_id = int(tg_user["id"])
    bot = request.app.state.application.bot
    if not await is_subscribed(SimpleNamespace(bot=bot), user_id):
        raise HTTPException(403, detail={"error": "not_subscribed", "join_link": config.CHANNEL_INVITE_LINK})
    await touch_user(user_id)
    return CurrentUser(id=user_id, first_name=tg_user.get("first_name", ""), username=tg_user.get("username"))


def entry_json(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "amount_minor": entry["amount_minor"],
        "type": entry["type"],
        "category": entry["category"],
        "category_label": "🔁 Transfer" if entry["type"] == "transfer" else catalog.label_for(entry["category"], entry["type"]),
        "account": entry["account"],
        "account_label": entry.get("account_name") or catalog.account_label(entry["account"]),
        "to_account": entry.get("to_account"),
        "to_account_label": (entry.get("to_account_name") or catalog.account_label(entry["to_account"]))
        if entry.get("to_account") else None,
        "note": entry["note"] or "",
        "created_at": entry["created_at"] + "Z",  # stored as naive UTC
        "occurred_at": entry["occurred_at"] + "Z",
        "date": periods.local_date_of(entry["occurred_at"]).isoformat(),  # local date it happened
    }


async def notify_warning(request: Request, user_id: int, warning):
    """A budget warning from the Mini App also arrives as a bot message, like in the bot."""
    if not warning:
        return
    try:
        await request.app.state.application.bot.send_message(chat_id=user_id, text=budget_warning_text(warning))
    except Exception as e:
        logger.warning(f"Couldn't send budget warning to {user_id}: {e}")


def validation_response(e: ValidationError):
    return JSONResponse(status_code=422, content={"error": str(e), "field": e.field})


# --- me / summary -------------------------------------------------------------
@router.get("/me")
async def me(user: CurrentUser = Depends(current_user)):
    settings = await db_call(prefs.get_prefs, user.id)
    catalog_json = catalog.as_json()
    return {
        "user": {"id": user.id, "first_name": user.first_name, "username": user.username},
        "settings": settings,
        "types": catalog_json["types"],
        "categories": catalog_json["categories"],
        # Every account with its label, balance and default flag.
        "accounts": await db_call(accounts.overview, user.id),
        "default_account": await db_call(accounts.get_default_account, user.id),
    }


@router.get("/summary")
async def summary(period: str = Query("week", pattern="^(week|month)$"),
                  date_from: Optional[str] = Query(None, alias="from"),
                  date_to: Optional[str] = Query(None, alias="to"),
                  user: CurrentUser = Depends(current_user)):
    try:
        return await db_call(summaries.summary, user.id, period, date_from, date_to)
    except ValueError:
        raise HTTPException(422, detail={"error": "Dates must look like 2026-11-23."})


# --- transactions ----------------------------------------------------------------
class NewEntry(BaseModel):
    amount: Amount
    type: str = "expense"
    category: str
    account: Optional[str] = None
    note: Optional[str] = ""
    date: Optional[str] = None  # local YYYY-MM-DD it happened; default today


class EntryChanges(BaseModel):
    amount: Optional[Amount] = None
    type: Optional[str] = None
    category: Optional[str] = None
    account: Optional[str] = None
    to_account: Optional[str] = None  # transfers only
    note: Optional[str] = None
    date: Optional[str] = None


class NewTransfer(BaseModel):
    amount: Amount
    from_account: str
    to_account: str
    note: Optional[str] = ""
    date: Optional[str] = None


@router.get("/transactions")
async def list_transactions(cursor: Optional[str] = None, type: Optional[str] = None,
                            category: Optional[str] = None, account: Optional[str] = None,
                            date_from: Optional[str] = Query(None, alias="from"),
                            date_to: Optional[str] = Query(None, alias="to"),
                            q: Optional[str] = None, user: CurrentUser = Depends(current_user)):
    try:
        items, next_cursor = await db_call(
            transactions.list_entries, user.id, cursor, type or None, category or None, account or None,
            date_from or None, date_to or None, (q or "").strip() or None,
        )
    except ValidationError as e:
        return validation_response(e)
    except ValueError:
        raise HTTPException(422, detail={"error": "Dates must look like 2026-11-23."})
    return {"items": [entry_json(e) for e in items], "next_cursor": next_cursor}


@router.post("/transactions", status_code=201)
async def create_transaction(body: NewEntry, request: Request, user: CurrentUser = Depends(current_user)):
    try:
        amount_minor = parse_amount_minor(body.amount)
        account = body.account or await db_call(accounts.fallback_account, user.id)
        entry, warning = await db_call(
            transactions.add_entry, user.id, amount_minor, body.type, body.category, account, body.note or "",
            body.date or None,
        )
    except ValidationError as e:
        return validation_response(e)
    await notify_warning(request, user.id, warning)
    return {"entry": entry_json(entry), "warning": warning}


@router.post("/transfers", status_code=201)
async def create_transfer(body: NewTransfer, user: CurrentUser = Depends(current_user)):
    """Move money between two of the user's accounts (not income, not an expense)."""
    try:
        entry = await db_call(transactions.add_transfer, user.id, parse_amount_minor(body.amount),
                              body.from_account, body.to_account, body.note or "", body.date or None)
    except ValidationError as e:
        return validation_response(e)
    return {"entry": entry_json(entry), "warning": None}


@router.patch("/transactions/{entry_id}")
async def edit_transaction(entry_id: int, body: EntryChanges, request: Request,
                           user: CurrentUser = Depends(current_user)):
    try:
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        if "amount" in changes:
            changes["amount_minor"] = parse_amount_minor(changes.pop("amount"))
        if "type" in changes:
            changes["type_"] = changes.pop("type")
        if "date" in changes:
            changes["day"] = changes.pop("date")
        entry, warning = await db_call(_update, user.id, entry_id, changes)
    except ValidationError as e:
        return validation_response(e)
    if entry is None:
        raise HTTPException(404, detail={"error": "No such entry."})
    await notify_warning(request, user.id, warning)
    return {"entry": entry_json(entry), "warning": warning}


def _update(user_id, entry_id, changes):
    type_ = changes.pop("type_", None)
    if type_ is not None:
        changes["type"] = type_
    return transactions.update_entry(user_id, entry_id, **changes)


@router.delete("/transactions/{entry_id}")
async def delete_transaction(entry_id: int, user: CurrentUser = Depends(current_user)):
    if not await db_call(transactions.delete_entry, user.id, entry_id):
        raise HTTPException(404, detail={"error": "No such entry."})
    return {"deleted": entry_id}


class QuickText(BaseModel):
    text: str


@router.post("/quick")
async def quick(body: QuickText, request: Request, user: CurrentUser = Depends(current_user)):
    """Quick entry, same rules as the bot. Without a category word, returns what was
    understood so the app can open the Add screen with it filled in."""
    try:
        parsed = quick_entry.parse(body.text, accounts=await db_call(quick_entry.user_accounts, user.id))
    except ValidationError as e:
        return validation_response(e)
    if parsed is None:
        return JSONResponse(status_code=422, content={"error": "Start with an amount, like: 500 food lunch", "field": "text"})
    draft = {"amount_minor": parsed.amount_minor, "type": parsed.type, "category": parsed.category,
             "account": parsed.account, "note": parsed.note, "date": parsed.day.isoformat() if parsed.day else None}
    if not parsed.category:
        return {"entry": None, "draft": draft, "warning": None}
    account = parsed.account or await db_call(accounts.fallback_account, user.id)
    try:
        entry, warning = await db_call(transactions.add_entry, user.id, parsed.amount_minor, parsed.type,
                                       parsed.category, account, parsed.note, parsed.day)
    except ValidationError as e:
        return validation_response(e)
    await notify_warning(request, user.id, warning)
    return {"entry": entry_json(entry), "draft": None, "warning": warning}


# --- budgets / accounts / settings -----------------------------------------------------
class BudgetChange(BaseModel):
    category: str
    limit: Optional[Amount] = None  # None or 0 removes the limit


@router.get("/budgets")
async def get_budgets(user: CurrentUser = Depends(current_user)):
    return {"budgets": await db_call(budgets.overview, user.id)}


@router.put("/budgets")
async def put_budget(body: BudgetChange, user: CurrentUser = Depends(current_user)):
    try:
        check_category(body.category, "expense")
        limit = None if body.limit in (None, "", 0, "0") else parse_amount_minor(body.limit)
        await db_call(budgets.set_limit, user.id, body.category, limit)
    except ValidationError as e:
        return validation_response(e)
    return {"budgets": await db_call(budgets.overview, user.id)}


class AccountChange(BaseModel):
    default_account: str


class NewAccount(BaseModel):
    name: str


class AccountEdit(BaseModel):
    name: Optional[str] = None
    archived: Optional[bool] = None


async def _accounts_response(user_id: int):
    return {"accounts": await db_call(accounts.overview, user_id),
            "default_account": await db_call(accounts.get_default_account, user_id)}


@router.get("/accounts")
async def get_accounts(user: CurrentUser = Depends(current_user)):
    return await _accounts_response(user.id)


@router.put("/accounts")
async def put_accounts(body: AccountChange, user: CurrentUser = Depends(current_user)):
    """Set the default account."""
    try:
        await db_call(accounts.set_default_account, user.id, body.default_account)
    except ValidationError as e:
        return validation_response(e)
    return await _accounts_response(user.id)


@router.post("/accounts", status_code=201)
async def add_account(body: NewAccount, user: CurrentUser = Depends(current_user)):
    try:
        await db_call(accounts.add_account, user.id, body.name)
    except ValidationError as e:
        return validation_response(e)
    return await _accounts_response(user.id)


@router.patch("/accounts/{key}")
async def edit_account(key: str, body: AccountEdit, user: CurrentUser = Depends(current_user)):
    """Rename, archive (archived: true) or restore (archived: false) an account."""
    try:
        if body.name is not None:
            await db_call(accounts.rename_account, user.id, key, body.name)
        if body.archived is not None:
            await db_call(accounts.set_archived, user.id, key, body.archived)
    except ValidationError as e:
        return validation_response(e)
    return await _accounts_response(user.id)


class SettingsChange(BaseModel):
    currency: Optional[str] = None
    recap_enabled: Optional[bool] = None


@router.put("/settings")
async def put_settings(body: SettingsChange, user: CurrentUser = Depends(current_user)):
    try:
        return {"settings": await db_call(prefs.set_prefs, user.id, body.currency, body.recap_enabled)}
    except ValidationError as e:
        return validation_response(e)

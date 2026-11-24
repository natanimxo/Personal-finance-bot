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
from app.services import accounts, budgets, catalog, prefs, summaries, transactions
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
        "category_label": catalog.label_for(entry["category"], entry["type"]),
        "account": entry["account"],
        "account_label": catalog.account_label(entry["account"]),
        "note": entry["note"] or "",
        "created_at": entry["created_at"] + "Z",  # stored as naive UTC
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


class EntryChanges(BaseModel):
    amount: Optional[Amount] = None
    type: Optional[str] = None
    category: Optional[str] = None
    account: Optional[str] = None
    note: Optional[str] = None


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
        account = body.account or await db_call(accounts.get_default_account, user.id) or "cash"
        entry, warning = await db_call(
            transactions.add_entry, user.id, amount_minor, body.type, body.category, account, body.note or ""
        )
    except ValidationError as e:
        return validation_response(e)
    await notify_warning(request, user.id, warning)
    return {"entry": entry_json(entry), "warning": warning}


@router.patch("/transactions/{entry_id}")
async def edit_transaction(entry_id: int, body: EntryChanges, request: Request,
                           user: CurrentUser = Depends(current_user)):
    try:
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        if "amount" in changes:
            changes["amount_minor"] = parse_amount_minor(changes.pop("amount"))
        if "type" in changes:
            changes["type_"] = changes.pop("type")
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


@router.get("/accounts")
async def get_accounts(user: CurrentUser = Depends(current_user)):
    return {"accounts": await db_call(accounts.overview, user.id)}


@router.put("/accounts")
async def put_accounts(body: AccountChange, user: CurrentUser = Depends(current_user)):
    try:
        await db_call(accounts.set_default_account, user.id, body.default_account)
    except ValidationError as e:
        return validation_response(e)
    return {"accounts": await db_call(accounts.overview, user.id)}


class SettingsChange(BaseModel):
    currency: Optional[str] = None
    recap_enabled: Optional[bool] = None


@router.put("/settings")
async def put_settings(body: SettingsChange, user: CurrentUser = Depends(current_user)):
    try:
        return {"settings": await db_call(prefs.set_prefs, user.id, body.currency, body.recap_enabled)}
    except ValidationError as e:
        return validation_response(e)

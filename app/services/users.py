from app.db import get_conn


def register_user(user_id: int):
    """Adds the user, or marks them active again if they had blocked the bot."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (user_id) VALUES (?) "
            "ON CONFLICT(user_id) DO UPDATE SET active = 1 WHERE active = 0",
            (user_id,),
        )


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]


def mark_inactive(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (user_id,))


def is_active(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT active FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and row["active"])


RECAP_KINDS = {  # kind -> (the user's switch, the "already sent" column)
    "weekly": ("recap_enabled", "last_recap_sent"),
    "monthly": ("monthly_recap_enabled", "last_monthly_recap_sent"),
}


def recap_candidates(period_key: str, kind: str = "weekly"):
    """Active users with this recap switched on who haven't been sent the one for `period_key`."""
    switch, sent = RECAP_KINDS[kind]
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT u.user_id FROM users u LEFT JOIN user_prefs p ON p.user_id = u.user_id "
            f"WHERE u.active = 1 AND COALESCE(p.{switch}, 1) = 1 "
            f"AND (u.{sent} IS NULL OR u.{sent} <> ?) ORDER BY u.user_id",
            (period_key,),
        ).fetchall()
        return [r["user_id"] for r in rows]


def recap_rows(kind: str = "weekly"):
    """[(user_id, timezone, last_sent)] of active users with this recap switched on.
    A user who hasn't picked a timezone yet is on UTC."""
    switch, sent = RECAP_KINDS[kind]
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT u.user_id, COALESCE(p.timezone, 'UTC') AS zone, u.{sent} AS last_sent FROM users u "
            f"LEFT JOIN user_prefs p ON p.user_id = u.user_id "
            f"WHERE u.active = 1 AND COALESCE(p.{switch}, 1) = 1 ORDER BY u.user_id",
        ).fetchall()
    return [(r["user_id"], r["zone"], r["last_sent"]) for r in rows]


def mark_recap_sent(user_id: int, period_key: str, kind: str = "weekly"):
    sent = RECAP_KINDS[kind][1]
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {sent} = ? WHERE user_id = ?", (period_key, user_id))

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


def recap_candidates(week_key: str):
    """Active users who have not been sent the recap for `week_key` yet."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.user_id FROM users u LEFT JOIN user_prefs p ON p.user_id = u.user_id "
            "WHERE u.active = 1 AND COALESCE(p.recap_enabled, 1) = 1 "
            "AND (u.last_recap_sent IS NULL OR u.last_recap_sent <> ?) ORDER BY u.user_id",
            (week_key,),
        ).fetchall()
        return [r["user_id"] for r in rows]


def mark_recap_sent(user_id: int, week_key: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_recap_sent = ? WHERE user_id = ?", (week_key, user_id))

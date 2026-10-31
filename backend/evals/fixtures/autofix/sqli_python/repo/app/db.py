import sqlite3


def get_user(conn: sqlite3.Connection, user_id: str):
    cur = conn.cursor(); cur.execute("SELECT * FROM users WHERE id = " + user_id)
    return cur.fetchone()

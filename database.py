import sqlite3
from datetime import datetime


DB_PATH = "labelspy.db"


def get_connection():
    """Создаёт подключение к базе данных с увеличенным таймаутом."""
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы если их ещё нет."""
    conn = get_connection()
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_premium INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            product_name TEXT,
            rating TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()


def add_user(user_id: int, username: str, first_name: str):
    """Добавляет нового пользователя (если его ещё нет)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
        (user_id, username, first_name)
    )
    conn.commit()
    conn.close()


def get_monthly_scan_count(user_id: int) -> int:
    """Считает сколько сканов сделал пользователь в текущем календарном месяце."""
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now()
    month_start = now.strftime("%Y-%m-01 00:00:00")

    cursor.execute(
        "SELECT COUNT(*) as cnt FROM scans WHERE user_id = ? AND scanned_at >= ?",
        (user_id, month_start)
    )
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0


def add_scan(user_id: int, product_name: str = None, rating: str = None):
    """Записывает новый успешный скан в базу."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO scans (user_id, product_name, rating) VALUES (?, ?, ?)",
        (user_id, product_name or "Нераспознано", str(rating) if rating is not None else None)
    )
    conn.commit()
    conn.close()


def is_premium(user_id: int) -> bool:
    """Проверяет, есть ли у пользователя премиум."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return bool(result and result["is_premium"])


def get_total_users() -> int:
    """Общее количество пользователей."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"]


def get_user_info(user_id: int):
    """Возвращает информацию о пользователе."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None


def set_premium(user_id: int, status: bool = True):
    """Устанавливает статус премиум для пользователя."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_premium = ? WHERE user_id = ?",
        (1 if status else 0, user_id)
    )
    conn.commit()
    conn.close()


def get_total_scans() -> int:
    """Общее количество сканов."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM scans")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"]


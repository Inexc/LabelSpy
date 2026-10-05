"""
Модуль работы с базой данных SQLite для LabelSpy.
Поддерживает миграции, временную зону UTC, срочные подписки и идемпотентные платежи.
"""

import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = "labelspy.db"


def get_utc_now() -> datetime:
    """Возвращает текущее время в UTC."""
    return datetime.now(timezone.utc)


def get_utc_now_str() -> str:
    """Возвращает текущее UTC-время в формате 'YYYY-MM-DD HH:MM:SS'."""
    return get_utc_now().strftime("%Y-%m-%d %H:%M:%S")


def get_month_start_utc() -> str:
    """Возвращает начало текущего календарного месяца в UTC ('YYYY-MM-01 00:00:00')."""
    return get_utc_now().strftime("%Y-%m-01 00:00:00")


def get_connection(db_path: str = None):
    """Создаёт подключение к базе данных с увеличенным таймаутом."""
    conn = sqlite3.connect(db_path or DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = None):
    """
    Создаёт таблицы и применяет миграции схемы без потери пользовательских данных.
    """
    conn = get_connection(db_path)
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()

    # 1. Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_premium INTEGER DEFAULT 0,
            premium_until TEXT DEFAULT NULL
        )
    """)

    # Миграция: проверяем наличие столбца premium_until в существующих БД
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row["name"] for row in cursor.fetchall()]
    if "premium_until" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN premium_until TEXT DEFAULT NULL")
        # Для пользователей со старым флагом is_premium=1 задаем стартовый срок (30 дней от текущего момента)
        legacy_until = (get_utc_now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE users SET premium_until = ? WHERE is_premium = 1 AND premium_until IS NULL",
            (legacy_until,)
        )

    # 2. Таблица сканирований
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            product_name TEXT,
            rating TEXT,
            status TEXT DEFAULT 'success',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    # Миграция: проверяем наличие столбца status в таблице scans
    cursor.execute("PRAGMA table_info(scans)")
    scan_columns = [row["name"] for row in cursor.fetchall()]
    if "status" not in scan_columns:
        cursor.execute("ALTER TABLE scans ADD COLUMN status TEXT DEFAULT 'success'")

    # Индекс для ускорения выборки лимита сканов по месяцам
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_user_time ON scans(user_id, scanned_at)")

    # 3. Таблица платежей (для идемпотентности и аудита)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_charge_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL,
            payload TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_charge ON payments(telegram_charge_id)")

    conn.commit()
    conn.close()


def add_user(user_id: int, username: str, first_name: str, db_path: str = None):
    """
    Добавляет нового пользователя или обновляет имя и username при изменении.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = get_utc_now_str()
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (user_id, username, first_name, now_str))
    conn.commit()
    conn.close()


def get_user_info(user_id: int, db_path: str = None) -> dict | None:
    """Возвращает информацию о пользователе из БД с актуальным статусом подписки."""
    # Обновляем статус подписки, если срок истёк
    is_premium(user_id, db_path=db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None


def is_premium(user_id: int, db_path: str = None) -> bool:
    """
    Проверяет, действует ли у пользователя премиум-подписка на текущий момент (UTC).
    Если срок истёк, автоматически сбрасывает статус.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return False

    prem_until_str = result["premium_until"]
    now_str = get_utc_now_str()

    if prem_until_str:
        if prem_until_str > now_str:
            conn.close()
            return True
        else:
            # Срок истёк — обновляем флаг в БД
            if result["is_premium"] != 0:
                cursor.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
            conn.close()
            return False

    # Если даты окончания нет, но флаг стоит (редкий legacy случай)
    has_prem = bool(result["is_premium"])
    conn.close()
    return has_prem


def get_premium_until(user_id: int, db_path: str = None) -> str | None:
    """Возвращает дату и время окончания подписки в формате UTC, если она активна."""
    if not is_premium(user_id, db_path=db_path):
        return None
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["premium_until"] if row else None


def grant_premium(user_id: int, duration_days: int, db_path: str = None) -> str:
    """
    Продлевает или активирует премиум-подписку на указанное количество дней.
    Если у пользователя уже есть активная подписка, продлевает её от даты окончания.
    Возвращает новую дату окончания подписки в формате UTC.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    now_utc = get_utc_now()
    now_str = get_utc_now_str()

    current_until_str = row["premium_until"] if row else None
    if current_until_str and current_until_str > now_str:
        try:
            base_date = datetime.strptime(current_until_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            base_date = now_utc
    else:
        base_date = now_utc

    new_until = base_date + timedelta(days=duration_days)
    new_until_str = new_until.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?",
        (new_until_str, user_id)
    )
    conn.commit()
    conn.close()
    return new_until_str


def set_premium(user_id: int, status: bool = True, duration_days: int = 30, db_path: str = None) -> str | None:
    """
    Управляет премиум-статусом (совместимость со старым API с поддержкой срока действия).
    """
    if status:
        return grant_premium(user_id, duration_days=duration_days, db_path=db_path)
    else:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()
        return None


def record_successful_payment(
    charge_id: str,
    user_id: int,
    amount: int,
    currency: str,
    payload: str,
    duration_days: int = 30,
    db_path: str = None
) -> tuple[bool, str]:
    """
    Идемпотентно сохраняет платёж и начисляет подписку.
    Возвращает (is_new_payment, premium_until_str).
    Если платёж с таким charge_id уже обработан, повторно дни не начисляются.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Проверяем, не был ли этот charge_id уже записан
    cursor.execute("SELECT id FROM payments WHERE telegram_charge_id = ?", (charge_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        current_until = get_premium_until(user_id, db_path=db_path) or ""
        return False, current_until

    # Записываем платёж
    now_str = get_utc_now_str()
    cursor.execute("""
        INSERT INTO payments (telegram_charge_id, user_id, amount, currency, payload, duration_days, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (charge_id, user_id, amount, currency, payload, duration_days, now_str))
    conn.commit()
    conn.close()

    # Начисляем дни
    new_until = grant_premium(user_id, duration_days=duration_days, db_path=db_path)
    return True, new_until


def get_monthly_scan_count(user_id: int, db_path: str = None) -> int:
    """
    Считает количество успешных сканов в текущем календарном месяце строго по UTC.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    month_start = get_month_start_utc()

    cursor.execute("""
        SELECT COUNT(*) as cnt FROM scans
        WHERE user_id = ? AND scanned_at >= ? AND (status = 'success' OR status IS NULL)
    """, (user_id, month_start))
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0


def add_scan(
    user_id: int,
    product_name: str = None,
    rating: str = None,
    status: str = "success",
    db_path: str = None
) -> int:
    """
    Записывает факт сканирования в базу с текущей временной меткой UTC.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    scanned_at = get_utc_now_str()

    cursor.execute("""
        INSERT INTO scans (user_id, scanned_at, product_name, rating, status)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, scanned_at, product_name or "Нераспознано", str(rating) if rating is not None else None, status))

    scan_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return scan_id


def get_total_users(db_path: str = None) -> int:
    """Возвращает общее количество пользователей."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0


def get_total_scans(db_path: str = None) -> int:
    """Возвращает общее количество успешных сканов."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM scans WHERE status = 'success' OR status IS NULL")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0

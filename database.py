"""
Модуль работы с базой данных для LabelSpy.
Поддерживает как облачный PostgreSQL (Neon / Supabase / Render Postgres через DATABASE_URL),
так и локальный SQLite (labelspy.db) для разработки и офлайн-тестов.
Включает автоматические миграции, хранение analysis_json для карточек,
срочные подписки и идемпотентные платежи по стандарту UTC.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DB_PATH = "labelspy.db"
_pg_pool = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None and HAS_PSYCOPG2:
        url = get_database_url()
        if url:
            try:
                _pg_pool = pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=url)
                logger.info("[DB] ThreadedConnectionPool успешно инициализирован.")
            except Exception as e:
                logger.error(f"[DB] Ошибка создания ThreadedConnectionPool: {e}")
                _pg_pool = None
    return _pg_pool


class PooledConnectionWrapper:
    """
    Обёртка соединения из пула.
    При вызове conn.close() возвращает соединение обратно в пул,
    не разрывая TCP/TLS-сессию, что кардинально ускоряет отклик бота.
    """
    def __init__(self, raw_conn, pool_inst):
        self._raw_conn = raw_conn
        self._pool = pool_inst
        self._closed = False

    def close(self):
        if not self._closed:
            self._closed = True
            if self._pool and not self._raw_conn.closed:
                try:
                    self._raw_conn.rollback()
                    self._pool.putconn(self._raw_conn)
                except Exception as e:
                    logger.warning(f"[DB] Ошибка возврата соединения в пул: {e}")
                    try:
                        self._pool.putconn(self._raw_conn, close=True)
                    except Exception:
                        pass
            elif not self._raw_conn.closed:
                try:
                    self._raw_conn.close()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name):
        return getattr(self._raw_conn, name)


def get_utc_now() -> datetime:
    """Возвращает текущее время в UTC."""
    return datetime.now(timezone.utc)


def get_utc_now_str() -> str:
    """Возвращает текущее UTC-время в формате 'YYYY-MM-DD HH:MM:SS'."""
    return get_utc_now().strftime("%Y-%m-%d %H:%M:%S")


def get_month_start_utc() -> str:
    """Возвращает начало текущего календарного месяца в UTC ('YYYY-MM-01 00:00:00')."""
    return get_utc_now().strftime("%Y-%m-01 00:00:00")


def get_database_url() -> str | None:
    """Возвращает очищенный URL подключения к PostgreSQL при наличии."""
    url = os.getenv("DATABASE_URL")
    if url and url.strip():
        url = url.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    return None


def is_postgres(db_path: str = None) -> bool:
    """Определяет, используется ли PostgreSQL в текущем окружении."""
    if db_path:
        return False
    return HAS_PSYCOPG2 and bool(get_database_url())


def get_connection(db_path: str = None):
    """Создаёт подключение к PostgreSQL или SQLite в зависимости от конфигурации."""
    if is_postgres(db_path):
        pool_inst = _get_pg_pool()
        if pool_inst:
            try:
                raw_conn = pool_inst.getconn()
                if raw_conn.closed != 0:
                    try:
                        pool_inst.putconn(raw_conn, close=True)
                    except Exception:
                        pass
                    raw_conn = pool_inst.getconn()
                raw_conn.autocommit = False
                return PooledConnectionWrapper(raw_conn, pool_inst)
            except Exception as e:
                logger.warning(f"[DB] Не удалось взять соединение из пула ({e}), прямое подключение...")
        conn = psycopg2.connect(get_database_url())
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(db_path or DB_PATH, timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn


def _run_query(conn, sql: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False, commit: bool = False):
    """
    Универсальный помощник выполнения SQL для SQLite и PostgreSQL.
    Автоматически переводит плейсхолдеры '?' в '%s' для PostgreSQL.
    """
    is_pg = hasattr(conn, "status") or "psycopg2" in str(type(conn)).lower()
    if is_pg:
        sql = sql.replace("?", "%s")
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    else:
        cursor = conn.cursor()

    cursor.execute(sql, params)

    result = None
    if fetchone:
        row = cursor.fetchone()
        result = dict(row) if row else None
    elif fetchall:
        rows = cursor.fetchall()
        result = [dict(r) for r in rows]

    if commit:
        conn.commit()

    return cursor, result


def init_db(db_path: str = None):
    """
    Создаёт таблицы и применяет миграции схемы для PostgreSQL или SQLite.
    """
    conn = get_connection(db_path)
    is_pg = is_postgres(db_path)

    if not is_pg:
        conn.execute("PRAGMA journal_mode = WAL;")

    if is_pg:
        # PostgreSQL схема
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TEXT DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS scans (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    product_name TEXT,
                    rating TEXT,
                    status TEXT DEFAULT 'success',
                    analysis_json TEXT DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    telegram_charge_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    duration_days INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_scans_user_time ON scans(user_id, scanned_at);
                CREATE INDEX IF NOT EXISTS idx_payments_charge ON payments(telegram_charge_id);

                ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TEXT DEFAULT NULL;
                ALTER TABLE scans ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'success';
                ALTER TABLE scans ADD COLUMN IF NOT EXISTS analysis_json TEXT DEFAULT NULL;
            """)
        conn.commit()
    else:
        # SQLite схема
        cursor = conn.cursor()
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                product_name TEXT,
                rating TEXT,
                status TEXT DEFAULT 'success',
                analysis_json TEXT DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

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

        # Миграции SQLite
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [r["name"] for r in cursor.fetchall()]
        if "premium_until" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN premium_until TEXT DEFAULT NULL")
            legacy_until = (get_utc_now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE users SET premium_until = ? WHERE is_premium = 1 AND premium_until IS NULL",
                (legacy_until,)
            )

        cursor.execute("PRAGMA table_info(scans)")
        scan_cols = [r["name"] for r in cursor.fetchall()]
        if "status" not in scan_cols:
            cursor.execute("ALTER TABLE scans ADD COLUMN status TEXT DEFAULT 'success'")
        if "analysis_json" not in scan_cols:
            cursor.execute("ALTER TABLE scans ADD COLUMN analysis_json TEXT DEFAULT NULL")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_user_time ON scans(user_id, scanned_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_charge ON payments(telegram_charge_id)")
        conn.commit()

    conn.close()


def add_user(user_id: int, username: str, first_name: str, db_path: str = None):
    """
    Добавляет нового пользователя или обновляет имя и username при изменении.
    """
    conn = get_connection(db_path)
    now_str = get_utc_now_str()
    sql = """
        INSERT INTO users (user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """
    _run_query(conn, sql, (user_id, username, first_name, now_str), commit=True)
    conn.close()


def get_user_info(user_id: int, db_path: str = None) -> dict | None:
    """Возвращает информацию о пользователе из БД с актуальным статусом подписки."""
    is_premium(user_id, db_path=db_path)
    conn = get_connection(db_path)
    _, user = _run_query(conn, "SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    conn.close()
    return user


def is_premium(user_id: int, db_path: str = None) -> bool:
    """
    Проверяет, действует ли у пользователя премиум-подписка на текущий момент (UTC).
    Если срок истёк, автоматически сбрасывает статус.
    """
    conn = get_connection(db_path)
    _, result = _run_query(conn, "SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,), fetchone=True)

    if not result:
        conn.close()
        return False

    prem_until_str = result.get("premium_until")
    now_str = get_utc_now_str()

    if prem_until_str:
        if prem_until_str > now_str:
            conn.close()
            return True
        else:
            if result.get("is_premium") != 0:
                _run_query(conn, "UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,), commit=True)
            conn.close()
            return False

    has_prem = bool(result.get("is_premium"))
    conn.close()
    return has_prem


def get_premium_until(user_id: int, db_path: str = None) -> str | None:
    """Возвращает дату окончания подписки в формате UTC, если она активна."""
    if not is_premium(user_id, db_path=db_path):
        return None
    conn = get_connection(db_path)
    _, row = _run_query(conn, "SELECT premium_until FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    conn.close()
    return row.get("premium_until") if row else None


def grant_premium(user_id: int, duration_days: int, db_path: str = None) -> str:
    """
    Продлевает или активирует премиум-подписку на указанное количество дней.
    Если у пользователя уже есть активная подписка, продлевает её от даты окончания.
    Возвращает новую дату окончания подписки в формате UTC.
    """
    conn = get_connection(db_path)
    _, row = _run_query(conn, "SELECT premium_until FROM users WHERE user_id = ?", (user_id,), fetchone=True)

    now_utc = get_utc_now()
    now_str = get_utc_now_str()

    current_until_str = row.get("premium_until") if row else None
    if current_until_str and current_until_str > now_str:
        try:
            base_date = datetime.strptime(current_until_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            base_date = now_utc
    else:
        base_date = now_utc

    new_until = base_date + timedelta(days=duration_days)
    new_until_str = new_until.strftime("%Y-%m-%d %H:%M:%S")

    sql = "UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?"
    _run_query(conn, sql, (new_until_str, user_id), commit=True)
    conn.close()
    return new_until_str


def set_premium(user_id: int, status: bool = True, duration_days: int = 30, db_path: str = None) -> str | None:
    """Управляет премиум-статусом (совместимость со старым интерфейсом)."""
    if status:
        return grant_premium(user_id, duration_days=duration_days, db_path=db_path)
    else:
        conn = get_connection(db_path)
        sql = "UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?"
        _run_query(conn, sql, (user_id,), commit=True)
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
    """
    conn = get_connection(db_path)
    _, existing = _run_query(conn, "SELECT id FROM payments WHERE telegram_charge_id = ?", (charge_id,), fetchone=True)
    if existing:
        conn.close()
        current_until = get_premium_until(user_id, db_path=db_path) or ""
        return False, current_until

    now_str = get_utc_now_str()
    sql = """
        INSERT INTO payments (telegram_charge_id, user_id, amount, currency, payload, duration_days, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    _run_query(conn, sql, (charge_id, user_id, amount, currency, payload, duration_days, now_str), commit=True)
    conn.close()

    new_until = grant_premium(user_id, duration_days=duration_days, db_path=db_path)
    return True, new_until


def get_monthly_scan_count(user_id: int, db_path: str = None) -> int:
    """Считает количество успешных сканов в текущем календарном месяце строго по UTC."""
    conn = get_connection(db_path)
    month_start = get_month_start_utc()
    sql = """
        SELECT COUNT(*) as cnt FROM scans
        WHERE user_id = ? AND scanned_at >= ? AND (status = 'success' OR status IS NULL)
    """
    _, res = _run_query(conn, sql, (user_id, month_start), fetchone=True)
    conn.close()
    return res.get("cnt", 0) if res else 0


def add_scan(
    user_id: int,
    product_name: str = None,
    rating: str = None,
    status: str = "success",
    analysis_json: str = None,
    db_path: str = None
) -> int:
    """
    Записывает факт сканирования в базу, включая analysis_json для генерации карточки.
    """
    conn = get_connection(db_path)
    scanned_at = get_utc_now_str()
    sql = """
        INSERT INTO scans (user_id, scanned_at, product_name, rating, status, analysis_json)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
    """
    cursor, row = _run_query(
        conn,
        sql,
        (user_id, scanned_at, product_name or "Нераспознано", str(rating) if rating is not None else None, status, analysis_json),
        fetchone=True,
        commit=True
    )
    scan_id = row.get("id") if row else cursor.lastrowid
    conn.close()
    return scan_id


def get_scan(scan_id: int, db_path: str = None) -> dict | None:
    """Возвращает информацию о скане по его ID."""
    conn = get_connection(db_path)
    _, scan = _run_query(conn, "SELECT * FROM scans WHERE id = ?", (scan_id,), fetchone=True)
    conn.close()
    return scan


def get_total_users(db_path: str = None) -> int:
    """Возвращает общее количество пользователей."""
    conn = get_connection(db_path)
    _, res = _run_query(conn, "SELECT COUNT(*) as cnt FROM users", fetchone=True)
    conn.close()
    return res.get("cnt", 0) if res else 0


def get_total_scans(db_path: str = None) -> int:
    """Возвращает общее количество успешных сканов."""
    conn = get_connection(db_path)
    _, res = _run_query(conn, "SELECT COUNT(*) as cnt FROM scans WHERE status = 'success' OR status IS NULL", fetchone=True)
    conn.close()
    return res.get("cnt", 0) if res else 0

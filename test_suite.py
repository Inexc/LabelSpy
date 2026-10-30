"""
Автоматический тестовый набор LabelSpy.
Запускается строго локально, не совершает сетевых вызовов в Telegram или Gemini.
Проверяет:
1. Миграции SQLite схемы
2. Сроки и продление подписки, истечение срока
3. Идемпотентность и валидацию платежей
4. Месячные лимиты и учет по UTC
5. Защиту от конкурентных запросов
6. Валидацию и нормализацию JSON-ответа AI
7. Экранирование HTML и соблюдение лимитов длины сообщений
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

import database
import analyzer
from config import FREE_SCANS_PER_MONTH, PREMIUM_SUBSCRIPTION_DAYS, DEMO_PREMIUM_DAYS


class TestDatabaseAndSubscriptions(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_file.close()
        self.db_path = self.temp_file.name

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_legacy_migration_and_compatibility(self):
        """Проверяет миграцию старой БД (без premium_until и status) без потери данных."""
        conn = sqlite3.connect(self.db_path)
        # Создаем старую схему
        conn.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_premium INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                product_name TEXT,
                rating TEXT
            )
        """)
        # Добавляем легаси пользователя с включенным премиумом
        conn.execute("INSERT INTO users (user_id, username, first_name, is_premium) VALUES (101, 'legacy_user', 'Old', 1)")
        conn.execute("INSERT INTO users (user_id, username, first_name, is_premium) VALUES (102, 'free_user', 'Free', 0)")
        conn.commit()
        conn.close()

        # Запускаем init_db с миграциями
        database.init_db(db_path=self.db_path)

        # Проверяем, что столбцы добавились и легаси премиум получил дату окончания
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        user_cols = [r["name"] for r in cur.fetchall()]
        self.assertIn("premium_until", user_cols)

        cur.execute("SELECT premium_until, is_premium FROM users WHERE user_id = 101")
        u101 = cur.fetchone()
        self.assertEqual(u101["is_premium"], 1)
        self.assertIsNotNone(u101["premium_until"])

        cur.execute("SELECT premium_until, is_premium FROM users WHERE user_id = 102")
        u102 = cur.fetchone()
        self.assertEqual(u102["is_premium"], 0)
        self.assertIsNone(u102["premium_until"])

        cur.execute("PRAGMA table_info(scans)")
        scan_cols = [r["name"] for r in cur.fetchall()]
        self.assertIn("status", scan_cols)

        # Проверяем наличие таблицы payments
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'")
        self.assertIsNotNone(cur.fetchone())
        conn.close()

    def test_subscription_expiration_and_extension(self):
        """Проверяет вычисление активности подписки, истечение и продление при повторной покупке."""
        database.init_db(db_path=self.db_path)
        user_id = 555
        database.add_user(user_id, "sub_user", "Tester", db_path=self.db_path)

        # 1. По умолчанию подписки нет
        self.assertFalse(database.is_premium(user_id, db_path=self.db_path))
        self.assertIsNone(database.get_premium_until(user_id, db_path=self.db_path))

        # 2. Активация на 30 дней
        expiry_1 = database.grant_premium(user_id, duration_days=30, db_path=self.db_path)
        self.assertTrue(database.is_premium(user_id, db_path=self.db_path))
        self.assertEqual(database.get_premium_until(user_id, db_path=self.db_path), expiry_1)

        # 3. Повторная покупка на 15 дней должна продлить от expiry_1
        expiry_2 = database.grant_premium(user_id, duration_days=15, db_path=self.db_path)
        dt1 = datetime.strptime(expiry_1, "%Y-%m-%d %H:%M:%S")
        dt2 = datetime.strptime(expiry_2, "%Y-%m-%d %H:%M:%S")
        self.assertEqual((dt2 - dt1).days, 15)

        # 4. Проверка истечения: искусственно переносим дату в прошлое
        conn = database.get_connection(self.db_path)
        past_str = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (past_str, user_id))
        conn.commit()
        conn.close()

        # Должен вернуть False и сбросить is_premium
        self.assertFalse(database.is_premium(user_id, db_path=self.db_path))
        self.assertIsNone(database.get_premium_until(user_id, db_path=self.db_path))

    def test_admin_demo_access_duration(self):
        """Проверяет явный срок действия демо-доступа администратора."""
        database.init_db(db_path=self.db_path)
        admin_id = 777
        database.add_user(admin_id, "admin", "Boss", db_path=self.db_path)

        expiry = database.grant_premium(admin_id, duration_days=DEMO_PREMIUM_DAYS, db_path=self.db_path)
        self.assertTrue(database.is_premium(admin_id, db_path=self.db_path))
        exp_dt = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
        now_dt = datetime.now(timezone.utc)
        self.assertAlmostEqual((exp_dt.replace(tzinfo=timezone.utc) - now_dt).days, DEMO_PREMIUM_DAYS, delta=1)

    def test_payment_idempotency(self):
        """Проверяет идемпотентность сохранения платежей (защита от двойного начисления)."""
        database.init_db(db_path=self.db_path)
        user_id = 999
        database.add_user(user_id, "buyer", "Buyer", db_path=self.db_path)

        charge_id = "tg_charge_test_12345"

        # Первая обработка платежа
        is_new_1, expiry_1 = database.record_successful_payment(
            charge_id=charge_id,
            user_id=user_id,
            amount=50,
            currency="XTR",
            payload=f"premium_1m_{user_id}",
            duration_days=30,
            db_path=self.db_path,
        )
        self.assertTrue(is_new_1)
        self.assertIsNotNone(expiry_1)

        # Повторная обработка того же платежа
        is_new_2, expiry_2 = database.record_successful_payment(
            charge_id=charge_id,
            user_id=user_id,
            amount=50,
            currency="XTR",
            payload=f"premium_1m_{user_id}",
            duration_days=30,
            db_path=self.db_path,
        )
        self.assertFalse(is_new_2)
        # Дата окончания не должна была сдвинуться еще на 30 дней!
        self.assertEqual(expiry_1, expiry_2)

    def test_utc_monthly_limit_and_failed_scans(self):
        """Проверяет подсчет лимита по календарному месяцу UTC и игнорирование ошибочных сканов."""
        database.init_db(db_path=self.db_path)
        user_id = 333
        database.add_user(user_id, "scan_tester", "Scan", db_path=self.db_path)

        # Добавляем 3 успешных скана в текущем месяце
        database.add_scan(user_id, "Whey 1", "9.0", status="success", db_path=self.db_path)
        database.add_scan(user_id, "Creatine", "8.5", status="success", db_path=self.db_path)
        database.add_scan(user_id, "BCAA", "7.0", status="success", db_path=self.db_path)

        # Добавляем 2 неудачных скана (не этикетка)
        database.add_scan(user_id, "Desk Photo", None, status="failed", db_path=self.db_path)
        database.add_scan(user_id, "Cat", None, status="failed", db_path=self.db_path)

        # Добавляем скан из предыдущего месяца
        conn = database.get_connection(self.db_path)
        conn.execute("""
            INSERT INTO scans (user_id, scanned_at, product_name, rating, status)
            VALUES (?, '2025-01-01 10:00:00', 'Old Scan', '8.0', 'success')
        """, (user_id,))
        conn.commit()
        conn.close()

        count = database.get_monthly_scan_count(user_id, db_path=self.db_path)
        # Должно быть ровно 3 (только успешные сканы текущего месяца)
        self.assertEqual(count, 3)

    def test_scan_saving_and_card_retrieval(self):
        """Проверяет сохранение analysis_json и генерацию карточки инфографики."""
        import json
        import card_generator

        database.init_db(db_path=self.db_path)
        user_id = 888
        database.add_user(user_id, "card_user", "Tester", db_path=self.db_path)

        analysis_mock = {
            "product_name": "Gold Whey Isolate",
            "score": "9.0/10",
            "verdict": "Качественный состав.",
            "positives": ["Чистый белок"],
            "warnings": []
        }
        json_str = json.dumps(analysis_mock, ensure_ascii=False)
        scan_id = database.add_scan(
            user_id=user_id,
            product_name=analysis_mock["product_name"],
            rating="9.0",
            status="success",
            analysis_json=json_str,
            db_path=self.db_path
        )
        self.assertIsNotNone(scan_id)

        retrieved = database.get_scan(scan_id, db_path=self.db_path)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["product_name"], "Gold Whey Isolate")
        self.assertEqual(retrieved["analysis_json"], json_str)

        card_bytes = card_generator.create_report_card(
            product_name=analysis_mock["product_name"],
            score_str=analysis_mock["score"],
            verdict=analysis_mock["verdict"],
            warnings=analysis_mock["warnings"],
            positives=analysis_mock["positives"]
        )
        self.assertGreater(len(card_bytes), 1000)



class TestConcurrencyAndAbuseProtection(unittest.TestCase):
    def test_active_user_scan_lock(self):
        """Проверяет блокировку параллельных запросов для одного пользователя."""
        import bot
        user_id = 444
        bot.active_user_scans.clear()

        # Первый запрос занимает лок
        self.assertNotIn(user_id, bot.active_user_scans)
        bot.active_user_scans.add(user_id)

        # Параллельный запрос должен видеть занятый лок
        self.assertIn(user_id, bot.active_user_scans)

        # Освобождение
        bot.active_user_scans.discard(user_id)
        self.assertNotIn(user_id, bot.active_user_scans)


class TestAnalyzerAndValidation(unittest.TestCase):
    def test_normalize_valid_json(self):
        """Проверяет нормализацию корректного JSON."""
        raw_data = {
            "product_name": "Gold Standard Whey",
            "category": "Спортивное питание",
            "score": "8.5/10",
            "verdict": "Чистый изолят.",
            "positives": ["Высокий белок", "Мало сахара"],
            "warnings": ["Содержит следы сои"],
            "ingredients_summary": "Сывороточный протеин 82%",
            "recommendation": "Отлично подходит для набора массы."
        }
        res = analyzer.validate_and_normalize_analysis(raw_data)
        self.assertNotIn("error", res)
        self.assertEqual(res["product_name"], "Gold Standard Whey")
        self.assertEqual(res["score"], "8.5/10")
        self.assertEqual(res["score_val"], 8.5)
        self.assertEqual(len(res["positives"]), 2)
        self.assertEqual(len(res["warnings"]), 1)

    def test_normalize_invalid_and_out_of_bound_scores(self):
        """Проверяет нормализацию некорректных оценок (больше 10, меньше 1, null, нечисло)."""
        # Слишком высокая оценка (15)
        r1 = analyzer.validate_and_normalize_analysis({"score": 15})
        self.assertEqual(r1["score_val"], 10.0)
        self.assertEqual(r1["score"], "10.0/10")

        # Отрицательная оценка (-3)
        r2 = analyzer.validate_and_normalize_analysis({"score": -3})
        self.assertEqual(r2["score_val"], 1.0)
        self.assertEqual(r2["score"], "1.0/10")

        # Null / невалидная строка
        r3 = analyzer.validate_and_normalize_analysis({"score": None})
        self.assertEqual(r3["score_val"], 5.0)

        r4 = analyzer.validate_and_normalize_analysis({"score": "N/A"})
        self.assertEqual(r4["score_val"], 5.0)

    def test_normalize_nulls_and_unexpected_types(self):
        """Проверяет устойчивость к неожиданным типам данных от LLM."""
        raw_dirty = {
            "product_name": None,
            "category": None,
            "score": None,
            "verdict": None,
            "positives": "не список, а строка",
            "warnings": [None, 123, ""],
            "ingredients_summary": None,
            "recommendation": None
        }
        res = analyzer.validate_and_normalize_analysis(raw_dirty)
        self.assertNotIn("error", res)
        self.assertEqual(res["product_name"], "Неизвестный продукт")
        self.assertEqual(res["category"], "Продукт")
        self.assertEqual(res["verdict"], "Состав проанализирован.")
        self.assertEqual(res["positives"], [])
        self.assertEqual(res["warnings"], ["123"])

    def test_html_escaping_and_length_security(self):
        """Проверяет безопасность HTML-экранирования и соблюдение лимита сообщения Telegram."""
        toxic_data = {
            "product_name": "Toxic <script>alert(1)</script> & Co",
            "category": "Sport & Food <Nutrition>",
            "score": "9.0/10",
            "verdict": "Safe formula: <0.1% sugar & zero fat.",
            "warnings": ["Allergens: milk & eggs <trace>"],
            "positives": ["Pure isolate & BCAAs > 5g"],
            "ingredients_summary": "Very long text " * 150,  # Огромный текст
            "recommendation": "Use daily & stay healthy."
        }
        formatted = analyzer.format_analysis_html(toxic_data)
        self.assertNotIn("<script>", formatted)
        self.assertIn("&lt;script&gt;", formatted)
        self.assertIn("&amp; Co", formatted)
        self.assertIn("Дисклеймер", formatted)
        # Гарантия непревышения лимита Telegram
        self.assertLess(len(formatted), 4000)

    def test_image_validation_empty_and_invalid(self):
        """Проверяет валидацию поврежденных или пустых изображений."""
        img, err = analyzer.validate_and_prepare_image(b"")
        self.assertIsNone(img)
        self.assertIn("пуст или повреждён", err)

        img2, err2 = analyzer.validate_and_prepare_image(b"not_an_image_at_all" * 10)
        self.assertIsNone(img2)
        self.assertIn("Не удалось открыть", err2)

    def test_card_generator_cyrillic_and_fonts(self):
        """Проверяет генерацию карточки с кириллицей и работу кэша шрифтов."""
        from card_generator import create_report_card, get_font
        font = get_font(16)
        self.assertIsNotNone(font)
        card_bytes = create_report_card(
            product_name="Тестовый напиток",
            score_str="4.0/10",
            verdict="Тестовый вердикт на русском языке",
            warnings=["Предупреждение 1", "Предупреждение 2"],
            positives=["Плюс 1"]
        )
        self.assertTrue(card_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(card_bytes), 1000)


if __name__ == "__main__":
    unittest.main()

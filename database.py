# database.py
import sqlite3
import time
import threading
import os

# --- Дополнительные функции из main.py ---
def create_tables(db_pool=None, DATABASE_FILE=None, MESSAGES_DB_FILE_FILE=None, _tasks=None):
    try:
        # Вызываем полную инициализацию всех таблиц из database.py
        print("🚀 Инициализация всех таблиц базы данных...")
        init_db()
        
        # Дополнительно создаем таблицы через пул соединений для реферальной системы
        if db_pool:
            db_pool.execute_query('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    referrer_id INTEGER DEFAULT NULL,
                    referrals_count INTEGER DEFAULT 0,
                    reg_date TEXT,
                    bonus_requests INTEGER DEFAULT 0,
                    used_bonus_requests INTEGER DEFAULT 0,
                    used_referral_code TEXT DEFAULT NULL,
                    adult_unlocks INTEGER DEFAULT 0
                )
            ''')

            # Миграция: добавляем недостающие колонки для реферальной системы
            try:
                cols = db_pool.execute_query("PRAGMA table_info(users)")
                existing = {row[1] for row in cols}
                if "reg_date" not in existing:
                    db_pool.execute_query("ALTER TABLE users ADD COLUMN reg_date TEXT")
                if "bonus_requests" not in existing:
                    db_pool.execute_query("ALTER TABLE users ADD COLUMN bonus_requests INTEGER DEFAULT 0")
                if "used_bonus_requests" not in existing:
                    db_pool.execute_query("ALTER TABLE users ADD COLUMN used_bonus_requests INTEGER DEFAULT 0")
                if "used_referral_code" not in existing:
                    db_pool.execute_query("ALTER TABLE users ADD COLUMN used_referral_code TEXT DEFAULT NULL")
                if "adult_unlocks" not in existing:
                    db_pool.execute_query("ALTER TABLE users ADD COLUMN adult_unlocks INTEGER DEFAULT 0")
            except Exception as mig_e:
                print(f"⚠️ Миграция users: {mig_e}")
            
            # Таблица для кастомных имен пользователей
            db_pool.execute_query('''
                CREATE TABLE IF NOT EXISTS custom_names (
                    user_id INTEGER PRIMARY KEY,
                    custom_name TEXT NOT NULL,
                    set_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для настроек приватности профиля
            db_pool.execute_query('''
                CREATE TABLE IF NOT EXISTS profile_privacy (
                    user_id INTEGER PRIMARY KEY,
                    allow_profile_link INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            print("✅ Дополнительные таблицы реферальной системы проверены")
        
        print("🎉 Все таблицы базы данных готовы к работе!")
            
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}")
        # Попытка создать минимальную таблицу без DEFAULT значений
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    referrer_id INTEGER,
                    referrals_count INTEGER,
                    reg_date TEXT,
                    bonus_requests INTEGER DEFAULT 0,
                    used_bonus_requests INTEGER DEFAULT 0,
                    used_referral_code TEXT,
                    adult_unlocks INTEGER DEFAULT 0
                )
            ''')
            conn.commit()
            conn.close()
            print("✅ Минимальная таблица создана")
        except Exception as e2:
            print(f"❌ Критическая ошибка создания таблиц: {e2}")

    # Ensure daily_claims table exists in messages DB for storing daily bonus claims
    try:
        meta_conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        meta_cur = meta_conn.cursor()
        meta_cur.execute('''
            CREATE TABLE IF NOT EXISTS daily_claims (
                user_id INTEGER PRIMARY KEY,
                streak INTEGER DEFAULT 0,
                last_claim_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        meta_conn.commit()
        meta_conn.close()
        print("✅ Таблица daily_claims создана/проверена в messages DB")
    except Exception as e:
        print(f"❌ Не удалось создать daily_claims в messages DB: {e}")
    try:
        meta_conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        meta_cur = meta_conn.cursor()
        meta_cur.execute('''
            CREATE TABLE IF NOT EXISTS daily_claim_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                claim_date DATE,
                streak INTEGER,
                bonus INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        meta_cur.execute('''
            CREATE TABLE IF NOT EXISTS daily_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        # Insert default message if not exists
        meta_cur.execute('SELECT value FROM daily_config WHERE key = ?', ('message_text',))
        if not meta_cur.fetchone():
            default_text = (
                "🎁 <b>Ежедневный бонус KRUZ</b> — собери серию из 7 дней! 🎯\n\n"
                "🔹 Каждый день бонус растет: 100 ➕50 ➡️ максимум 500 дань\n"
                "🔸 Для получения — подпишись на канал и нажми на текущий день.\n\n"
                "🔥 Не пропускай — чем дольше серия, тем больше награда! 💪\n"
                "📅 Нажми на номер дня, чтобы получить награду."
            )
            meta_cur.execute('INSERT INTO daily_config (key, value) VALUES (?, ?)', ('message_text', default_text))
        meta_conn.commit()
        meta_conn.close()
        print("✅ Таблицы daily_claim_logs и daily_config созданы/проверены")
    except Exception as e:
        print(f"❌ Не удалось создать daily logs/config: {e}")

import datetime
async def add_user(user_id: int, username: str, db_pool=None, DATABASE_FILE=None):
    """Добавляет пользователя в БД. Возвращает True если пользователь новый, False если уже существовал."""
    is_new_user = False
    try:
        if db_pool:
            columns = db_pool.execute_query("PRAGMA table_info(users)")
            column_names = [row[1] for row in columns]
            if "reg_date" not in column_names:
                db_pool.execute_query("ALTER TABLE users ADD COLUMN reg_date TEXT")
            if "bonus_requests" not in column_names:
                db_pool.execute_query("ALTER TABLE users ADD COLUMN bonus_requests INTEGER DEFAULT 0")
            if "used_bonus_requests" not in column_names:
                db_pool.execute_query("ALTER TABLE users ADD COLUMN used_bonus_requests INTEGER DEFAULT 0")
            if "used_referral_code" not in column_names:
                db_pool.execute_query("ALTER TABLE users ADD COLUMN used_referral_code TEXT DEFAULT NULL")
            if "adult_unlocks" not in column_names:
                db_pool.execute_query("ALTER TABLE users ADD COLUMN adult_unlocks INTEGER DEFAULT 0")
            result = db_pool.execute_one("SELECT reg_date FROM users WHERE user_id = ?", (user_id,))
            if not result:
                is_new_user = True
                reg_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                db_pool.execute_query(
                    "INSERT OR REPLACE INTO users (user_id, username, reg_date, referrals_count, bonus_requests, used_bonus_requests, used_referral_code, adult_unlocks, dan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username or '', reg_date, 0, 0, 0, None, 0, 500)
                )
            else:
                db_pool.execute_query("UPDATE users SET username = ? WHERE user_id = ?", (username or '', user_id))
        else:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, referrals_count FROM users WHERE user_id = ?", (user_id,))
            existing = cursor.fetchone()
            if not existing:
                is_new_user = True
                reg_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    "INSERT INTO users (user_id, username, referrals_count, reg_date, bonus_requests, used_bonus_requests, used_referral_code, adult_unlocks, dan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                    (user_id, username or '', 0, reg_date, 0, 0, None, 0, 500)
                )
            else:
                if existing[1] is None:
                    cursor.execute("UPDATE users SET username = ?, referrals_count = ? WHERE user_id = ?", 
                                 (username or '', 0, user_id))
                else:
                    cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username or '', user_id))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"❌ Ошибка в add_user: {e}")
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO users (user_id, username, referrals_count, bonus_requests, used_bonus_requests, used_referral_code, adult_unlocks, dan) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                (user_id, username or '', 0, 0, 0, None, 0, 500)
            )
            conn.commit()
            cursor.execute("SELECT reg_date FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row or row[0] is None:
                reg_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("UPDATE users SET reg_date = ? WHERE user_id = ?", (reg_date, user_id))
            conn.commit()
            conn.close()
        except Exception as e2:
            print(f"❌ Критическая ошибка add_user fallback: {e2}")
            try:
                conn.close()
            except:
                pass
    
    return is_new_user

async def set_referrer(user_id: int, referrer_id: int, db_pool=None, _tasks=None):
    if not db_pool:
        return False
    if user_id == referrer_id:
        return False
    result = db_pool.execute_one("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
    can_set_referrer = (result is None) or (result and result[0] is None)
    if can_set_referrer:
        await add_user(user_id, "Unknown", db_pool=db_pool)
        await add_user(referrer_id, "Unknown", db_pool=db_pool)
        db_pool.execute_query("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, user_id))
        db_pool.execute_query("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (referrer_id,))
        try:
            if _tasks:
                _tasks.record_referral(referrer_id)
        except Exception as e:
            print(f"❌ Ошибка записи реферала для {referrer_id}: {e}")
        return True
    return False

# --- Inventory functions ---
def create_inventory_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER,
        item_id TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, item_id)
    );
    """)
    conn.commit()
    conn.close()

def remove_item(user_id: int, item_id: str, count: int = 1):
    """Удаляет предметы из инвентаря, правильно обрабатывая дублированные записи"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Получаем общее количество предметов (с учетом дубликатов)
    cur.execute("SELECT SUM(count) as total_count FROM inventory WHERE user_id=? AND item_id=? AND count > 0", (user_id, item_id))
    row = cur.fetchone()
    total_count = row[0] if row and row[0] else 0
    
    if total_count <= 0:
        # Нет предметов для удаления
        conn.close()
        return
    
    if total_count > count:
        # Оставляем часть предметов
        remaining = total_count - count
        # Удаляем все записи для этого предмета
        cur.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
        # Добавляем одну запись с правильным количеством
        cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", (user_id, item_id, remaining))
    else:
        # Удаляем все записи этого предмета
        cur.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    
    conn.commit()
    conn.close()

def get_inventory(user_id: int):
    """Получает инвентарь пользователя. Возвращает список кортежей (item_id, count), агрегируя одинаковые предметы"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Группируем по item_id и суммируем количество для устранения возможных дубликатов
    cur.execute("""
        SELECT item_id, SUM(count) as total_count 
        FROM inventory 
        WHERE user_id=? AND count > 0 
        GROUP BY item_id 
        HAVING total_count > 0 
        ORDER BY item_id
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def add_item(user_id: int, item_id: str, count: int = 1):
    """Добавляет предмет в инвентарь пользователя, очищая дублированные записи"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Получаем текущее общее количество (с учетом дубликатов)
    cur.execute("SELECT SUM(count) as total_count FROM inventory WHERE user_id=? AND item_id=? AND count > 0", (user_id, item_id))
    row = cur.fetchone()
    current_total = row[0] if row and row[0] else 0
    
    # Новое общее количество
    new_total = current_total + count
    
    # Удаляем все записи этого предмета (включая дубликаты)
    cur.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    
    # Добавляем одну запись с правильным количеством
    if new_total > 0:
        cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", (user_id, item_id, new_total))
    
    conn.commit()
    conn.close()

def clean_inventory_duplicates():
    """Очищает дублированные записи в инвентаре для всех пользователей"""
    print("🧹 Начинаем очистку дублированных записей в инвентаре...")
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Находим все дублированные записи
    cur.execute("""
        SELECT user_id, item_id, SUM(count) as total_count
        FROM inventory 
        GROUP BY user_id, item_id
        HAVING COUNT(*) > 1
    """)
    duplicates = cur.fetchall()
    
    if not duplicates:
        print("✅ Дублированных записей не найдено")
        conn.close()
        return
    
    print(f"⚠️ Найдено {len(duplicates)} дублированных групп записей")
    
    for user_id, item_id, total_count in duplicates:
        # Удаляем все записи для этого пользователя и предмета
        cur.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
        
        # Добавляем одну запись с правильным количеством (если > 0)
        if total_count > 0:
            cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", (user_id, item_id, total_count))
        
        print(f"🔧 Исправлено: пользователь {user_id}, предмет {item_id}: {total_count} шт.")
    
    # Также удаляем записи с отрицательными или нулевыми значениями
    cur.execute("DELETE FROM inventory WHERE count <= 0")
    deleted_count = cur.rowcount
    if deleted_count > 0:
        print(f"🗑️ Удалено {deleted_count} записей с нулевыми/отрицательными значениями")
    
    conn.commit()
    conn.close()
    print("✅ Очистка дублированных записей завершена")

def set_inventory_item(user_id: int, item_id: str, count: int):
    """Устанавливает точное количество предмета в инвентаре пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if count > 0:
        cur.execute("INSERT OR REPLACE INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", (user_id, item_id, count))
    else:
        cur.execute("DELETE FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
    conn.commit()
    conn.close()

def create_bets_table():
    """Создает таблицу для ставок"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        bet_id TEXT PRIMARY KEY,
        chat_id INTEGER,
        msg_id INTEGER,
        text TEXT,
        created_by INTEGER,
        created_at INTEGER
    );
    """)
    conn.commit()
    conn.close()

def create_bans_table():
    """Создает таблицу для банов"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        banned_until INTEGER,
        banned_by INTEGER,
        reason TEXT,
        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    """)
    conn.commit()
    conn.close()

def create_user_effects_table():
    """Создает таблицу для активных эффектов пользователей"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_effects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        effect_type TEXT,
        effect_data TEXT,
        expires_at INTEGER,
        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    """)
    conn.commit()
    conn.close()



# Always store DB in the 'database' folder in the project directory
DB_FOLDER = os.path.join(os.path.dirname(__file__), "database")
os.makedirs(DB_FOLDER, exist_ok=True)
DB_PATH = os.path.join(DB_FOLDER, "game_bot.db")

_lock = threading.Lock()

# Установить баланс ДАНЬ с округлением
def set_dan(user_id: int, value):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        # Округляем до двух знаков
        value = 0.00 if abs(value) < 0.005 else round(value, 2)
        cur.execute("UPDATE users SET dan = ? WHERE user_id = ?", (value, user_id))
        conn.commit()
        conn.close()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=0.999)
    conn.row_factory = sqlite3.Row
    try:
        # Стандартный режим DELETE (без WAL файлов)
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        # Небольшой page cache; отрицательное значение — в КБ
        conn.execute("PRAGMA cache_size=-20000;")  # ~20MB
        # Уменьшаем время блокировки
        conn.execute("PRAGMA busy_timeout=999;")
    except Exception:
        # Если PRAGMA не применились — продолжаем без падения
        pass
    return conn

def create_lottery_tables():
    """Создает таблицы для лотереи в общем файле game_bot.db и переносит данные из старого messages.db (если есть)."""
    import os
    # Создаем таблицы лотереи в основном DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Таблица билетов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            draw_date DATE NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')

    # Таблица розыгрышей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_date DATE UNIQUE NOT NULL,
            winner_user_id INTEGER,
            winner_username TEXT,
            total_tickets INTEGER DEFAULT 0,
            prize_amount INTEGER DEFAULT 0,
            draw_time TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''')

    # Дополнительные таблицы дневной системы, которые ранее жили в messages.db
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_meta (
            meta_date DATE PRIMARY KEY,
            bonus INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_claims (
            user_id INTEGER PRIMARY KEY,
            streak INTEGER DEFAULT 0,
            last_claim_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_claim_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            claim_date DATE,
            streak INTEGER,
            bonus INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()
    conn.close()

    # Перенос данных из старого messages.db, если он существует
    try:
        old_path = os.path.join(os.path.dirname(__file__), "database", "messages.db")
        if os.path.exists(old_path) and os.path.abspath(old_path) != os.path.abspath(DB_PATH):
            _migrate_messages_db_into_main(old_path)
    except Exception as e:
        try:
            print(f"⚠️ Ошибка миграции из messages.db: {e}")
        except Exception:
            pass

def create_referral_tables():
    """Создает дополнительные таблицы для реферальной системы в общем файле game_bot.db и переносит данные из старого referral_bot.db (если есть)."""
    import os
    # Работает в основном DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Гарантируем наличие необходимых колонок в основной таблице users
    cursor.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in cursor.fetchall()}
    if "referrer_id" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
    if "referrals_count" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0")

    # Таблица для кастомных имен пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_names (
            user_id INTEGER PRIMARY KEY,
            custom_name TEXT NOT NULL,
            set_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица для настроек приватности профиля
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profile_privacy (
            user_id INTEGER PRIMARY KEY,
            allow_profile_link INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

    # Перенос данных из старого referral_bot.db, если он существует
    try:
        ref_db_folder = os.path.join(os.path.dirname(__file__), "database")
        old_ref_path = os.path.join(ref_db_folder, 'referral_bot.db')
        if os.path.exists(old_ref_path) and os.path.abspath(old_ref_path) != os.path.abspath(DB_PATH):
            _migrate_referral_db_into_main(old_ref_path)
    except Exception as e:
        try:
            print(f"⚠️ Ошибка миграции из referral_bot.db: {e}")
        except Exception:
            pass

def _migrate_messages_db_into_main(old_messages_path: str):
    """Переносит таблицы из messages.db в основной game_bot.db (если в целевых таблицах ещё нет данных)."""
    src = sqlite3.connect(old_messages_path)
    dst = sqlite3.connect(DB_PATH)
    try:
        s_cur = src.cursor()
        d_cur = dst.cursor()

        # Список таблиц для переноса: (name, create_sql)
        tables = {
            'lottery_tickets': None,
            'lottery_draws': None,
            'lottery_meta': None,
            'daily_claims': None,
            'daily_claim_logs': None,
            'daily_config': None,
        }

        # Переносим построчно, избегая конфликтов по PRIMARY KEY
        for table in tables.keys():
            # Если в целевой таблице уже есть данные — пропускаем перенос этой таблицы
            d_cur.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not d_cur.fetchone()[0]:
                # Таблицы должны существовать после create_lottery_tables()
                continue
            d_cur.execute(f"SELECT COUNT(*) FROM {table}")
            if d_cur.fetchone()[0] > 0:
                continue

            # Проверим, есть ли таблица в источнике
            s_cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not s_cur.fetchone()[0]:
                continue

            # Получаем список колонок для согласованной вставки
            s_cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in s_cur.fetchall()]
            col_list = ",".join(cols)
            placeholders = ",".join(["?"] * len(cols))

            s_cur.execute(f"SELECT {col_list} FROM {table}")
            rows = s_cur.fetchall()
            if not rows:
                continue
            d_cur.executemany(
                f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                rows
            )
            dst.commit()

        try:
            print("✅ Миграция данных из messages.db завершена")
        except Exception:
            pass
    finally:
        try:
            src.close()
        finally:
            dst.close()

def _migrate_referral_db_into_main(old_ref_path: str):
    """Переносит данные из referral_bot.db в основной game_bot.db.
    Пользователей обновляем только по referrer_id/referrals_count/username/reg_date (без вмешательства в баланс).
    Таблицы custom_names и profile_privacy копируем полностью (если пусто).
    """
    src = sqlite3.connect(old_ref_path)
    dst = sqlite3.connect(DB_PATH)
    try:
        s_cur = src.cursor()
        d_cur = dst.cursor()

        # Обновляем users: переносим только поля реферальной системы
        # Убедимся, что нужные колонки есть
        d_cur.execute("PRAGMA table_info(users)")
        d_cols = {r[1] for r in d_cur.fetchall()}
        if "referrer_id" not in d_cols:
            d_cur.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        if "referrals_count" not in d_cols:
            d_cur.execute("ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0")

        # Если таблица users есть в источнике — переносим
        s_cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'")
        if s_cur.fetchone()[0]:
            s_cur.execute("SELECT user_id, username, referrer_id, referrals_count, reg_date FROM users")
            for user_id, username, referrer_id, referrals_count, reg_date in s_cur.fetchall():
                # Обновляем существующие записи
                d_cur.execute("SELECT user_id, referrer_id, referrals_count FROM users WHERE user_id = ?", (user_id,))
                row = d_cur.fetchone()
                if row:
                    # Если в основной БД поля пустые — обновляем
                    if row[1] is None and referrer_id is not None:
                        d_cur.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, user_id))
                    if (row[2] is None or row[2] == 0) and (referrals_count is not None):
                        d_cur.execute("UPDATE users SET referrals_count = ? WHERE user_id = ?", (referrals_count, user_id))
                    # Обновим username при необходимости
                    if username:
                        d_cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                else:
                    # Пользователя нет в основной БД — можно пропустить, т.к. будет создан при первом обращении.
                    # Если очень нужно — раскомментировать вставку с безопасными дефолтами.
                    pass

        # Перенос custom_names, profile_privacy если в целевых таблицах пусто
        for table in ("custom_names", "profile_privacy"):
            d_cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not d_cur.fetchone()[0]:
                continue
            d_cur.execute(f"SELECT COUNT(*) FROM {table}")
            if d_cur.fetchone()[0] > 0:
                continue
            s_cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not s_cur.fetchone()[0]:
                continue
            s_cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in s_cur.fetchall()]
            col_list = ",".join(cols)
            placeholders = ",".join(["?"] * len(cols))
            s_cur.execute(f"SELECT {col_list} FROM {table}")
            rows = s_cur.fetchall()
            if rows:
                d_cur.executemany(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                    rows
                )
        dst.commit()
        try:
            print("✅ Миграция данных из referral_bot.db завершена")
        except Exception:
            pass
    finally:
        try:
            src.close()
        finally:
            dst.close()

def init_db():
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            dan INTEGER DEFAULT 0,         -- Дань ✨
            kruz INTEGER DEFAULT 0,        -- Кусочек Круза ⭐️
            last_free INTEGER DEFAULT 0,   -- timestamp of last free give
            ref_by INTEGER DEFAULT NULL,   -- who invited this user
            ref_count INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            first_bet INTEGER DEFAULT 0,
            farm_level INTEGER DEFAULT 1,
            farm_income INTEGER DEFAULT 10,
            farm_capacity INTEGER DEFAULT 40,
            farm_stored INTEGER DEFAULT 0,
            farm_last_collected INTEGER DEFAULT 0,
            dan_win INTEGER DEFAULT 0,     -- Выиграно дань
            dan_lose INTEGER DEFAULT 0,    -- Проиграно дань
            win_count INTEGER DEFAULT 0,   -- Кол-во выигрышей
            lose_count INTEGER DEFAULT 0   -- Кол-во проигрышей
        )
        """)
        # Автоматически добавляем win_count, lose_count, dan_win, dan_lose, reg_date, first_name для старых пользователей
        cur.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cur.fetchall()]
        if "win_count" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN win_count INTEGER DEFAULT 0")
        if "lose_count" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN lose_count INTEGER DEFAULT 0")
        if "dan_win" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN dan_win INTEGER DEFAULT 0")
        if "dan_lose" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN dan_lose INTEGER DEFAULT 0")
        if "reg_date" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN reg_date TEXT")
        if "first_name" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        if "last_name" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
        if "xp" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
        if "level" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
        if "pending_level_rewards" not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN pending_level_rewards INTEGER DEFAULT 0")
        conn.commit()
        conn.close()
        
        # Создаем все необходимые таблицы
        print("🔧 Создаем таблицы базы данных...")
        
        # Создаем таблицу инвентаря
        create_inventory_table()
        print("✅ Таблица inventory создана")
        
        # Создаем таблицу ставок
        create_bets_table()
        print("✅ Таблица bets создана")
        
        # Создаем таблицу банов
        create_bans_table()
        print("✅ Таблица bans создана")
        
        # Создаем таблицу эффектов
        create_user_effects_table()
        print("✅ Таблица user_effects создана")
        
        # Создаем таблицу аукциона
        create_auction_table()
        print("✅ Таблица auction_items создана")
        
        # Создаем таблицу наград за уровень
        create_level_rewards_table()
        print("✅ Таблица level_rewards создана")
        
        # Создаем таблицы лотереи
        create_lottery_tables()
        print("✅ Таблицы lottery создана")
        
        # Создаем таблицы реферальной системы
        create_referral_tables()
        print("✅ Таблицы referral системы созданы")
        
        print("🎉 Все таблицы базы данных успешно созданы!")

# Увеличить счетчик выигранной дань и количество выигрышей
def increment_dan_win(user_id: int, amount: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET dan_win = dan_win + ?, win_count = win_count + 1 WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

# Увеличить счетчик проигранной дань и количество проигрышей
def increment_dan_lose(user_id: int, amount: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET dan_lose = dan_lose + ?, lose_count = lose_count + 1 WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
def save_bet(bet_id: str, chat_id: int, msg_id: int, text: str, created_by: int):
    import time
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("REPLACE INTO bets (bet_id, chat_id, msg_id, text, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (bet_id, chat_id, msg_id, text, created_by, int(time.time())))
        conn.commit()
        conn.close()

def get_bet(bet_id: str):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,))
        row = cur.fetchone()
        conn.close()
        return row

def get_all_bets():
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM bets ORDER BY created_at DESC")
        rows = cur.fetchall()
        conn.close()
        return rows

def delete_bet(bet_id: str):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM bets WHERE bet_id = ?", (bet_id,))
        conn.commit()
        conn.close()

def ensure_user(user_id: int, username: str = None, ref_by: int = None, first_name: str = None, last_name: str = None):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
                import datetime
                reg_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # Создаем нового пользователя с начальным балансом 500 ДАНЬ
                cur.execute(
                    "INSERT INTO users (user_id, username, ref_by, reg_date, dan, first_name, last_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, ref_by, reg_date, 500, first_name, last_name),
                )
                conn.commit()
                print(f"🎉 Новый пользователь {user_id} создан с балансом 500 ДАНЬ!")
                if ref_by:
                    # increment ref_count for referrer
                    cur.execute("UPDATE users SET ref_count = ref_count + 1, dan = dan + ? WHERE user_id = ?",
                                (175, ref_by))
                    conn.commit()
        else:
            # Обновляем информацию пользователя если она изменилась
            updates = []
            params = []
            
            # Безопасная проверка с обработкой отсутствующих колонок
            try:
                if username and row["username"] != username:
                    updates.append("username = ?")
                    params.append(username)
            except (KeyError, IndexError):
                if username:
                    updates.append("username = ?")
                    params.append(username)
            
            try:
                if first_name and row["first_name"] != first_name:
                    updates.append("first_name = ?") 
                    params.append(first_name)
            except (KeyError, IndexError):
                if first_name:
                    updates.append("first_name = ?")
                    params.append(first_name)
            
            try:
                if last_name and row["last_name"] != last_name:
                    updates.append("last_name = ?")
                    params.append(last_name)
            except (KeyError, IndexError):
                if last_name:
                    updates.append("last_name = ?")
                    params.append(last_name)
            
            if updates:
                params.append(user_id)
                cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
                conn.commit()
        conn.close()

def get_user(user_id: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            # Преобразуем row в dict для удобства
            return dict(row)
        return None

def get_balance(user_id: int):
    row = get_user(user_id)
    if row:
        return {"dan": row["dan"], "kruz": row["kruz"], "games_played": row["games_played"], "first_bet": row["first_bet"]}
    return None

def add_dan(user_id: int, amount: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET dan = dan + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

def add_kruz(user_id: int, amount: int):
    with _lock:
        conn = _connect()
        cur = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET kruz = kruz + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

def add_xp(user_id: int, amount: int):
    """Добавляет опыт пользователю с автоматическим повышением уровня"""
    XP_PER_LEVEL = 5000
    
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Получаем текущие значения
        cur.execute("SELECT xp, level, pending_level_rewards FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        
        if not row:
            conn.close()
            return {'xp': 0, 'level': 1, 'leveled_up': False, 'levels_gained': 0, 'pending_rewards': 0}
        
        current_xp = row[0] if row[0] else 0
        current_level = row[1] if row[1] else 1
        pending_rewards = row[2] if row[2] else 0
        
        # Добавляем опыт
        new_xp = current_xp + amount
        new_level = current_level
        levels_gained = 0
        
        # Проверяем повышение уровня
        while new_xp >= XP_PER_LEVEL:
            new_xp -= XP_PER_LEVEL
            new_level += 1
            levels_gained += 1
        
        new_pending = pending_rewards + levels_gained
        
        # Обновляем в базе
        cur.execute("""
            UPDATE users 
            SET xp = ?, level = ?, pending_level_rewards = ? 
            WHERE user_id = ?
        """, (new_xp, new_level, new_pending, user_id))
        
        conn.commit()
        conn.close()
        
        return {
            'xp': new_xp,
            'level': new_level,
            'leveled_up': levels_gained > 0,
            'levels_gained': levels_gained,
            'pending_rewards': new_pending
        }

def get_user_xp_data(user_id: int):
    """Получает данные об опыте и уровне пользователя"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT xp, level, pending_level_rewards FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return {'xp': 0, 'level': 1, 'pending_level_rewards': 0}
        
        return {
            'xp': row[0] if row[0] else 0,
            'level': row[1] if row[1] else 1,
            'pending_level_rewards': row[2] if row[2] else 0
        }

def claim_level_reward(user_id: int):
    """Уменьшает счетчик наград на 1"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Получаем текущее количество
        cur.execute("SELECT pending_level_rewards FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        
        if not row or row[0] <= 0:
            conn.close()
            return False
        
        # Уменьшаем на 1
        new_pending = row[0] - 1
        cur.execute("UPDATE users SET pending_level_rewards = ? WHERE user_id = ?", (new_pending, user_id))
        conn.commit()
        conn.close()
        return True

def set_first_bet(user_id: int, amount: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET first_bet = ? WHERE user_id = ? AND first_bet = 0", (amount, user_id))
        conn.commit()
        conn.close()

def increment_games(user_id: int):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET games_played = games_played + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

def can_get_free(user_id: int, cooldown_seconds: int = 7 * 24 * 3600):
    row = get_user(user_id)
    if not row:
        return True
    last = row["last_free"]
    now = int(time.time())
    return (now - last) >= cooldown_seconds

def grant_free(user_id: int, amount: int = 50):
    with _lock:
        now = int(time.time())
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET dan = dan + ?, last_free = ? WHERE user_id = ?", (amount, now, user_id))
        conn.commit()
        conn.close()

def withdraw_dan(user_id: int, amount: int) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT dan FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["dan"] < amount:
            conn.close()
            return False
        cur.execute("UPDATE users SET dan = dan - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True

def withdraw_kruz(user_id: int, amount: int) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT kruz FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["kruz"] < amount:
            conn.close()
            return False
        cur.execute("UPDATE users SET kruz = kruz - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True

# Функции для работы с наградами за уровень
def get_all_level_rewards(user_level: int = None):
    """Получить все активные награды, доступные для указанного уровня"""
    with _lock:
        conn = _connect()
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
        cur = conn.cursor()
        
        if user_level is not None:
            cur.execute("""
                SELECT * FROM level_rewards 
                WHERE enabled = 1 
                AND min_level <= ? 
                AND max_level >= ?
                ORDER BY slot, chance DESC
            """, (user_level, user_level))
        else:
            cur.execute("SELECT * FROM level_rewards WHERE enabled = 1 ORDER BY slot, chance DESC")
        
        rows = cur.fetchall()
        conn.close()
        
        rewards = []
        for row in rows:
            rewards.append({
                'id': row['id'],
                'reward_type': row['reward_type'],
                'reward_id': row['reward_id'],
                'reward_amount_min': row['reward_amount_min'],
                'reward_amount_max': row['reward_amount_max'],
                'reward_name': row['reward_name'],
                'chance': row['chance'],
                'slot': row['slot'],
                'min_level': row['min_level'],
                'max_level': row['max_level'],
                'enabled': row['enabled'],
                'description': row['description']
            })
        
        return rewards

def generate_random_level_rewards(user_level: int, count: int = 3):
    """Генерирует случайные награды из разных слотов на основе шансов из БД"""
    import random
    
    # Получаем все доступные награды для уровня
    all_rewards = get_all_level_rewards(user_level)
    
    if not all_rewards:
        # Если нет наград в БД, возвращаем заглушку
        return [
            {'reward_type': 'currency', 'reward_id': 'dan', 'reward_amount': 1000, 'reward_name': 'Дань'},
            {'reward_type': 'currency', 'reward_id': 'dan', 'reward_amount': 2000, 'reward_name': 'Дань'},
            {'reward_type': 'currency', 'reward_id': 'dan', 'reward_amount': 5000, 'reward_name': 'Дань'}
        ]
    
    # Разделяем награды по слотам
    slots = {}
    for reward in all_rewards:
        slot_num = reward.get('slot', 1)
        if slot_num not in slots:
            slots[slot_num] = []
        slots[slot_num].append(reward)
    
    # Генерируем награды для каждого слота
    selected_rewards = []
    for slot_num in range(1, count + 1):
        if slot_num not in slots or not slots[slot_num]:
            continue
        
        # Создаем взвешенный список на основе шансов
        weighted_rewards = []
        for reward in slots[slot_num]:
            weighted_rewards.extend([reward] * int(reward['chance'] * 10))
        
        if weighted_rewards:
            selected = random.choice(weighted_rewards)
            
            # Генерируем случайное количество в диапазоне min-max
            amount_min = selected.get('reward_amount_min', 1)
            amount_max = selected.get('reward_amount_max', 1)
            amount = random.randint(amount_min, amount_max)
            
            selected_rewards.append({
                'reward_type': selected['reward_type'],
                'reward_id': selected['reward_id'],
                'reward_amount': amount,
                'reward_name': selected['reward_name'],
                'description': selected.get('description', ''),
                'slot': slot_num
            })
    
    return selected_rewards

def add_level_reward(reward_type: str, reward_id: str, reward_amount: int, 
                     reward_name: str, chance: float, min_level: int = 1, 
                     max_level: int = 999, description: str = ""):
    """Добавить новую награду в базу"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO level_rewards 
            (reward_type, reward_id, reward_amount, reward_name, chance, min_level, max_level, enabled, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (reward_type, reward_id, reward_amount, reward_name, chance, min_level, max_level, description))
        conn.commit()
        conn.close()

def update_level_reward(reward_id_db: int, **kwargs):
    """Обновить существующую награду"""
    allowed_fields = ['reward_type', 'reward_id', 'reward_amount', 'reward_name', 
                     'chance', 'min_level', 'max_level', 'enabled', 'description']
    
    updates = []
    values = []
    for key, value in kwargs.items():
        if key in allowed_fields:
            updates.append(f"{key} = ?")
            values.append(value)
    
    if not updates:
        return
    
    values.append(reward_id_db)
    
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(f"UPDATE level_rewards SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
        conn.close()

def delete_level_reward(reward_id_db: int):
    """Удалить награду из базы"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM level_rewards WHERE id = ?", (reward_id_db,))
        conn.commit()
        conn.close()

# Функции для работы с банами
def add_ban(user_id: int, banned_until: int, banned_by: int, reason: str):
    """Добавить бан пользователю"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO bans (user_id, banned_until, banned_by, reason) VALUES (?, ?, ?, ?)", 
                   (user_id, banned_until, banned_by, reason))
        conn.commit()
        conn.close()

def is_banned(user_id: int) -> bool:
    """Проверить забанен ли пользователь"""
    import time
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT banned_until FROM bans WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return False
        
        # Если время бана истекло, удаляем запись
        if row[0] <= int(time.time()):
            remove_ban(user_id)
            return False
        
        return True

def remove_ban(user_id: int):
    """Удалить бан пользователя"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

# Функции для работы с эффектами
def add_user_effect(user_id: int, effect_type: str, effect_data: str, duration_hours: int):
    """Добавить эффект пользователю"""
    import time
    expires_at = int(time.time()) + (duration_hours * 3600)
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("INSERT INTO user_effects (user_id, effect_type, effect_data, expires_at) VALUES (?, ?, ?, ?)", 
                   (user_id, effect_type, effect_data, expires_at))
        conn.commit()
        conn.close()

def get_user_effect(user_id: int, effect_type: str):
    """Получить активный эффект пользователя"""
    import time
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_effects WHERE user_id = ? AND effect_type = ? AND expires_at > ? ORDER BY expires_at DESC LIMIT 1", 
                   (user_id, effect_type, int(time.time())))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "id": row[0],
                "user_id": row[1],
                "effect_type": row[2],
                "effect_data": row[3],
                "expires_at": row[4],
                "created_at": row[5]
            }
        return None

def remove_expired_effects():
    """Удалить истекшие эффекты"""
    import time
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_effects WHERE expires_at <= ?", (int(time.time()),))
        conn.commit()
        conn.close()

# --- AUCTION FUNCTIONS ---

def create_auction_table():
    """Создать таблицу для аукционных лотов"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auction_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price_per_item INTEGER NOT NULL,
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        expires_at INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        buyer_id INTEGER DEFAULT NULL,
        sold_at INTEGER DEFAULT NULL,
        -- Расширение для индивидуальных животных
        owned_animal_id INTEGER DEFAULT NULL,
        base_animal_item_id TEXT DEFAULT NULL,
        animal_last_fed_time INTEGER DEFAULT NULL
    );
    """)
    # Индексы для ускорения выборок/очистки
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auction_active ON auction_items(status, expires_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auction_seller_active ON auction_items(seller_id, status, expires_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auction_created ON auction_items(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auction_id_status ON auction_items(id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auction_buyer ON auction_items(buyer_id)")
    # Миграция для уже существующей таблицы: добавляем колонки, если их нет
    try:
        cur.execute("PRAGMA table_info(auction_items)")
        cols = [row[1] for row in cur.fetchall()]
        if 'owned_animal_id' not in cols:
            cur.execute("ALTER TABLE auction_items ADD COLUMN owned_animal_id INTEGER DEFAULT NULL")
        if 'base_animal_item_id' not in cols:
            cur.execute("ALTER TABLE auction_items ADD COLUMN base_animal_item_id TEXT DEFAULT NULL")
        if 'animal_last_fed_time' not in cols:
            cur.execute("ALTER TABLE auction_items ADD COLUMN animal_last_fed_time INTEGER DEFAULT NULL")
    except Exception as _mig_e:
        pass
    conn.commit()
    conn.close()

def create_level_rewards_table():
    """Создать таблицу для наград за уровень"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS level_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reward_type TEXT NOT NULL,
        reward_id TEXT,
        reward_amount_min INTEGER DEFAULT 1,
        reward_amount_max INTEGER DEFAULT 1,
        reward_name TEXT NOT NULL,
        chance REAL NOT NULL,
        slot INTEGER DEFAULT 1,
        min_level INTEGER DEFAULT 1,
        max_level INTEGER DEFAULT 999,
        enabled INTEGER DEFAULT 1,
        description TEXT
    );
    """)
    
    # Проверяем наличие колонки slot
    cur.execute("PRAGMA table_info(level_rewards)")
    columns = [row[1] for row in cur.fetchall()]
    if 'slot' not in columns:
        cur.execute("ALTER TABLE level_rewards ADD COLUMN slot INTEGER DEFAULT 1")
    if 'reward_amount_min' not in columns:
        cur.execute("ALTER TABLE level_rewards ADD COLUMN reward_amount_min INTEGER DEFAULT 1")
    if 'reward_amount_max' not in columns:
        cur.execute("ALTER TABLE level_rewards ADD COLUMN reward_amount_max INTEGER DEFAULT 1")
    
    # Проверяем, есть ли уже данные в таблице
    cur.execute("SELECT COUNT(*) FROM level_rewards")
    count = cur.fetchone()[0]
    
    # Если таблица пустая, добавляем базовые награды
    if count == 0:
        default_rewards = [
            # СЛОТ 1 - КРУТЫЕ НАГРАДЫ (сундуки, много денег, редкие предметы)
            ('item', 'case_1', 1, 1, 'Сундук 1 lvl', 25.0, 1, 1, 999, 1, 'Обычный сундук'),
            ('item', 'case_2', 1, 1, 'Сундук 2 lvl', 15.0, 1, 1, 999, 1, 'Редкий сундук'),
            ('item', 'case_3', 1, 1, 'Сундук 3 lvl', 8.0, 1, 1, 999, 1, 'Эпический сундук'),
            ('currency', 'dan', 10000, 10000, 'Много дань', 2.0, 1, 1, 999, 1, 'ДЖЕКПОТ: 10000 дань'),
            ('special', 'infinite_farm', 1, 1, 'Бесконечная ферма', 1.0, 1, 1, 999, 1, 'ЛЕГЕНДА: Безлимитная ферма'),
            ('currency', 'dan', 3000, 7000, 'Куча дань', 10.0, 1, 1, 999, 1, 'Много дани'),
            ('currency', 'pts', 20, 50, 'Много PTS', 12.0, 1, 1, 999, 1, 'Рейтинговые очки'),
            ('item', 'treasure', 1, 1, 'Сокровище', 5.0, 1, 1, 999, 1, 'Ценная награда'),
            
            # СЛОТ 2 - СРЕДНИЕ НАГРАДЫ (деньги, pts, кейсы 1 лвл, кукуруза/пшеница)
            ('currency', 'dan', 500, 3000, 'Дань', 30.0, 2, 1, 999, 1, 'Игровая валюта'),
            ('currency', 'pts', 5, 15, 'PTS', 25.0, 2, 1, 999, 1, 'Рейтинговые очки'),
            ('item', 'case_1', 1, 1, 'Сундук 1 lvl', 15.0, 2, 1, 999, 1, 'Обычный сундук'),
            ('item', 'corn', 5, 15, 'Кукуруза', 15.0, 2, 1, 999, 1, 'Корм для фермы'),
            ('item', 'wheat', 5, 10, 'Пшеница', 15.0, 2, 1, 999, 1, 'Корм для фермы'),
            
            # СЛОТ 3 - ПРОСТЫЕ НАГРАДЫ (всегда пшеница или кукуруза)
            ('item', 'wheat', 1, 20, 'Пшеница', 50.0, 3, 1, 999, 1, 'Зерно для фермы'),
            ('item', 'corn', 1, 20, 'Кукуруза', 50.0, 3, 1, 999, 1, 'Зерно для фермы'),
        ]
        cur.executemany("""
            INSERT INTO level_rewards 
            (reward_type, reward_id, reward_amount_min, reward_amount_max, reward_name, chance, slot, min_level, max_level, enabled, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_rewards)
    
    conn.commit()
    conn.close()

def add_auction_item(seller_id: int, item_id: str, quantity: int, price_per_item: int, hours: int = 24):
    """Выставить предмет на аукцион.
    Поддерживает как обычные предметы (inventory), так и индивидуальных животных (формат item_id 'XX@owned_id').
    Для животных quantity принудительно = 1.
    """
    import time
    
    # Ветвление: индивидуальное животное
    if '@' in item_id:
        base_id, owned_id_str = item_id.split('@', 1)
        try:
            owned_id = int(owned_id_str)
        except ValueError:
            return {"error": "Некорректный ID животного"}
        # Проверяем, что животное существует у продавца
        try:
            from ferma import get_owned_animal
            owned = get_owned_animal(seller_id, owned_id)
        except Exception:
            owned = None
        if not owned or owned.get('item_id') != base_id:
            return {"error": "Животное не найдено у продавца"}
        # Резервируем животное: удаляем из owned_animals и записываем данные в лот
        try:
            from ferma import remove_owned_animal_by_id
            ok = remove_owned_animal_by_id(seller_id, owned_id)
        except Exception as e:
            ok = False
        if not ok:
            return {"error": "Не удалось зарезервировать животное"}
        expires_at = int(time.time()) + (hours * 3600)
        with _lock:
            conn = _connect()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO auction_items (
                    seller_id, item_id, quantity, price_per_item, expires_at,
                    owned_animal_id, base_animal_item_id, animal_last_fed_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (seller_id, base_id, 1, price_per_item, expires_at,
                 owned.get('id'), base_id, int(owned.get('last_fed_time') or 0))
            )
            auction_id = cur.lastrowid
            conn.commit()
            conn.close()
        return {"success": True, "auction_id": auction_id}

    # Обычные предметы из инвентаря
    # Проверяем, есть ли у продавца такое количество предметов
    inventory = get_inventory(seller_id)
    user_count = 0
    for inv_item_id, inv_count in inventory:
        if inv_item_id == item_id:
            user_count = inv_count
            break
    if user_count < quantity:
        return {"error": f"У вас недостаточно предметов. В наличии: {user_count}"}
    # Забираем предметы из инвентаря (они будут возвращены при покупке/истечении)
    remove_item(seller_id, item_id, quantity)
    expires_at = int(time.time()) + (hours * 3600)
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO auction_items (seller_id, item_id, quantity, price_per_item, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (seller_id, item_id, quantity, price_per_item, expires_at)
        )
        auction_id = cur.lastrowid
        conn.commit()
        conn.close()
    return {"success": True, "auction_id": auction_id}

def get_auction_items(page: int = 1, per_page: int = 10, seller_id: int | None = None):
    """Получить список активных лотов"""
    import time
    offset = (page - 1) * per_page
    
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        if seller_id:
            # Лоты конкретного продавца
            cur.execute("""
                SELECT id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status
                FROM auction_items 
                WHERE seller_id = ? AND status = 'active' AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (seller_id, int(time.time()), per_page, offset))
        else:
            # Все активные лоты
            cur.execute("""
                SELECT id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status
                FROM auction_items 
                WHERE status = 'active' AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (int(time.time()), per_page, offset))
        
        items = cur.fetchall()
        
        # Считаем общее количество
        if seller_id:
            cur.execute("SELECT COUNT(*) FROM auction_items WHERE seller_id = ? AND status = 'active' AND expires_at > ?", 
                       (seller_id, int(time.time())))
        else:
            cur.execute("SELECT COUNT(*) FROM auction_items WHERE status = 'active' AND expires_at > ?", 
                       (int(time.time()),))
        
        total = cur.fetchone()[0]
        conn.close()
        
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }

def buy_auction_item(buyer_id: int, auction_id: int):
    """Купить предмет с аукциона"""
    import time
    
    # Сначала получаем данные и делаем проверки БЕЗ блокировки
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Получаем всю информацию о лоте одним запросом
        cur.execute("""
            SELECT seller_id, item_id, quantity, price_per_item, status, expires_at,
                   owned_animal_id, base_animal_item_id, animal_last_fed_time
            FROM auction_items WHERE id = ? AND status = 'active'
        """, (auction_id,))
        
        auction = cur.fetchone()
        if not auction:
            conn.close()
            return {"error": "Лот не найден или уже неактивен"}
        
        seller_id, item_id, quantity, price_per_item, status, expires_at, owned_animal_id, base_animal_item_id, animal_last_fed_time = auction
        
        if expires_at <= int(time.time()):
            conn.close()
            return {"error": "Срок лота истёк"}
        
        if seller_id == buyer_id:
            conn.close()
            return {"error": "Нельзя покупать свои лоты"}
        
        total_price = quantity * price_per_item
        
        # Проверяем баланс покупателя
        cur.execute("SELECT dan FROM users WHERE user_id = ?", (buyer_id,))
        buyer_row = cur.fetchone()
        if not buyer_row or buyer_row[0] < total_price:
            conn.close()
            return {"error": f"Недостаточно средств. Нужно: {total_price} дань"}
        
        conn.close()
    
    # Определяем тип предмета
    is_animal = owned_animal_id is not None or base_animal_item_id is not None
    
    # Если это животное, создаём owned_animal ДО транзакции
    if is_animal:
        try:
            from ferma import add_owned_animal
            last_fed = int(animal_last_fed_time or 0)
            print(f"🐄 Добавляем животное покупателю {buyer_id}: item_id={base_animal_item_id}, last_fed={last_fed}")
            add_owned_animal(buyer_id, base_animal_item_id, last_fed)
            print(f"✅ Животное успешно добавлено покупателю {buyer_id}")
        except Exception as e:
            print(f"❌ Ошибка добавления животного: {e}")
            import traceback
            traceback.print_exc()
            return {"error": f"Ошибка передачи животного: {e}"}
    
    # Теперь быстрая транзакция для денег и статуса
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        try:
            cur.execute("BEGIN IMMEDIATE")
        except Exception:
            pass
        
        # Проверяем что лот всё ещё активен (double-check)
        cur.execute("SELECT status FROM auction_items WHERE id = ?", (auction_id,))
        check = cur.fetchone()
        if not check or check[0] != 'active':
            conn.rollback()
            conn.close()
            # Если животное уже создано - откатываем (TODO: удалить животное)
            return {"error": "Лот уже продан"}
        
        # Списываем/начисляем деньги
        cur.execute("UPDATE users SET dan = dan - ? WHERE user_id = ?", (total_price, buyer_id))
        cur.execute("UPDATE users SET dan = dan + ? WHERE user_id = ?", (total_price, seller_id))
        
        # Для обычных предметов добавляем в инвентарь
        if not is_animal:
            cur.execute("INSERT OR IGNORE INTO inventory (user_id, item_id, count) VALUES (?, ?, 0)", (buyer_id, item_id))
            cur.execute("UPDATE inventory SET count = count + ? WHERE user_id = ? AND item_id = ?", 
                       (quantity, buyer_id, item_id))
        
        # Помечаем лот как проданный
        cur.execute("""
            UPDATE auction_items 
            SET status = 'sold', buyer_id = ?, sold_at = ?
            WHERE id = ?
        """, (buyer_id, int(time.time()), auction_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "item_id": item_id,
            "quantity": quantity,
            "total_price": total_price,
            "seller_id": seller_id
        }

def remove_auction_item(seller_id: int, auction_id: int):
    """Снять лот с аукциона (только свой)"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Проверяем, принадлежит ли лот продавцу
        cur.execute("""
            SELECT seller_id, item_id, quantity, status 
            FROM auction_items WHERE id = ? AND seller_id = ?
        """, (auction_id, seller_id))
        
        auction = cur.fetchone()
        if not auction:
            conn.close()
            return {"error": "Лот не найден или не принадлежит вам"}
        
        seller, item_id, quantity, status = auction
        
        if status != 'active':
            conn.close()
            return {"error": "Лот уже продан или неактивен"}
        
        # Возвращаем предметы продавцу
        # Проверим, был ли это лот с индивидуальным животным
        cur.execute("SELECT owned_animal_id, base_animal_item_id, animal_last_fed_time FROM auction_items WHERE id = ?", (auction_id,))
        animal_row = cur.fetchone()
        is_animal = False
        if animal_row and (animal_row[0] is not None or animal_row[1] is not None):
            is_animal = True
        if is_animal:
            try:
                from ferma import add_owned_animal
                base_animal_item_id = animal_row[1]
                last_fed = int(animal_row[2] or 0)
                add_owned_animal(seller_id, base_animal_item_id, last_fed)
            except Exception:
                conn.close()
                return {"error": "Не удалось вернуть животное продавцу"}
        else:
            cur.execute("SELECT count FROM inventory WHERE user_id = ? AND item_id = ?", (seller_id, item_id))
            existing_row = cur.fetchone()
            if existing_row:
                cur.execute("UPDATE inventory SET count = count + ? WHERE user_id = ? AND item_id = ?", 
                           (quantity, seller_id, item_id))
            else:
                cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", 
                           (seller_id, item_id, quantity))
        
        # Помечаем лот как отменённый
        cur.execute("UPDATE auction_items SET status = 'cancelled' WHERE id = ?", (auction_id,))
        
        conn.commit()
        conn.close()
        
        return {"success": True, "item_id": item_id, "quantity": quantity}

def cleanup_expired_auctions():
    """Очистить истёкшие аукционы и вернуть предметы продавцам"""
    import time
    
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Находим истёкшие активные лоты
        cur.execute("""
            SELECT id, seller_id, item_id, quantity 
            FROM auction_items 
            WHERE status = 'active' AND expires_at <= ?
        """, (int(time.time()),))
        
        expired_auctions = cur.fetchall()
        
        for auction_id, seller_id, item_id, quantity in expired_auctions:
            # Определяем, животное ли это
            cur.execute("SELECT owned_animal_id, base_animal_item_id, animal_last_fed_time FROM auction_items WHERE id = ?", (auction_id,))
            animal_row = cur.fetchone()
            is_animal = False
            if animal_row and (animal_row[0] is not None or animal_row[1] is not None):
                is_animal = True
            if is_animal:
                try:
                    from ferma import add_owned_animal
                    base_animal_item_id = animal_row[1]
                    last_fed = int(animal_row[2] or 0)
                    add_owned_animal(seller_id, base_animal_item_id, last_fed)
                except Exception:
                    pass
            else:
                cur.execute("SELECT count FROM inventory WHERE user_id = ? AND item_id = ?", (seller_id, item_id))
                existing_row = cur.fetchone()
                if existing_row:
                    cur.execute("UPDATE inventory SET count = count + ? WHERE user_id = ? AND item_id = ?", 
                               (quantity, seller_id, item_id))
                else:
                    cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", 
                               (seller_id, item_id, quantity))
            # Помечаем лот как истёкший
            cur.execute("UPDATE auction_items SET status = 'expired' WHERE id = ?", (auction_id,))
        
        conn.commit()
        conn.close()
        
        return len(expired_auctions)

def buy_auction_item_partial(buyer_id: int, auction_id: int, buy_quantity: int):
    """Купить определенное количество предметов с аукциона (частичная покупка)"""
    import time
    
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        
        # Явно начинаем транзакцию
        try:
            cur.execute("BEGIN IMMEDIATE")
        except Exception:
            pass

        # Получаем информацию о лоте
        cur.execute("""
            SELECT seller_id, item_id, quantity, price_per_item, status, expires_at
            FROM auction_items WHERE id = ?
        """, (auction_id,))
        
        auction = cur.fetchone()
        if not auction:
            conn.close()
            return {"error": "Лот не найден"}
        
        seller_id, item_id, quantity, price_per_item, status, expires_at = auction
        
        if status != 'active':
            conn.close()
            return {"error": "Лот уже продан или неактивен"}
        
        if expires_at <= int(time.time()):
            conn.close()
            return {"error": "Срок лота истёк"}
        
        if seller_id == buyer_id:
            conn.close()
            return {"error": "Нельзя покупать свои лоты"}
        
        # Проверяем, что запрошенное количество не больше доступного
        if buy_quantity > quantity:
            conn.close()
            return {"error": f"В лоте только {quantity} предметов"}
        
        if buy_quantity <= 0:
            conn.close()
            return {"error": "Количество должно быть больше 0"}
        
        total_price = buy_quantity * price_per_item
        
        # Проверяем баланс покупателя
        cur.execute("SELECT dan FROM users WHERE user_id = ?", (buyer_id,))
        buyer_row = cur.fetchone()
        if not buyer_row or buyer_row[0] < total_price:
            conn.close()
            return {"error": f"Недостаточно средств. Нужно: {total_price} дань"}
        
        # Выполняем транзакцию
        # Списываем деньги с покупателя
        cur.execute("UPDATE users SET dan = dan - ? WHERE user_id = ?", (total_price, buyer_id))
        
        # Начисляем деньги продавцу
        cur.execute("UPDATE users SET dan = dan + ? WHERE user_id = ?", (total_price, seller_id))
        
        # Передаём предметы покупателю
        cur.execute("SELECT count FROM inventory WHERE user_id = ? AND item_id = ?", (buyer_id, item_id))
        existing_row = cur.fetchone()
        
        if existing_row:
            # Обновляем количество существующего предмета
            cur.execute("UPDATE inventory SET count = count + ? WHERE user_id = ? AND item_id = ?", 
                       (buy_quantity, buyer_id, item_id))
        else:
            # Добавляем новый предмет
            cur.execute("INSERT INTO inventory (user_id, item_id, count) VALUES (?, ?, ?)", 
                       (buyer_id, item_id, buy_quantity))
        
        # Обновляем количество в лоте
        remaining_quantity = quantity - buy_quantity
        
        if remaining_quantity <= 0:
            # Лот полностью распродан
            cur.execute("""
                UPDATE auction_items 
                SET status = 'sold', buyer_id = ?, sold_at = ?, quantity = 0
                WHERE id = ?
            """, (buyer_id, int(time.time()), auction_id))
        else:
            # Уменьшаем количество в лоте
            cur.execute("""
                UPDATE auction_items 
                SET quantity = ?
                WHERE id = ?
            """, (remaining_quantity, auction_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "item_id": item_id,
            "quantity": buy_quantity,
            "total_price": total_price,
            "seller_id": seller_id,
            "remaining_in_lot": remaining_quantity
        }

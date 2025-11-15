# Проверка фермы пользователя - только обновляет данные без автосбора
def check_ferma(user_id: int):
    """
    Проверяет ферму пользователя и обновляет данные о накопившейся дани для отображения.
    НЕ собирает дань автоматически - пользователь должен сам нажать "Собрать дань".
    Вызывается при каждом открытии меню фермы для актуальных данных.
    """
    try:
        # Просто обновляем/проверяем данные фермы, не собираем дань
        # Это обеспечивает актуальность данных для отображения в меню
        farm = get_farm(user_id)  # Получает актуальные данные из БД
        
        # Рассчитываем сколько дани можно собрать (для отображения потенциального дохода)
        to_add, periods = calculate_income(user_id)
        
        print(f"🌾 Обновлены данные фермы для пользователя {user_id}, доступно для сбора: {to_add:.2f} дани")
        
        # Не собираем дань! Пользователь сам должен нажать "Собрать дань"
        return {'available_to_collect': to_add, 'periods': periods, 'farm': farm}
        
    except Exception as e:
        print(f"❌ Ошибка при обновлении данных фермы: {e}")
        # Если ошибка - не блокируем работу фермы, просто логируем
        return {'available_to_collect': 0, 'periods': 0, 'farm': None}
import database as db
import time

# === СИСТЕМА ЖИВОТНЫХ НА ФЕРМЕ ===

# Маппинг item_id -> тип животного
ANIMAL_ITEMS = {
    '08': 'chicken',  # Курица
    '09': 'cow'       # Корова
}

# Конфигурация животных
ANIMALS_CONFIG = {
    'chicken': {
        'name': '🐔 Курица',
        'item_id': '08',
        'income_per_hour': 50,
        'max_hungry_hours': 12,
        'food_items': ['06', '07'],  # пшеница, кукуруза
    },
    'cow': {
        'name': '🐄 Корова',
        'item_id': '09',
        'income_per_hour': 100,
        'max_hungry_hours': 12,
        'food_items': ['06'],  # Только пшеница
    }
}

# Уровни, на которых открываются слоты и даются животные
ANIMAL_UNLOCK_LEVELS = [3, 5, 7, 9]

def init_animals_table():
    """Создает таблицу для размещенных на ферме животных"""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        
        # Проверяем существование таблицы
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='farm_animals'")
        table_exists = cur.fetchone()
        
        if table_exists:
            # Проверяем структуру таблицы
            cur.execute("PRAGMA table_info(farm_animals)")
            columns_rows = cur.fetchall()
            columns = [row[1] for row in columns_rows]
            
            # Если старая структура (с animal_type вместо animal_item_id)
            if 'animal_type' in columns and 'animal_item_id' not in columns:
                print("🔄 Миграция таблицы farm_animals...")
                # Удаляем старую таблицу
                cur.execute("DROP TABLE farm_animals")
                conn.commit()
                print("✅ Старая таблица удалена")

            # Если нет колонки feed_buffer_hours — добавим миграцией
            if 'feed_buffer_hours' not in columns:
                try:
                    cur.execute("ALTER TABLE farm_animals ADD COLUMN feed_buffer_hours INTEGER DEFAULT 0")
                    conn.commit()
                    print("🔧 Миграция: добавлен столбец feed_buffer_hours в farm_animals")
                except Exception as e:
                    print(f"⚠️ Не удалось добавить feed_buffer_hours: {e}")
        
        # Создаем таблицу с правильной структурой
        cur.execute('''
            CREATE TABLE IF NOT EXISTS farm_animals (
                user_id INTEGER,
                slot_number INTEGER,
                animal_item_id TEXT,
                last_fed_time INTEGER DEFAULT 0,
                feed_buffer_hours INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, slot_number)
            )
        ''')
        conn.commit()
        conn.close()
        print("✅ Таблица farm_animals готова")

# Инициализируем таблицу при импорте модуля
init_animals_table()

# Таблица владения животными (индивидуальные экземпляры вне слотов)
def init_owned_animals_table():
    """Создает таблицу индивидуальных животных пользователя вне слотов фермы"""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS owned_animals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                animal_item_id TEXT,
                last_fed_time INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        conn.close()
        print("✅ Таблица owned_animals готова")

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ИНДИВИДУАЛЬНЫХ ЖИВОТНЫХ ===
def add_owned_animal(user_id: int, animal_item_id: str, last_fed_time: int = 0):
    """Добавляет индивидуальное животное пользователю (в хранилище owned_animals)."""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO owned_animals (user_id, animal_item_id, last_fed_time) VALUES (?, ?, ?)',
            (user_id, animal_item_id, int(last_fed_time or 0))
        )
        conn.commit()
        conn.close()

def list_owned_animals(user_id: int):
    """Возвращает список индивидуальных животных пользователя с их id и памятью кормления."""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, animal_item_id, last_fed_time FROM owned_animals WHERE user_id = ? ORDER BY id ASC',
            (user_id,)
        )
        rows = cur.fetchall()
        conn.close()
    result = []
    for rid, item_id, fed in rows:
        animal_type = ANIMAL_ITEMS.get(item_id, 'unknown')
        name = ANIMALS_CONFIG.get(animal_type, {}).get('name', 'Животное')
        result.append({
            'id': int(rid),
            'item_id': item_id,
            'type': animal_type,
            'name': name,
            'last_fed_time': int(fed or 0),
        })
    return result

def place_specific_owned_animal_on_farm(user_id: int, owned_id: int):
    """Размещает на ферму конкретное животное из owned_animals по его уникальному id.
    Сохраняет last_fed_time. Ошибки, если нет слотов или животное не найдено.
    """
    # Проверяем уровень фермы и доступные слоты
    farm = get_farm(user_id)
    max_slots = get_available_animal_slots(farm['level'])
    if max_slots == 0:
        return {'status': 'error', 'msg': 'У вас нет слотов для животных! Улучшите ферму до уровня 3.'}

    placed_animals = get_user_farm_animals(user_id)
    if len(placed_animals) >= max_slots:
        return {'status': 'error', 'msg': f'Все слоты заняты ({len(placed_animals)}/{max_slots})! Улучшите ферму.'}

    # Находим первый свободный слот
    free_slot = None
    for slot in range(1, max_slots + 1):
        if slot not in placed_animals:
            free_slot = slot
            break
    if free_slot is None:
        return {'status': 'error', 'msg': 'Нет свободных слотов!'}

    # Извлекаем конкретное животное из owned_animals
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('SELECT animal_item_id, last_fed_time FROM owned_animals WHERE user_id=? AND id=?', (user_id, owned_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {'status': 'error', 'msg': 'Это животное не найдено в вашем хранилище!'}
        animal_item_id, last_fed_time = row[0], int(row[1] or 0)
        # Удаляем из owned_animals и размещаем в farm_animals
        cur.execute('DELETE FROM owned_animals WHERE id=?', (owned_id,))
        cur.execute(
            'INSERT INTO farm_animals (user_id, slot_number, animal_item_id, last_fed_time) VALUES (?, ?, ?, ?)',
            (user_id, free_slot, animal_item_id, last_fed_time)
        )
        conn.commit()
        conn.close()

    animal_type = ANIMAL_ITEMS.get(animal_item_id, 'unknown')
    animal_name = ANIMALS_CONFIG.get(animal_type, {}).get('name', 'Животное')
    return {
        'status': 'ok',
        'msg': f'✅ {animal_name} (ID {owned_id}) размещена на ферме в слот {free_slot}!'
    }

def remove_owned_animal_by_id(user_id: int, owned_id: int) -> bool:
    """Удаляет индивидуальное животное по его owned_id для данного пользователя."""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('DELETE FROM owned_animals WHERE user_id=? AND id=?', (user_id, owned_id))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
    return deleted > 0

def get_owned_animal(user_id: int, owned_id: int):
    """Возвращает информацию об индивидуальном животном или None."""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('SELECT id, animal_item_id, last_fed_time FROM owned_animals WHERE user_id=? AND id=?', (user_id, owned_id))
        row = cur.fetchone()
        conn.close()
    if not row:
        return None
    rid, item_id, fed = row
    animal_type = ANIMAL_ITEMS.get(item_id, 'unknown')
    name = ANIMALS_CONFIG.get(animal_type, {}).get('name', 'Животное')
    return {'id': rid, 'item_id': item_id, 'type': animal_type, 'name': name, 'last_fed_time': int(fed or 0)}

init_owned_animals_table()

def get_unassigned_animals_counts(user_id: int):
    """Возвращает количество незадействованных животных по типам (из owned_animals)"""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            SELECT animal_item_id, COUNT(*) FROM owned_animals
            WHERE user_id = ?
            GROUP BY animal_item_id
        ''', (user_id,))
        rows = cur.fetchall()
        conn.close()
    return {item_id: cnt for (item_id, cnt) in rows}

def pop_owned_animal(user_id: int, animal_item_id: str):
    """Извлекает одно животное из owned_animals и возвращает его last_fed_time. Если нет — None"""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, last_fed_time FROM owned_animals
            WHERE user_id = ? AND animal_item_id = ?
            ORDER BY id ASC
            LIMIT 1
        ''', (user_id, animal_item_id))
        row = cur.fetchone()
        if not row:
            print(f"⚠️ pop_owned_animal: У пользователя {user_id} нет животного {animal_item_id} в owned_animals")
            conn.close()
            return None
        animal_id, last_fed = row
        print(f"✅ pop_owned_animal: Извлекаем животное ID={animal_id}, item_id={animal_item_id}, last_fed={last_fed}")
        cur.execute('DELETE FROM owned_animals WHERE id = ?', (animal_id,))
        conn.commit()
        conn.close()
        return int(last_fed or 0)

# Default farm parameters
FARM_DEFAULT = {
    'level': 1,
    'income_per_hour': 10,   # Уровень 1: базовый доход 10/ч
    'warehouse_capacity': 50,  # Уровень 1: базовый склад 50
    'stored_dan': 0,
    'last_collected': 0,
}


# Get farm data for a user (always up-to-date with DB)
def get_farm(user_id: int):
    row = db.get_user(user_id)
    if not row:
        db.ensure_user(user_id)
        row = db.get_user(user_id)
    if not row:  # последний шанс
        return FARM_DEFAULT.copy()
    # Always read from DB (row предполагается dict-подобным)
    row_keys = set(row.keys()) if hasattr(row, 'keys') else set()
    farm = {
        'level': row['farm_level'] if 'farm_level' in row_keys else FARM_DEFAULT['level'],
        'income_per_hour': row['farm_income'] if 'farm_income' in row_keys else FARM_DEFAULT['income_per_hour'],
        'warehouse_capacity': row['farm_capacity'] if 'farm_capacity' in row_keys else FARM_DEFAULT['warehouse_capacity'],
        'stored_dan': row['farm_stored'] if 'farm_stored' in row_keys else FARM_DEFAULT['stored_dan'],
        'last_collected': row['farm_last_collected'] if 'farm_last_collected' in row_keys else FARM_DEFAULT['last_collected'],
    }
    return farm

# Get top N farms by income_per_hour
def get_farm_leaderboard(top_n=10):
    import sqlite3
    conn = db._connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, farm_income FROM users ORDER BY farm_income DESC LIMIT ?", (top_n,))
    rows = cur.fetchall()
    conn.close()
    return rows

# Get position in leaderboard by income_per_hour
def get_farm_leaderboard_position(user_id: int):
    conn = db._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE farm_income > (SELECT farm_income FROM users WHERE user_id = ?)", (user_id,))
    pos = cur.fetchone()[0] + 1
    conn.close()
    return pos

# Upgrade warehouse (increase warehouse_capacity)

def upgrade_warehouse(user_id: int):
    farm = get_farm(user_id)
    user = db.get_user(user_id)
    if not user:
        db.ensure_user(user_id)
        user = db.get_user(user_id)
        if not user:
            return {'status': 'error', 'msg': 'Пользователь не найден'}
    # стоимость, новая вместимость (более плавная и дорогая прогрессия)
    upgrades = [
        (400, 40),
        (900, 55),
        (2000, 70),
        (4500, 90),
        (9000, 120),
        (18000, 170),
        (40000, 230),
        (90000, 320)
    ]
    current_capacity = farm['warehouse_capacity']
    next_upgrade = None
    for cost, capacity in upgrades:
        if capacity > current_capacity:
            next_upgrade = (cost, capacity)
            break
    if not next_upgrade:
        return {'status': 'error', 'msg': 'Максимальная вместимость склада достигнута!'}
    cost, new_capacity = next_upgrade
    if user['dan'] < cost:
        return {'status': 'error', 'msg': f'Недостаточно Дань для улучшения склада! Нужно: {cost}, у вас: {user["dan"]}'}
    db.withdraw_dan(user_id, cost)
    update_farm(user_id, capacity=new_capacity)
    return {
        'status': 'ok',
        'msg': f'Склад улучшен! Новая вместимость: {new_capacity} (минус {cost} Дань)'
    }

# Update farm data for a user
def update_farm(user_id: int, **kwargs):
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"farm_{k} = ?")
        values.append(v)
    if not fields:
        return
    values.append(user_id)
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", tuple(values))
        conn.commit()
        conn.close()

# Calculate dan to collect since last collection
def calculate_income(user_id: int):
    farm = get_farm(user_id)
    now = int(time.time())
    last = farm['last_collected']
    period_seconds = 3600  # 1 час (НЕ уменьшать, чтобы не ускорять фарм)
    periods = (now - last) // period_seconds
    if periods > 0:
        income_per_period = farm['income_per_hour']
        total_income = income_per_period * periods
        
        # Проверяем активен ли бесконечный склад
        infinite_storage = db.get_user_effect(user_id, "infinite_storage")
        if infinite_storage:
            remaining_time = infinite_storage['expires_at'] - now
            if remaining_time > 0:
                # Бесконечный склад активен - нет ограничений
                to_add = total_income
            else:
                # Бесконечный склад истек - применяем ограничения
                available_space = farm['warehouse_capacity'] - farm['stored_dan']
                to_add = min(total_income, max(0, available_space))
        else:
            # Бесконечный склад не активен - применяем ограничения
            available_space = farm['warehouse_capacity'] - farm['stored_dan']
            to_add = min(total_income, max(0, available_space))
        
        return to_add, periods
    else:
        return 0, 0

# Collect dan from farm to warehouse
def collect_dan(user_id: int):
    to_add, periods = calculate_income(user_id)
    if to_add > 0:
        farm = get_farm(user_id)
        new_stored = farm['stored_dan'] + to_add
        update_farm(user_id, stored=new_stored, last_collected=int(time.time()))
    # После начисления дохода, проверяем есть ли дань на складе
    farm = get_farm(user_id)
    if farm['stored_dan'] > 0:
        stored = farm['stored_dan']
        return {'status': 'ok', 'stored_dan': f'{stored:.2f}', 'msg': f'На складе {stored:.2f} Дань.'}
    else:
        return {'status': 'empty', 'stored_dan': '0.00', 'msg': 'На складе нет Дань.'}

# Transfer dan from warehouse to user balance
def transfer_dan_to_balance(user_id: int):
    farm = get_farm(user_id)
    dan = farm['stored_dan']
    # Забираем только целую часть, остаток оставляем
    whole = int(dan)
    fractional = dan - whole
    if whole > 0:
        db.add_dan(user_id, whole)
        update_farm(user_id, stored=fractional)
    return float(f'{whole:.2f}')

# Upgrade farm (level up, increase income/capacity)
# При улучшении фермы автоматически улучшается и склад!

def upgrade_farm(user_id: int):
    farm = get_farm(user_id)
    user = db.get_user(user_id)
    if not user:
        db.ensure_user(user_id)
        user = db.get_user(user_id)
        if not user:
            return {'status': 'error', 'msg': 'Пользователь не найден'}
    
    # Новая прогрессия: стоимость, доход/ч, вместимость склада, уровень
    upgrades = [
        (400, 15, 70, 2),       # Уровень 2: 400 → 15/ч, склад 70
        (1500, 20, 90, 3),      # Уровень 3: 2,000 → 20/ч, склад 90
        (2000, 30, 120, 4),     # Уровень 4: 4,000 → 30/ч, склад 120
        (4500, 50, 300, 5),     # Уровень 5: 7,500 → 50/ч, склад 300
        (6000, 70, 400, 6),    # Уровень 6: 10,000 → 70/ч, склад 400
        (10000, 90, 600, 7),    # Уровень 7: 15,000 → 90/ч, склад 600
        (25000, 110, 800, 8),   # Уровень 8: 25,000 → 110/ч, склад 800
        (30400, 150, 2000, 9),  # Уровень 9: 50,400 → 150/ч, склад 2000
        (70250, 200, 4000, 10) # Уровень 10: 100,000 → 200/ч, склад 4000
    ]
    
    current_level = farm['level']
    next_upgrade = None
    for cost, income, capacity, level in upgrades:
        if level > current_level:
            next_upgrade = (cost, income, capacity, level)
            break
    
    if not next_upgrade:
        return {'status': 'error', 'msg': 'Максимальный уровень фермы достигнут!'}
    
    cost, new_income, new_capacity, new_level = next_upgrade
    
    # Проверяем баланс пользователя
    user_balance = float(user.get('dan', 0))
    if user_balance < cost:
        # Красиво форматируем сообщение об ошибке
        try:
            from main import format_number_beautiful
            balance_formatted = format_number_beautiful(user_balance)
            cost_formatted = format_number_beautiful(cost)
            needed = cost - user_balance
            needed_formatted = format_number_beautiful(needed)
            return {
                'status': 'error', 
                'msg': f'❌ Недостаточно дань!\n\n'
                       f'💰 У вас: {balance_formatted} дань\n'
                       f'💸 Нужно: {cost_formatted} дань\n'
                       f'📈 Не хватает: {needed_formatted} дань'
            }
        except ImportError:
            # Fallback без красивого форматирования
            return {'status': 'error', 'msg': f'❌ Недостаточно дань!\nНужно: {cost}, у вас: {user_balance}'}
    
    # Списываем дань и обновляем ферму (доход, склад и уровень одновременно)
    db.withdraw_dan(user_id, cost)
    update_farm(user_id, income=new_income, capacity=new_capacity, level=new_level)
    
    # Если достигли уровня, на котором даётся животное (3, 5, 7, 9)
    animal_reward = None
    if new_level in ANIMAL_UNLOCK_LEVELS:
        animal_reward = give_random_animal_reward(user_id)
    
    msg = f'✅ Ферма улучшена до уровня {new_level}!\n' \
          f'📈 Доход: {new_income}/ч\n' \
          f'📦 Склад: {new_capacity}\n' \
          f'💸 Стоимость: {cost} Дань'
    
    if animal_reward:
        msg += f'\n\n🎁 Вы получили: {animal_reward["name"]}!\n' \
               f'💡 Разместите животное на ферме через инвентарь или продайте.'
    
    return {
        'status': 'ok',
        'msg': msg,
        'animal_reward': animal_reward
    }

def get_next_upgrade_cost(user_id: int):
    """Получает стоимость следующего улучшения фермы"""
    farm = get_farm(user_id)
    current_level = farm['level']
    
    # Те же данные об улучшениях (синхронизировано с upgrade_farm)
    upgrades = [
        (400, 15, 70, 2),
        (2000, 20, 90, 3),
        (4000, 30, 120, 4),
        (7500, 50, 300, 5),
        (10000, 70, 400, 6),
        (15000, 90, 600, 7),
        (25000, 110, 800, 8),
        (50400, 150, 2000, 9),
        (100000, 200, 4000, 10)
    ]
    
    # Находим следующее улучшение
    for cost, income, capacity, level in upgrades:
        if level > current_level:
            return cost
    
    # Если максимальный уровень - возвращаем None
    return None

# === ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ ЖИВОТНЫМИ ===

def get_available_animal_slots(farm_level: int):
    """Возвращает количество доступных слотов для животных на данном уровне фермы"""
    slots = 0
    for level in ANIMAL_UNLOCK_LEVELS:
        if farm_level >= level:
            slots += 1
    return slots

def get_user_farm_animals(user_id: int):
    """Получает всех животных, размещенных на ферме пользователя"""
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            SELECT slot_number, animal_item_id, last_fed_time, COALESCE(feed_buffer_hours, 0)
            FROM farm_animals 
            WHERE user_id = ?
            ORDER BY slot_number
        ''', (user_id,))
        rows = cur.fetchall()
        conn.close()
    
    animals = {}
    for row in rows:
        animal_item_id = row[1]
        animal_type = ANIMAL_ITEMS.get(animal_item_id, 'unknown')
        animals[row[0]] = {
            'item_id': animal_item_id,
            'type': animal_type,
            'last_fed_time': row[2],
            'feed_buffer_hours': int(row[3] or 0),
        }
    return animals

def place_animal_on_farm(user_id: int, animal_item_id: str):
    """Размещает животное на ферму в свободный слот.
    Сначала использует индивидуальных животных из owned_animals (с сохраненной памятью кормления),
    если их нет — конвертирует один предмет из инвентаря в новое животное (last_fed_time=0)."""
    # Проверяем, есть ли это животное
    if animal_item_id not in ANIMAL_ITEMS:
        return {'status': 'error', 'msg': 'Это не животное!'}
    
    # Попытаемся взять индивидуальное животное из owned_animals
    last_fed_time = pop_owned_animal(user_id, animal_item_id)
    if last_fed_time is None:
        # Проверяем наличие в инвентаре (легаси поддержка)
        inventory = db.get_inventory(user_id)
        has_animal = any((item_id == animal_item_id and count > 0) for item_id, count in inventory)
        if not has_animal:
            return {'status': 'error', 'msg': 'У вас нет этого животного!'}
        # Убираем из инвентаря, животное «новое»
        db.remove_item(user_id, animal_item_id, 1)
        last_fed_time = 0
    
    # Проверяем уровень фермы и доступные слоты
    farm = get_farm(user_id)
    max_slots = get_available_animal_slots(farm['level'])
    
    if max_slots == 0:
        return {'status': 'error', 'msg': 'У вас нет слотов для животных! Улучшите ферму до уровня 3.'}
    
    # Проверяем занятость слотов
    placed_animals = get_user_farm_animals(user_id)
    
    if len(placed_animals) >= max_slots:
        return {'status': 'error', 'msg': f'Все слоты заняты ({len(placed_animals)}/{max_slots})! Улучшите ферму для новых слотов.'}
    
    # Находим первый свободный слот
    free_slot = None
    for slot in range(1, max_slots + 1):
        if slot not in placed_animals:
            free_slot = slot
            break
    
    if free_slot is None:
        return {'status': 'error', 'msg': 'Нет свободных слотов!'}
    
    # Размещаем на ферму
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO farm_animals (user_id, slot_number, animal_item_id, last_fed_time)
            VALUES (?, ?, ?, ?)
        ''', (user_id, free_slot, animal_item_id, last_fed_time))
        conn.commit()
        conn.close()
    
    animal_type = ANIMAL_ITEMS[animal_item_id]
    animal_name = ANIMALS_CONFIG[animal_type]['name']
    
    return {
        'status': 'ok',
        'msg': f'✅ {animal_name} размещена на ферме в слот {free_slot}!\n\n💡 Не забудьте покормить её пшеницей или кукурузой, чтобы она начала приносить дань.'
    }

def remove_animal_from_farm(user_id: int, slot_number: int):
    """Убирает животное с фермы и возвращает его в owned_animals с сохранением памяти кормления."""
    animals = get_user_farm_animals(user_id)
    
    if slot_number not in animals:
        return {'status': 'error', 'msg': 'В этом слоте нет животного!'}
    
    animal_item_id = animals[slot_number]['item_id']
    animal_type = animals[slot_number]['type']
    animal_name = ANIMALS_CONFIG[animal_type]['name']
    last_fed_time = animals[slot_number]['last_fed_time']
    
    # Удаляем животное с фермы
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            DELETE FROM farm_animals 
            WHERE user_id = ? AND slot_number = ?
        ''', (user_id, slot_number))
        # Добавляем животное в owned_animals с актуальным last_fed_time
        cur.execute('INSERT INTO owned_animals (user_id, animal_item_id, last_fed_time) VALUES (?, ?, ?)', (user_id, animal_item_id, last_fed_time))
        conn.commit()
        conn.close()
    
    return {
        'status': 'ok',
        'msg': f'✅ {animal_name} убрана с фермы и сохранена в хранилище животных!'
    }

def feed_animal(user_id: int, slot_number: int, food_item_id: str):
    """Кормит животное, обновляет время последнего кормления"""
    animals = get_user_farm_animals(user_id)
    
    if slot_number not in animals:
        return {'status': 'error', 'msg': 'В этом слоте нет животного!'}
    
    animal = animals[slot_number]
    animal_type = animal['type']
    
    if animal_type not in ANIMALS_CONFIG:
        return {'status': 'error', 'msg': 'Неизвестный тип животного!'}
    
    config = ANIMALS_CONFIG[animal_type]
    
    # Проверяем, подходит ли еда
    if food_item_id not in config['food_items']:
        return {'status': 'error', 'msg': f'{config["name"]} не ест это!'}
    
    # Проверяем наличие еды в инвентаре
    inventory = db.get_inventory(user_id)
    food_count = 0
    
    for item_id, count in inventory:
        if item_id == food_item_id:
            food_count = count
            break
    
    if food_count < 1:
        return {'status': 'error', 'msg': 'У вас нет этой еды!'}
    
    # Убираем 1 единицу еды
    db.remove_item(user_id, food_item_id, 1)
    
    # Логика «кормление добавляет время», максимум +36 часов буфера
    now = int(time.time())
    current_last_fed = int(animal.get('last_fed_time', 0) or 0)
    current_buf = int(animal.get('feed_buffer_hours', 0) or 0)
    base_hours = int(config['max_hungry_hours'])
    max_extra = 36
    
    # Нельзя перекармливать свыше 36 часов буфера
    if current_buf >= max_extra:
        return {
            'status': 'error',
            'msg': f'❌ Нельзя кормить больше чем на {max_extra} часов запаса. Подождите, пока время немного уменьшится.'
        }
    
    # Если животное спит (вышло окно активности), сбрасываем базу и буфер
    total_allowed = base_hours + current_buf
    hours_since = (now - current_last_fed) / 3600 if current_last_fed else 9999
    if hours_since >= total_allowed:
        # «Проснулось с нуля»: ставим текущее кормление как новую базу
        new_last_fed = now
        new_buf = min(12, max_extra)
    else:
        # Активно: просто увеличиваем буфер
        new_last_fed = current_last_fed
        new_buf = min(current_buf + 12, max_extra)
    
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('''
            UPDATE farm_animals 
            SET last_fed_time = ?, feed_buffer_hours = ?
            WHERE user_id = ? AND slot_number = ?
        ''', (new_last_fed, new_buf, user_id, slot_number))
        conn.commit()
        conn.close()
    
    left_total = base_hours + new_buf
    return {
        'status': 'ok',
        'msg': f'✅ {config["name"]} накормлена! Запас активности: до {left_total} ч (буфер {new_buf} ч).'
    }

def is_animal_active(animal_data: dict):
    """Проверяет, активно ли животное (накормлено ли в последние 12 часов)"""
    if not animal_data or animal_data.get('last_fed_time', 0) == 0:
        return False
    
    now = int(time.time())
    hours_since_fed = (now - animal_data['last_fed_time']) / 3600
    
    animal_type = animal_data.get('type')
    if animal_type not in ANIMALS_CONFIG:
        return False
    
    base = ANIMALS_CONFIG[animal_type]['max_hungry_hours']
    buf = int(animal_data.get('feed_buffer_hours', 0) or 0)
    return hours_since_fed < (base + buf)

def calculate_animals_income(user_id: int):
    """Рассчитывает накопленный доход от всех активных животных"""
    animals = get_user_farm_animals(user_id)
    total_income = 0
    active_count = 0
    
    now = int(time.time())
    
    for slot_number, animal_data in animals.items():
        last_fed = animal_data.get('last_fed_time', 0)
        
        if last_fed == 0:
            continue  # Никогда не кормили
        
        animal_type = animal_data['type']
        if animal_type not in ANIMALS_CONFIG:
            continue
        
        config = ANIMALS_CONFIG[animal_type]
        hours_since_fed = (now - last_fed) / 3600
        
        allowed_hours = config['max_hungry_hours'] + int(animal_data.get('feed_buffer_hours', 0) or 0)
        if hours_since_fed < allowed_hours:
            hours_to_pay = min(hours_since_fed, allowed_hours)
            income = config['income_per_hour'] * hours_to_pay
            total_income += income
            active_count += 1
    
    return total_income, active_count

def give_random_animal_reward(user_id: int):
    """Даёт случайное животное: 25% корова, 75% курица"""
    import random
    
    # 25% шанс на корову, 75% на курицу
    if random.random() < 0.25:
        animal_item_id = '09'  # Корова
        animal_name = '🐄 Корова'
    else:
        animal_item_id = '08'  # Курица
        animal_name = '🐔 Курица'
    
    # Добавляем как индивидуальное животное в хранилище (не в инвентарь)
    with db._lock:
        conn = db._connect()
        cur = conn.cursor()
        cur.execute('INSERT INTO owned_animals (user_id, animal_item_id, last_fed_time) VALUES (?, ?, 0)', (user_id, animal_item_id))
        conn.commit()
        conn.close()
    
    return {'item_id': animal_item_id, 'name': animal_name}

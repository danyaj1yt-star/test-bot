# tasks.py - Система ежедневных заданий
import random
import sqlite3
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import database as db

# Список всех возможных заданий
TASK_LIST = [
    {
        "id": 1,
        "name": "Собрать дань с фермы",
        "description": "Соберите дань с вашей фермы 15 раз",
        "reward_dan": 1500,
        "emoji": "🌾"
    },
    {
        "id": 2,
        "name": "Победитель арены",
        "description": "Выиграйте 5 боев на арене",
        "reward_dan": 1200,
        "emoji": "⚔️"
    },
    {
        "id": 3,
        "name": "Азартный игрок",
        "description": "Сыграйте 10 раз в любую игру",
        "reward_dan": 600,
        "emoji": "🎲"
    },
    {
        "id": 4,
        "name": "Коллекционер",
        "description": "Откройте 3 сундука любого уровня",
        "reward_dan": 1000,
        "emoji": "🎁"
    },
    {
        "id": 5,
        "name": "Торговец",
        "description": "Совершите 5 покупок в магазине",
        "reward_dan": 1000,
        "emoji": "🛒"
    },
    {
        "id": 6,
        "name": "Охотник за удачей",
        "description": "Выиграйте в лотерею или получите джекпот",
        "reward_dan": 3000,
        "emoji": "🍀"
    },
    {
        "id": 7,
        "name": "Щедрый друг",
        "description": "Отправьте дань другому игроку",
        "reward_dan": 500,
        "emoji": "🤝"
    },
    {
        "id": 9,
        "name": "Баттл-мастер",
        "description": "Сыграйте в баттлы между игроками 20 раз (бет, крестик, кости и т.д.)",
        "reward_dan": 1500,
        "emoji": "🎮"
    },
    {
        "id": 10,
        "name": "Чемпион арены",
        "description": "Выиграйте 5 раза на арене против реального человека",
        "reward_dan": 2000,
        "emoji": "🏆"
    },
    {
        "id": 11,
        "name": "Пригласи друзей",
        "description": "Пригласите 5 человек по реферальной ссылке",
        "reward_dan": 3000,
        "emoji": "👥"
    },
    {
        "id": 12,
        "name": "Хайроллер Бет - Максимум",
        "description": "Сыграйте в бет на сумму от 100 дань, 100 раз",
        "reward_dan": 5000,
        "emoji": "💎"
    },
    {
        "id": 13,
        "name": "Хайроллер Бет - Средний",
        "description": "Сыграйте в бет на сумму от 100 дань, 25 раз",
        "reward_dan": 2500,
        "emoji": "💰"
    },
    {
        "id": 14,
        "name": "Хайроллер Бет - Начальный",
        "description": "Сыграйте в бет на сумму от 1000 дань, 6 раз",
        "reward_dan": 2500,
        "emoji": "🪙"
    },
    {
        "id": 15,
        "name": "Кладоискатель - Средний",
        "description": "Сыграйте в Клад на сумму от 100 дань, 30 раз",
        "reward_dan": 2500,
        "emoji": "🗺️"
    },
    {
        "id": 16,
        "name": "Кладоискатель - Начальный",
        "description": "Сыграйте в Клад на сумму от 100 дань, 25 раз",
        "reward_dan": 1500,
        "emoji": "🧭"
    },
    {
        "id": 17,
        "name": "Кладоискатель - Профи",
        "description": "Сыграйте в Клад на сумму от 1000 дань, 10 раз",
        "reward_dan": 5000,
        "emoji": "💰"
    }
]

# Подключение к БД для хранения заданий
def get_db_connection():
    """Создает подключение к БД заданий"""
    conn = sqlite3.connect('database/tasks.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_tasks_db():
    """Инициализация таблицы заданий"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица для хранения активных заданий (обновляется ежедневно)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_tasks (
            date TEXT PRIMARY KEY,
            task_ids TEXT NOT NULL
        )
    ''')
    
    # Таблица для отслеживания прогресса игроков
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_task_progress (
            user_id INTEGER,
            date TEXT,
            task_id INTEGER,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date, task_id)
        )
    ''')
    # Сырые счетчики для задач с количественной целью (не процент)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_task_counters (
            user_id INTEGER,
            date TEXT,
            task_id INTEGER,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date, task_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_today_date() -> str:
    """Возвращает сегодняшнюю дату в формате YYYY-MM-DD"""
    return datetime.now().strftime('%Y-%m-%d')

def get_current_week_id() -> str:
    """Возвращает ID текущей недели в формате YYYY-WXX
    Неделя начинается в воскресенье в 23:00 по Киеву (UTC+2/UTC+3)
    """
    import pytz
    
    # Киевская временная зона
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.now(kyiv_tz)
    
    # Если сейчас воскресенье после 23:00 или позже - это уже следующая неделя
    if now_kyiv.weekday() == 6 and now_kyiv.hour >= 23:  # 6 = воскресенье
        # Переходим на следующий день для расчета недели
        next_day = now_kyiv + timedelta(days=1)
        year, week, _ = next_day.isocalendar()
    else:
        year, week, _ = now_kyiv.isocalendar()
    
    return f"{year}-W{week:02d}"

def get_daily_tasks() -> List[dict]:
    """Получает или генерирует 5 заданий на текущую неделю (одинаковые для всех)
    Задания обновляются каждую неделю в воскресенье в 23:00 по Киеву"""
    week_id = get_current_week_id()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем, есть ли задания на эту неделю
    cursor.execute('SELECT task_ids FROM daily_tasks WHERE date = ?', (week_id,))
    result = cursor.fetchone()
    
    if result:
        # Задания уже сгенерированы для этой недели
        task_ids = [int(x) for x in result['task_ids'].split(',')]
    else:
        # Генерируем новые 5 случайных заданий без повторов по description
        unique_tasks = []
        used_descriptions = set()
        for task in random.sample(TASK_LIST, len(TASK_LIST)):
            desc = task.get('description', '').strip().lower()
            if desc and desc not in used_descriptions:
                unique_tasks.append(task)
                used_descriptions.add(desc)
            if len(unique_tasks) == 5:
                break
        task_ids = [task['id'] for task in unique_tasks]
        # Сохраняем в БД с ID недели
        cursor.execute(
            'INSERT INTO daily_tasks (date, task_ids) VALUES (?, ?)',
            (week_id, ','.join(map(str, task_ids)))
        )
        conn.commit()
    
    conn.close()
    
    # Возвращаем полные данные заданий
    return [task for task in TASK_LIST if task['id'] in task_ids]

def get_user_tasks(user_id: int) -> List[dict]:
    """Получает задания пользователя с прогрессом"""
    week_id = get_current_week_id()
    daily_tasks = get_daily_tasks()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    tasks_with_progress = []
    for task in daily_tasks:
        cursor.execute('''
            SELECT progress, completed, claimed
            FROM user_task_progress
            WHERE user_id = ? AND date = ? AND task_id = ?
        ''', (user_id, week_id, task['id']))
        
        result = cursor.fetchone()
        if result:
            task_copy = task.copy()
            task_copy['progress'] = result['progress']
            task_copy['completed'] = bool(result['completed'])
            task_copy['claimed'] = bool(result['claimed'])
        else:
            # Инициализируем прогресс для пользователя
            cursor.execute('''
                INSERT INTO user_task_progress (user_id, date, task_id, progress, completed, claimed)
                VALUES (?, ?, ?, 0, 0, 0)
            ''', (user_id, week_id, task['id']))
            conn.commit()
            
            task_copy = task.copy()
            task_copy['progress'] = 0
            task_copy['completed'] = False
            task_copy['claimed'] = False
        
        tasks_with_progress.append(task_copy)
    
    conn.close()
    return tasks_with_progress

def _progress_bar(percent: int, width: int = 5) -> str:
    """Возвращает строчку прогресс-бара из █ и ░ фиксированной ширины.
    Правило заполнения: ceil(percent/step), но для 0% = 0 заполнения.
    """
    try:
        p = max(0, min(100, int(percent)))
    except Exception:
        p = 0
    step = 100 // width  # 20 при width=5
    filled = 0 if p == 0 else min(width, (p + step - 1) // step)  # ceil, но 0 остаётся 0
    empty = max(0, width - filled)
    return "█" * filled + "░" * empty


def format_tasks_text(user_id: int) -> str:
    """Форматирует список заданий в минималистичном стиле с кратким описанием.
    Формат:
      📋 Недельные задания — Неделя XX
      N. {emoji} Описание
          📊 count/goal • +reward Дань
    """
    tasks = get_user_tasks(user_id)
    week_id = get_current_week_id()
    # Получаем диапазон дат недели
    import pytz
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.now(kyiv_tz)
    # Определяем начало недели (понедельник)
    start_of_week = now_kyiv - timedelta(days=now_kyiv.weekday())
    # Определяем конец недели (воскресенье)
    end_of_week = start_of_week + timedelta(days=6)
    # Форматируем даты как ДД.ММ
    start_str = start_of_week.strftime('%d.%m')
    end_str = end_of_week.strftime('%d.%m')
    lines = [f"<b>📋 Недельные задания — {start_str} - {end_str}</b>"]

    for i, task in enumerate(tasks, 1):
        reward = f"{task['reward_dan']:,}"
        emoji = task.get('emoji', '•')
        # Краткое описание из description
        desc = task.get('description', task.get('name', ''))

        # Состояния завершения/получения
        if task.get('claimed'):
            lines.append(f"{i}. {emoji} {desc}")
            lines.append(f"    <b>✅ Награда получена • +{reward} Дань</b>")
            continue
        if task.get('completed'):
            lines.append(f"{i}. {emoji} {desc}")
            lines.append(f"    <b>🎁 Доступна награда • +{reward} Дань</b>")
            continue

        # Активный прогресс
        # Пытаемся показать счётчик x/N, если для задачи есть цель
        task_id = int(task.get('id', 0))
        count_str = None
        goal = TASK_GOALS.get(task_id)
        if goal:
            try:
                current = _get_counter(user_id, task_id)
                count_str = f"{current}/{goal}"
            except Exception:
                count_str = None

        lines.append(f"{i}. {emoji} {desc}")
        if count_str:
            lines.append(f"    <b>📊 {count_str} • +{reward} Дань</b>")
        else:
            lines.append(f"    <b>📊 • +{reward} Дань</b>")

    return "\n".join(lines)

def update_task_progress(user_id: int, task_id: int, progress: int):
    """Обновляет прогресс задания (0-100%)"""
    week_id = get_current_week_id()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    completed = 1 if progress >= 100 else 0
    
    cursor.execute('''
        UPDATE user_task_progress
        SET progress = ?, completed = ?
        WHERE user_id = ? AND date = ? AND task_id = ?
    ''', (min(progress, 100), completed, user_id, week_id, task_id))
    
    conn.commit()
    conn.close()

def claim_task_reward(user_id: int, task_id: int) -> Optional[int]:
    """Получить награду за выполненное задание. Возвращает сумму награды или None"""
    week_id = get_current_week_id()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем статус задания
    cursor.execute('''
        SELECT completed, claimed FROM user_task_progress
        WHERE user_id = ? AND date = ? AND task_id = ?
    ''', (user_id, week_id, task_id))
    
    result = cursor.fetchone()
    if not result or not result['completed'] or result['claimed']:
        conn.close()
        return None
    
    # Отмечаем награду как полученную
    cursor.execute('''
        UPDATE user_task_progress
        SET claimed = 1
        WHERE user_id = ? AND date = ? AND task_id = ?
    ''', (user_id, week_id, task_id))
    
    conn.commit()
    conn.close()
    
    # Находим задание и выдаем награду
    task = next((t for t in TASK_LIST if t['id'] == task_id), None)
    if task:
        db.add_dan(user_id, task['reward_dan'])
        return task['reward_dan']
    
    return None

# Инициализация БД при импорте модуля
init_tasks_db()

# === ХЕЛПЕРЫ ДЛЯ РЕГИСТРАЦИИ СОБЫТИЙ И ПРОГРЕССА ===

# Карта целевых значений для количественных задач
TASK_GOALS = {
    1: 15,   # Соберите дань с фермы 15 раз
    2: 5,    # Победитель арены — 5 боев
    3: 10,   # Азартный игрок — 10 игр
    4: 3,    # Коллекционер — 3 сундука
    5: 5,    # Торговец — 5 покупок
    7: 1,    # Щедрый друг — 1 раз
    8: 3,    # Выполнить любые 3 команды (оставлено как было)
    9: 20,   # Баттл-мастер — 20 баттлов
    10: 5,   # Чемпион арены — 5 побед против реального человека
    11: 5,   # Пригласи друзей — 5 рефералов
    12: 100, # Хайроллер Бет - Максимум — 100 раз
    13: 25,  # Хайроллер Бет - Средний — 25 раз
    14: 6,   # Хайроллер Бет - Начальный — 6 раз
    15: 30,  # Кладоискатель - Средний — 30 раз
    16: 25,  # Кладоискатель - Начальный — 25 раз
    17: 10,  # Кладоискатель - Профи — 10 раз
}

def _is_task_active(task_id: int) -> bool:
    """Проверяет, входит ли task_id в сегодняшние 5 заданий."""
    try:
        today_ids = {t['id'] for t in get_daily_tasks()}
        return task_id in today_ids
    except Exception:
        return False

def _get_counter(user_id: int, task_id: int) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    week_id = get_current_week_id()
    cur.execute('SELECT count FROM user_task_counters WHERE user_id=? AND date=? AND task_id=?', (user_id, week_id, task_id))
    row = cur.fetchone()
    conn.close()
    return int(row['count']) if row else 0

def _set_counter_and_progress(user_id: int, task_id: int, new_count: int, goal: int):
    """Обновляет сырое значение count и синхронизирует проценты/complete в основной таблице."""
    week_id = get_current_week_id()
    conn = get_db_connection()
    cur = conn.cursor()
    # ensure rows exist in both tables
    cur.execute('INSERT OR IGNORE INTO user_task_counters (user_id, date, task_id, count) VALUES (?, ?, ?, 0)', (user_id, week_id, task_id))
    cur.execute('INSERT OR IGNORE INTO user_task_progress (user_id, date, task_id, progress, completed, claimed) VALUES (?, ?, ?, 0, 0, 0)', (user_id, week_id, task_id))
    # update counter
    cur.execute('UPDATE user_task_counters SET count=? WHERE user_id=? AND date=? AND task_id=?', (new_count, user_id, week_id, task_id))
    # compute percent and completed
    percent = 100 if new_count >= goal else int(new_count * 100 / max(1, goal))
    completed = 1 if new_count >= goal else 0
    cur.execute('UPDATE user_task_progress SET progress=?, completed=? WHERE user_id=? AND date=? AND task_id=?', (percent, completed, user_id, week_id, task_id))
    conn.commit()
    conn.close()

def _add_units(user_id: int, task_id: int, units: int = 1):
    """Добавляет единицы прогресса для количественной задачи (если она активна сегодня)."""
    if not _is_task_active(task_id):
        return
    goal = TASK_GOALS.get(task_id)
    if not goal:
        return
    current = _get_counter(user_id, task_id)
    new_count = min(goal, current + max(1, units))
    _set_counter_and_progress(user_id, task_id, new_count, goal)

# Публичные API для регистрации событий из модулей игр

def record_battle_play(user_id: int):
    """Любая PvP-активность (бет, крестики-нолики, кости и т.п.)."""
    _add_units(user_id, 9, 1)
    # Также считаем как "сыграл любую игру" если активна
    _add_units(user_id, 3, 1)

def record_arena_win(user_id: int, vs_real: bool = True):
    """Победа на арене. Если vs_real=False — игнорируем задачу 10."""
    if vs_real:
        _add_units(user_id, 10, 1)
    # Любая победа — это тоже факт игры
    _add_units(user_id, 3, 1)

def record_bet_play(user_id: int, stake: int):
    """Сыгран бет на сумму stake. Считаем задачи 12/13/14 (все с порогом 100)."""
    try:
        stake_val = int(stake)
    except Exception:
        return
    if stake_val >= 100:
        _add_units(user_id, 12, 1)
        _add_units(user_id, 13, 1)
        _add_units(user_id, 14, 1)
        _add_units(user_id, 3, 1)

def record_clad_play(user_id: int, bet: int):
    """Сыгран Клад на сумму bet. Считаем задачи 15/16 (>=100) и 17 (>=1000)."""
    try:
        bet_val = int(bet)
    except Exception:
        return
    if bet_val >= 100:
        _add_units(user_id, 15, 1)
        _add_units(user_id, 16, 1)
        _add_units(user_id, 3, 1)
    if bet_val >= 1000:
        _add_units(user_id, 17, 1)

def record_referral(user_id: int):
    """Регистрирует успешное приглашение реферала."""
    _add_units(user_id, 11, 1)

def record_shop_purchase(user_id: int):
    """Регистрирует покупку в магазине (за дань или за звезды)."""
    _add_units(user_id, 5, 1)

def record_case_open(user_id: int):
    """Регистрирует открытие сундука/кейса любого уровня."""
    _add_units(user_id, 4, 1)

def record_farm_collect(user_id: int):
    """Регистрирует сбор дани с фермы."""
    _add_units(user_id, 1, 1)

def record_dan_transfer(user_id: int):
    """Регистрирует отправку дани другому игроку."""
    _add_units(user_id, 7, 1)

def record_command_use(user_id: int):
    """Регистрирует использование команды бота."""
    _add_units(user_id, 8, 1)

def record_any_game(user_id: int):
    """Регистрирует факт игры в любую игру (без PvP-счётчиков)."""
    _add_units(user_id, 3, 1)

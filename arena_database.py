"""
База данных для арены - отдельная система для PvP
"""
import sqlite3
import os
from typing import Dict, List, Optional
import time

# Путь к базе данных арены
ARENA_DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'arena.db')

def get_arena_connection():
    """Получить соединение с базой данных арены"""
    # Создаем папку если не существует
    os.makedirs(os.path.dirname(ARENA_DB_PATH), exist_ok=True)
    return sqlite3.connect(ARENA_DB_PATH)

def init_arena_database():
    """Инициализация базы данных арены"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    # Таблица рейтингов игроков
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arena_ratings (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            rating INTEGER DEFAULT 200,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            win_streak INTEGER DEFAULT 0,
            best_win_streak INTEGER DEFAULT 0,
            total_damage_dealt INTEGER DEFAULT 0,
            total_damage_taken INTEGER DEFAULT 0,
            total_healing INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            last_game_time INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица истории боев
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arena_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER NOT NULL,
            player1_username TEXT NOT NULL,
            player2_id INTEGER NOT NULL,
            player2_username TEXT NOT NULL,
            winner_id INTEGER NOT NULL,
            player1_rating_before INTEGER NOT NULL,
            player2_rating_before INTEGER NOT NULL,
            player1_rating_after INTEGER NOT NULL,
            player2_rating_after INTEGER NOT NULL,
            rounds_count INTEGER NOT NULL,
            battle_duration INTEGER NOT NULL,
            battle_time INTEGER NOT NULL,
            battle_data TEXT
        )
    ''')
    
    # Таблица достижений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arena_achievements (
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            earned_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, achievement_id)
        )
    ''')
    
    # Таблица сезонных статистик
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arena_seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_name TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arena_season_stats (
            user_id INTEGER NOT NULL,
            season_id INTEGER NOT NULL,
            rating INTEGER DEFAULT 200,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            best_rating INTEGER DEFAULT 200,
            PRIMARY KEY (user_id, season_id),
            FOREIGN KEY (season_id) REFERENCES arena_seasons(id)
        )
    ''')
    
    conn.commit()
    
    # Миграции: добавляем недостающие колонки для опыта/уровней
    try:
        cursor.execute("PRAGMA table_info(arena_ratings)")
        cols = {row[1] for row in cursor.fetchall()}
        # Опыт и уровень игрока в арене
        if 'xp' not in cols:
            cursor.execute("ALTER TABLE arena_ratings ADD COLUMN xp INTEGER DEFAULT 0")
        if 'level' not in cols:
            cursor.execute("ALTER TABLE arena_ratings ADD COLUMN level INTEGER DEFAULT 1")
        # Дата последнего ежедневного большого бонуса за победу
        if 'last_bonus_win_date' not in cols:
            cursor.execute("ALTER TABLE arena_ratings ADD COLUMN last_bonus_win_date TEXT")
        # Количество ожидающих наград за повышение уровня
        if 'pending_level_rewards' not in cols:
            cursor.execute("ALTER TABLE arena_ratings ADD COLUMN pending_level_rewards INTEGER DEFAULT 0")
        conn.commit()
    except Exception as mig_e:
        print(f"⚠️ Миграция таблицы arena_ratings: {mig_e}")
    conn.close()
    print("✅ База данных арены инициализирована")

def get_player_rating(user_id: int, username: Optional[str] = None) -> Dict:
    """Получить рейтинг игрока"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM arena_ratings WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        # Создаем новую запись
        current_time = int(time.time())
        cursor.execute('''
            INSERT INTO arena_ratings 
            (user_id, username, rating, wins, losses, win_streak, best_win_streak,
             total_damage_dealt, total_damage_taken, total_healing, games_played,
             last_game_time, created_at, xp, level, last_bonus_win_date, pending_level_rewards) 
            VALUES (?, ?, 200, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, 0, 1, NULL, 0)
        ''', (user_id, username or f"Player_{user_id}", current_time))
        conn.commit()
        
        rating_data = {
            'user_id': user_id,
            'username': username or f"Player_{user_id}",
            'rating': 200,
            'wins': 0,
            'losses': 0,
            'win_streak': 0,
            'best_win_streak': 0,
            'total_damage_dealt': 0,
            'total_damage_taken': 0,
            'total_healing': 0,
            'games_played': 0,
            'last_game_time': 0,
            'created_at': current_time,
            'xp': 0,
            'level': 1,
            'last_bonus_win_date': None,
            'pending_level_rewards': 0
        }
    else:
        # Старые БД могут не иметь новых столбцов; безопасно извлекаем по индексу с проверкой длины
        row = list(result)
        # Ожидаем минимум 13 колонок как в старой схеме
        xp = 0
        level = 1
        last_bonus_win_date = None
        pending_level_rewards = 0
        if len(row) > 13:
            xp = row[13] if row[13] is not None else 0
        if len(row) > 14:
            level = row[14] if row[14] is not None else 1
        if len(row) > 15:
            last_bonus_win_date = row[15]
        if len(row) > 16:
            pending_level_rewards = row[16] if row[16] is not None else 0
        rating_data = {
            'user_id': row[0],
            'username': row[1],
            'rating': row[2],
            'wins': row[3],
            'losses': row[4],
            'win_streak': row[5],
            'best_win_streak': row[6],
            'total_damage_dealt': row[7],
            'total_damage_taken': row[8],
            'total_healing': row[9],
            'games_played': row[10],
            'last_game_time': row[11],
            'created_at': row[12],
            'xp': xp,
            'level': level,
            'last_bonus_win_date': last_bonus_win_date,
            'pending_level_rewards': pending_level_rewards
        }
    
    conn.close()
    return rating_data

def get_player_rank(user_id: int) -> int:
    """Получить ранг игрока в общей таблице"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    # Получаем ранг игрока по рейтингу
    cursor.execute('''
        SELECT COUNT(*) + 1 as rank 
        FROM arena_ratings 
        WHERE rating > (SELECT rating FROM arena_ratings WHERE user_id = ? LIMIT 1)
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else 1

def update_player_rating(user_id: int, username: str, rating_change: int, is_win: bool, 
                        damage_dealt: int = 0, damage_taken: int = 0, healing: int = 0):
    """Обновить рейтинг игрока"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    # Получаем текущие данные
    current_data = get_player_rating(user_id, username)
    
    # Вычисляем новые значения
    new_rating = max(0, current_data['rating'] + rating_change)
    new_wins = current_data['wins'] + (1 if is_win else 0)
    new_losses = current_data['losses'] + (0 if is_win else 1)
    new_win_streak = (current_data['win_streak'] + 1) if is_win else 0
    new_best_streak = max(current_data['best_win_streak'], new_win_streak)
    new_games = current_data['games_played'] + 1
    
    # Обновляем запись
    cursor.execute('''
        UPDATE arena_ratings 
        SET username = ?, rating = ?, wins = ?, losses = ?, win_streak = ?, 
            best_win_streak = ?, total_damage_dealt = ?, total_damage_taken = ?, 
            total_healing = ?, games_played = ?, last_game_time = ?
        WHERE user_id = ?
    ''', (
        username, new_rating, new_wins, new_losses, new_win_streak, new_best_streak,
        current_data['total_damage_dealt'] + damage_dealt,
        current_data['total_damage_taken'] + damage_taken,
        current_data['total_healing'] + healing,
        new_games, int(time.time()), user_id
    ))
    
    conn.commit()
    conn.close()
    
    return new_rating

def register_win_xp(user_id: int) -> Dict:
    """Начислить опыт за победу с учетом ежедневного большого бонуса.
    Возвращает словарь: { 'xp_gain': int, 'xp': int, 'level': int, 'leveled_up': bool, 'pending_level_rewards': int }
    """
    import datetime
    conn = get_arena_connection()
    cursor = conn.cursor()
    # Убедимся, что запись существует
    current = get_player_rating(user_id)
    today = datetime.date.today().isoformat()
    # Определяем награду: первая победа за день 100-400, иначе 20-100
    import random as _rnd
    if current.get('last_bonus_win_date') != today:
        xp_gain = _rnd.randint(100, 400)
        last_bonus_win_date = today
    else:
        xp_gain = _rnd.randint(20, 100)
        last_bonus_win_date = current.get('last_bonus_win_date')
    xp = int(current.get('xp', 0)) + xp_gain
    level = int(current.get('level', 1))
    leveled_up = False
    pending = int(current.get('pending_level_rewards', 0))
    XP_PER_LEVEL = 5000
    while xp >= XP_PER_LEVEL:
        xp -= XP_PER_LEVEL
        level += 1
        pending += 1
        leveled_up = True
    cursor.execute('''
        UPDATE arena_ratings
        SET xp = ?, level = ?, last_bonus_win_date = ?, pending_level_rewards = ?
        WHERE user_id = ?
    ''', (xp, level, last_bonus_win_date, pending, user_id))
    conn.commit()
    conn.close()
    return {
        'xp_gain': xp_gain,
        'xp': xp,
        'level': level,
        'leveled_up': leveled_up,
        'pending_level_rewards': pending
    }

def claim_level_reward(user_id: int) -> bool:
    """
    Уменьшает счетчик наград на 1 при получении награды.
    Возвращает True если успешно, False если наград не было.
    """
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    # Получаем текущее количество наград
    cursor.execute('SELECT pending_level_rewards FROM arena_ratings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row or row[0] <= 0:
        conn.close()
        return False
    
    # Уменьшаем на 1
    new_pending = row[0] - 1
    cursor.execute('UPDATE arena_ratings SET pending_level_rewards = ? WHERE user_id = ?', 
                   (new_pending, user_id))
    conn.commit()
    conn.close()
    return True

def save_battle_result(player1_data: Dict, player2_data: Dict, winner_id: int, 
                      rounds_count: int, duration: int, battle_data: str = ""):
    """Сохранить результат боя"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO arena_battles 
        (player1_id, player1_username, player2_id, player2_username, winner_id,
         player1_rating_before, player2_rating_before, player1_rating_after, player2_rating_after,
         rounds_count, battle_duration, battle_time, battle_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        player1_data['user_id'], player1_data['username'],
        player2_data['user_id'], player2_data['username'],
        winner_id,
        player1_data['rating_before'], player2_data['rating_before'],
        player1_data['rating_after'], player2_data['rating_after'],
        rounds_count, duration, int(time.time()), battle_data
    ))
    
    conn.commit()
    conn.close()

def get_top_players(limit: int = 10) -> List[Dict]:
    """Получить топ игроков по рейтингу"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, rating, wins, losses, win_streak, games_played
        FROM arena_ratings 
        WHERE games_played > 0
        ORDER BY rating DESC, wins DESC 
        LIMIT ?
    ''', (limit,))
    
    results = cursor.fetchall()
    conn.close()
    
    players = []
    for i, result in enumerate(results):
        players.append({
            'rank': i + 1,
            'user_id': result[0],
            'username': result[1],
            'rating': result[2],
            'wins': result[3],
            'losses': result[4],
            'win_streak': result[5],
            'games_played': result[6],
            'winrate': round((result[3] / result[6]) * 100, 1) if result[6] > 0 else 0
        })
    
    return players

def get_player_battles_history(user_id: int, limit: int = 10) -> List[Dict]:
    """Получить историю боев игрока"""
    conn = get_arena_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM arena_battles 
        WHERE player1_id = ? OR player2_id = ?
        ORDER BY battle_time DESC 
        LIMIT ?
    ''', (user_id, user_id, limit))
    
    results = cursor.fetchall()
    conn.close()
    
    battles = []
    for result in results:
        battles.append({
            'id': result[0],
            'player1_id': result[1],
            'player1_username': result[2],
            'player2_id': result[3],
            'player2_username': result[4],
            'winner_id': result[5],
            'rounds_count': result[10],
            'duration': result[11],
            'battle_time': result[12],
            'was_winner': result[5] == user_id
        })
    
    return battles

if __name__ == "__main__":
    # Тест инициализации
    init_arena_database()
    
    # Тест создания игрока
    test_user = 12345
    rating = get_player_rating(test_user, "TestPlayer")
    print(f"Создан игрок: {rating}")
    
    rank = get_player_rank(test_user)
    print(f"Ранг игрока: #{rank}")
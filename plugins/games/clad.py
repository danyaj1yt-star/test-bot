import random
import time
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Структура для хранения активных игр (теперь по game_id, а не user_id)
active_clads = {}

# Мультипликаторы (ограничено до 6 реальных этапов, финальный редкий финал x25)
# Экономически таргетируем средний ранний выход на 2-3 уровне.
MULTS = [1.25, 1.65, 2.00, 3.60, 6.50, 25.0]

# Подкрутка шансов: вероятность ПРОИГРЫША по уровням (меньше — больше шансов пройти)
# Было жестко: [0.20, 0.50, 0.70, 0.90, 0.97, 0.995]
# Сделаем добрее, особенно на ранних уровнях
LOSE_CHANCES = [0.2, 0.4, 0.7, 0.8, 0.95, 0.975]
MAX_LOSE_CHANCES = [0.5, 0.7, 0.85, 0.92, 0.95, 0.99]

def generate_unique_game_id(user_id):
    """Генерирует уникальный ID игры с наносекундной точностью"""
    return f"clad_{user_id}_{time.time_ns()}"


MINES_PER_ROW = [1, 2, 3, 4, 4, 4]  # запрошенное распределение мин
CELLS_PER_ROW = 5

def generate_row(mines: int, level: int = 0):
    """Генерирует один ряд по количеству мин с подкруткой для первых уровней."""
    row = [0] * CELLS_PER_ROW
    mines = min(mines, CELLS_PER_ROW)
    mine_idxs = random.sample(range(CELLS_PER_ROW), mines)
    for idx in mine_idxs:
        row[idx] = 1
    return row

def generate_display_row(mines: int, clicked_cell: int, is_mine_hit: bool):
    """Генерирует ряд для отображения после игры"""
    row = [0] * CELLS_PER_ROW
    if is_mine_hit:
        # Ставим мину в кликнутую ячейку
        row[clicked_cell] = 1
        mines -= 1
    
    # Размещаем остальные мины случайно
    if mines > 0:
        available_cells = [i for i in range(CELLS_PER_ROW) if i != clicked_cell]
        mines = min(mines, len(available_cells))
        mine_idxs = random.sample(available_cells, mines)
        for idx in mine_idxs:
            row[idx] = 1
    
    return row

# Генерация клавиатуры для текущего уровня


# Генерация клавиатуры: показывать все открытые ряды, открытые клетки — 💵/💣, остальные — 'копай'
def get_keyboard(game, reveal_all=False):
    """Строим клавиатуру с учётом ленивой генерации рядов.
    Сгенерированные пройденные ряды показываем полностью (💣/💵).
    Текущий ряд если сгенерирован и игра жива — кнопки 🤞.
    Будущие не сгенерированные ряды – пустые ячейки.
    """
    kb = []
    total_levels = len(MINES_PER_ROW)
    for lvl in range(total_levels):
        row_data = game['rows'][lvl]
        kb_row = []
        for idx in range(CELLS_PER_ROW):
            if lvl < game['level']:
                # Пройденные: показываем содержимое
                if row_data:
                    btn = InlineKeyboardButton(text=('💣' if row_data[idx] == 1 else '💵'), callback_data='none')
                else:
                    btn = InlineKeyboardButton(text='?', callback_data='none')
            elif lvl == game['level'] and game['alive']:
                # Текущий активный уровень: интерактивные клетки
                btn = InlineKeyboardButton(text='🤞', callback_data=f"clad:{game['game_id']}:{idx}")
            else:
                btn = InlineKeyboardButton(text=' ', callback_data='none')
            kb_row.append(btn)
        mult = MULTS[lvl] if lvl < len(MULTS) else MULTS[-1]
        mult_text = f"x{mult}" if not isinstance(mult, str) else mult
        kb_row.append(InlineKeyboardButton(text=mult_text, callback_data='none'))
        kb.append(kb_row)
    if game['alive'] and not reveal_all and game['level'] > 0:
        last_level = max(0, game['level'] - 1)
        mult = MULTS[last_level] if last_level < len(MULTS) else MULTS[-1]
        mult_text = f"{mult}x" if not isinstance(mult, str) else mult
        kb.append([InlineKeyboardButton(text=f"Забрать ({mult_text})", callback_data=f"clad:{game['game_id']}:take")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# Начать игру


def start_clad_game(user_id, bet):
    game_id = generate_unique_game_id(user_id)
    # rows: список из len(MINES_PER_ROW) элементов; None пока не сгенерированы.
    rows = [None for _ in MINES_PER_ROW]
    game = {
        'game_id': game_id,
        'user_id': user_id,
        'bet': bet,
        'rows': rows,
        'level': 0,
        'alive': True
    }
    active_clads[game_id] = game
    return game

# Проверка шага


async def step_clad_game(game_id, cell_idx):
    game = active_clads.get(game_id)
    if not game or not game['alive']:
        return {'status': 'end', 'msg': 'Игра завершена.'}
    
    current_level = game['level']
    if current_level >= len(MINES_PER_ROW):
        return {'status': 'end', 'msg': 'Игра завершена.'}
    
    # Добавляем задержку 0.3 секунды для создания напряжения
    import asyncio
    await asyncio.sleep(0.3)
    
    # Плавная интерполяция шанса проигрыша по размеру ставки
    bet = game.get('bet', 0)
    min_bet = 10
    max_bet = 300_000
    factor = min(max((bet - min_bet) / (max_bet - min_bet), 0), 1)
    # Для каждого уровня вычисляем шанс
    if current_level < len(LOSE_CHANCES):
        base = LOSE_CHANCES[current_level]
        maxc = MAX_LOSE_CHANCES[current_level]
        chance = base + factor * (maxc - base)
        hit_mine = random.random() < chance
    else:
        # Если уровней больше, используем последний шанс
        base = LOSE_CHANCES[-1]
        maxc = MAX_LOSE_CHANCES[-1]
        chance = base + factor * (maxc - base)
        hit_mine = random.random() < chance

    # Выводим шанс игроку (только для текущего уровня)
    percent = int(chance * 100)
    try:
        from aiogram import types
        user_id = game.get('user_id')
        msg_text = f"Шанс проигрыша на этом уровне: {percent}% (ставка: {bet})"
        # Если есть message_id, можно отредактировать, иначе отправить новое
        # Здесь предполагается, что у вас есть chat_id, например user_id
        # Можно добавить логику для отправки сообщения игроку
        # await bot.send_message(user_id, msg_text)
        pass
    except Exception:
        pass
    
    if hit_mine:
        game['alive'] = False
        # Генерируем ряд для отображения для любого уровня
        game['rows'][current_level] = generate_display_row(MINES_PER_ROW[current_level], cell_idx, True)
        game['clicked_cell'] = cell_idx  # Сохраняем кликнутую ячейку
        try:
            import database as db
            db.increment_dan_lose(game['user_id'], game['bet'])
        except Exception:
            pass
        return {'status': 'lose', 'msg': f'Вы попали на мину! Проигрыш. Потеряно {game["bet"]:.2f}.'}
    else:
        # Генерируем ряд для отображения при успешном прохождении для любого уровня
        game['rows'][current_level] = generate_display_row(MINES_PER_ROW[current_level], cell_idx, False)
        
        game['level'] += 1
        if game['level'] >= len(MINES_PER_ROW):
            game['alive'] = False
            try:
                import database as db
                db.increment_dan_win(game['user_id'], max(game['bet'] * MULTS[-1] - game['bet'], 0))
                db.increment_dan_lose(game['user_id'], game['bet'])
            except Exception:
                pass
            return {'status': 'win', 'msg': f'Поздравляем! Вы прошли все уровни и выиграли {game["bet"] * MULTS[-1]:.2f}.'}
        return {'status': 'next', 'msg': f'Успешно! Следующий уровень: {game["level"]+1}'}

# Забрать выигрыш


async def take_clad_game(game_id):
    game = active_clads.get(game_id)
    if not game or not game['alive']:
        return {'status': 'end', 'msg': 'Игра завершена.'}
    
    # Добавляем задержку 0.3 секунды для создания напряжения
    import asyncio
    await asyncio.sleep(0.3)
    
    # Платим за последний полностью пройденный уровень
    last_level = max(0, game['level'] - 1)
    mult = MULTS[last_level] if last_level < len(MULTS) else MULTS[-1]
    win = game['bet'] * mult
    game['alive'] = False
    try:
        import database as db
        db.increment_dan_win(game['user_id'], max(win-game['bet'],0))
        db.increment_dan_lose(game['user_id'], game['bet'])
    except Exception:
        pass
    return {'status': 'take', 'msg': f'Вы забрали {win:.2f} Дань!'}
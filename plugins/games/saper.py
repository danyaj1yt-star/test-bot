# --- Saper 3x3: доп-скрипт для интеграции ---
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

SIZE = 3
BOMBS = 2
BLACK = "⬛"
BOMB = "💣"

class SimpleSaper:
    def result_text(self, show_opened=False):
        # show_opened=True: белые квадраты на открытых, 🚩 на бомбах, остальное — чёрные
        WHITE = '⬜️'
        FLAG = '💣'
        lines = []
        for r in range(SIZE):
            row = []
            for c in range(SIZE):
                if show_opened:
                    if (r, c) in self.bombs:
                        row.append(FLAG)
                    elif (r, c) in self.revealed:
                        row.append(WHITE)
                    else:
                        row.append(BLACK)
                else:
                    if (r, c) in self.bombs:
                        row.append(FLAG)
                    else:
                        row.append(BLACK)
            lines.append(''.join(row))
        return '\n'.join(lines)
    def __init__(self, stake=0, owner_id=None, game_id=None):
        cells = [(r, c) for r in range(SIZE) for c in range(SIZE)]
        self.bombs = set(random.sample(cells, BOMBS))
        self.revealed = set()
        self.display = {}  # (r, c) -> str (число или '?')
        self.stake = stake
        self.multiplier = 1.0
        self.finished = False
        self.owner_id = owner_id
        self.game_id = game_id or generate_unique_game_id(owner_id)

    def neighbors(self, r, c):
        return [ (nr, nc)
            for nr in range(max(0, r-1), min(SIZE, r+2))
            for nc in range(max(0, c-1), min(SIZE, c+2))
            if (nr, nc) != (r, c)
        ]

    def cell_text(self, r, c):
        if (r, c) not in self.revealed:
            return BLACK
        if (r, c) in self.bombs:
            return BOMB
        return self.display.get((r, c), BLACK)

    def open(self, r, c):
        if (r, c) in self.revealed:
            return False
        self.revealed.add((r, c))
        if (r, c) not in self.bombs:
            count = sum((nr, nc) in self.bombs for nr, nc in self.neighbors(r, c))
            # Ограничить максимум двумя клетками с "2"
            twos = sum(1 for v in self.display.values() if v == "2")
            if count == 2 and twos < 2 and random.choice([True, False]):
                self.display[(r, c)] = "2"
            else:
                self.display[(r, c)] = "?"
            # Новый рост множителя (потолок 2.5):
            # 1-я +0.25, 2-я +0.30, 3-я +0.35, 4-я +0.40, 5-я +0.20
            opened = len([cell for cell in self.revealed if cell not in self.bombs])
            increments = [0.25, 0.30, 0.35, 0.40, 0.20]
            if opened <= len(increments):
                self.multiplier += increments[opened - 1]
            # Ограничим максимумом 2.5
            if self.multiplier > 2.5:
                self.multiplier = 2.5
        return True

    def keyboard(self, show_bombs_on_lose=False, show_repeat=False):
        kb = []
        if self.finished or show_bombs_on_lose:
            # Показываем все бомбы, остальные клетки — чёрные, все кнопки неактивны
            kb = [
                [InlineKeyboardButton(text=(BOMB if (r, c) in self.bombs else BLACK), callback_data="none") for c in range(SIZE)]
                for r in range(SIZE)
            ]
            if show_repeat:
                kb.append([InlineKeyboardButton(text="Повторить", callback_data=f"saper_repeat:{self.game_id}:{self.stake}")])
            return InlineKeyboardMarkup(inline_keyboard=kb)
        kb = [
            [InlineKeyboardButton(text=self.cell_text(r, c), callback_data=f"saper_open:{self.game_id}:{r}:{c}") for c in range(SIZE)]
            for r in range(SIZE)
        ]
        safe_cells = SIZE * SIZE - BOMBS
        if 0 < len(self.revealed) < safe_cells:
            kb.append([InlineKeyboardButton(text="Забрать", callback_data=f"saper_take:{self.game_id}")])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def status_text(self):
        return f"Сапёр 3x3! Ваша ставка {self.stake} ДАНЬ\nВыигрыш {self.multiplier:.1f}х\n\nОткрой клетку:"

# --- Хранилище игр ---
import time
import random
from typing import Dict

SIZE = 3
BOMB_COUNT = 1
active_saper_games: Dict[str, 'SimpleSaper'] = {}

def generate_unique_game_id(user_id):
    """Генерирует уникальный ID игры с наносекундной точностью"""
    return f"saper_{user_id}_{time.time_ns()}"
import time


# --- Обработчик команды сапёр ---
async def saper_message_handler(message):
    text = message.text.strip().lower() if message.text else ""
    if "сапер" in text:
        user_id = message.from_user.id
        parts = text.split()
        if len(parts) < 2:
            await message.reply("Формат: сапер X (X — сумма)")
            return
        try:
            stake = int(parts[1])
        except Exception:
            await message.reply("Ставка должна быть числом.")
            return
        await start_saper_game(message, stake)

# --- Новый хелпер для старта сапёра по ставке ---
async def start_saper_game(message, stake):
    user_id = message.from_user.id
    if stake < 10:
        await message.reply("Минимальная ставка — 10 Дань.")
        return
    import database as db
    user = db.get_user(user_id)
    if not user or user["dan"] < stake:
        await message.reply(f"Недостаточно Дань! Ваш баланс: {user['dan'] if user else 0}")
        return
    # Создаем новую игру с уникальным ID (больше никаких ограничений!)
    game_id = generate_unique_game_id(user_id)
    db.withdraw_dan(user_id, stake)
    active_saper_games[game_id] = SimpleSaper(stake=stake, owner_id=user_id, game_id=game_id)
    await message.reply(active_saper_games[game_id].status_text(), reply_markup=active_saper_games[game_id].keyboard())

# --- Обработчик колбеков сапёра ---
async def saper_callback_handler(callback):
    user_id = callback.from_user.id
    
    # --- Обработка кнопки "Повторить" ---
    if callback.data.startswith("saper_repeat:"):
        # Проверяем владельца игры перед передачей в main
        try:
            parts = callback.data.split(":")
            if len(parts) >= 2:
                game_id = parts[1]
                # Если игра еще существует, проверяем владельца
                if game_id in active_saper_games:
                    game = active_saper_games[game_id]
                    if callback.from_user.id != game.owner_id:
                        await callback.answer("Только владелец игры может повторить", show_alert=True)
                        return
            
            from main import saper_repeat_callback
            await saper_repeat_callback(callback)
        except Exception:
            await callback.answer("Ошибка при повторе игры", show_alert=True)
        return
    
    # Извлекаем game_id из callback_data
    if callback.data.startswith("saper_open:"):
        parts = callback.data.split(":")
        if len(parts) >= 2:
            game_id = parts[1]
        else:
            await callback.answer("Неверный формат данных", show_alert=True)
            return
    elif callback.data.startswith("saper_take:"):
        parts = callback.data.split(":")
        if len(parts) >= 2:
            game_id = parts[1]
        else:
            await callback.answer("Неверный формат данных", show_alert=True)
            return
    else:
        await callback.answer("Неизвестная команда", show_alert=True)
        return
    
    game = active_saper_games.get(game_id)
    if not game:
        try:
            await callback.answer("Игра не найдена.", show_alert=True)
        except Exception:
            pass
        return
    # Приватность: только владелец может нажимать игровые кнопки
    if user_id != game.owner_id:
        try:
            await callback.answer("Это не ваша игра!", show_alert=True)
        except Exception:
            pass
        return
    if game.finished:
        try:
            await callback.answer("Игра завершена", show_alert=True)
        except Exception:
            pass
        return
    
    # Обработка кнопки "Забрать"
    if callback.data.startswith("saper_take:"):
        game.finished = True
        import asyncio
        import database as db
        if any(cell in game.revealed for cell in game.bombs):
            # Проигрыш: задержка 1 секунда, затем показываем поле с бомбами и кнопку "Повторить"
            try:
                db.increment_dan_lose(user_id, game.stake)
            except Exception:
                pass
            user_row = db.get_user(user_id)
            bal = user_row["dan"] if user_row else 0
            import main as main
            await asyncio.sleep(1)
            await main.safe_edit_text(callback.message,
                f"Вы проиграли {game.stake} ДАНЬ.\nВаш баланс: {bal} ДАНЬ",
                reply_markup=game.keyboard(show_bombs_on_lose=True, show_repeat=True),
                parse_mode="HTML"
            )
            # Очищаем завершенную игру
            if game_id in active_saper_games:
                del active_saper_games[game_id]
        else:
            win = int(game.stake * game.multiplier)
            db.add_dan(user_id, win)
            try:
                db.increment_dan_win(user_id, win - game.stake)  # Чистый выигрыш
            except Exception:
                pass
            user_row = db.get_user(user_id)
            bal_after = user_row["dan"] if user_row else 0
            bal_before = bal_after - win + game.stake
            import main as main
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Повторить", callback_data=f"saper_repeat:{game_id}:{game.stake}")]
            ])
            await asyncio.sleep(1)
            await main.safe_edit_text(
                callback.message,
                f"Вы выиграли {win} ДАНЬ.\nСтавка: {game.stake} ДАНЬ\nРезультаты:\n{game.result_text(show_opened=True)}\nВаш баланс: {bal_after} (было {bal_before}) ДАНЬ",
                reply_markup=kb
            )
            # Очищаем завершенную игру
            if game_id in active_saper_games:
                del active_saper_games[game_id]
        return
    if callback.data.startswith("saper_open:"):
        parts = callback.data.split(":")
        if len(parts) >= 4:
            _, game_id, r, c = parts[:4]
            r, c = int(r), int(c)
        else:
            await callback.answer("Неверный формат команды открытия", show_alert=True)
            return
        if not game.open(r, c):
            try:
                await callback.answer("Эта клетка уже открыта", show_alert=True)
            except Exception:
                pass
            return
        # Проверка на проигрыш (открыли бомбу)
        if (r, c) in game.bombs:
            game.finished = True
            import asyncio
            import database as db
            try:
                db.increment_dan_lose(user_id, game.stake)
            except Exception:
                pass
            user_row = db.get_user(user_id)
            bal = user_row["dan"] if user_row else 0
            import main as main
            await asyncio.sleep(1)
            await main.safe_edit_text(callback.message,
                f"Вы проиграли {game.stake} ДАНЬ.\nВаш баланс: {bal} ДАНЬ",
                reply_markup=game.keyboard(show_bombs_on_lose=True, show_repeat=True),
                parse_mode="HTML"
            )
            return
        kb = game.keyboard()
        import main
        await main.safe_edit_text(callback.message, game.status_text(), reply_markup=kb)
        total_cells = SIZE * SIZE
        safe_cells = total_cells - BOMBS
        unopened_bombs = [cell for cell in game.bombs if cell not in game.revealed]
        if len(game.revealed) == safe_cells and len(unopened_bombs) == BOMBS:
            game.finished = True
            # Финальный множитель ограничен 2.5
            if game.multiplier < 2.5:
                game.multiplier = 2.5
            win = int(game.stake * game.multiplier)
            import asyncio
            import database as db
            db.add_dan(user_id, win)
            user_row = db.get_user(user_id)
            bal = user_row["dan"] if user_row else 0
            import main as main
            await asyncio.sleep(1)
            await main.safe_edit_text(callback.message,
                f"Вы выиграли ставку {win} ДАНЬ.\nСтавка: {game.stake} ДАНЬ\nРезультаты:\n{game.result_text()}\nВаш баланс: {bal} (+{win}) ДАНЬ",
                reply_markup=None
            )
            # Очищаем завершенную игру
            if game_id in active_saper_games:
                del active_saper_games[game_id]
            return

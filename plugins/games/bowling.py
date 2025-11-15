"""
🎳 Bowling Game
Игра в боулинг с выбором исхода
"""

import random
import asyncio
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database as db

# Multipliers for winning (основано на Telegram dice значениях 1-6)
MULTIPLIERS = {
    "strike": 5.8,      # 6 кегель - страйк (максимум)
    "spare": 4.5,       # 5 кегель - отлично
    "good": 3.0,        # 3-4 кегли - среднее
    "medium": 2.0,      # 2 кегли - слабо
    "bad": 1.5          # 1 кегля - мимо (минимальный выигрыш)
}

# Store active bowling games: user_id -> game_state
active_bowling_games = {}


class BowlingGame:
    """Represents a bowling game instance"""
    
    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.pins_fallen = None  # Will be set after user chooses
        self.user_choice = None  # User's predicted outcome
        self.result = None
        self.multiplier = None
        self.winnings = 0
        
    def generate_result(self):
        """Generate random bowling result (0-10 pins fallen)"""
        # 15% chance for strike (10 pins)
        # 15% chance for spare (9 pins)
        # 25% chance for good (6-8 pins)
        # 25% chance for medium (3-5 pins)
        # 20% chance for bad (0-2 pins)
        
        r = random.random()
        if r < 0.15:
            self.pins_fallen = 10
            self.result = "strike"
        elif r < 0.30:
            self.pins_fallen = 9
            self.result = "spare"
        elif r < 0.55:
            self.pins_fallen = random.randint(6, 8)
            self.result = "good"
        elif r < 0.80:
            self.pins_fallen = random.randint(3, 5)
            self.result = "medium"
        else:
            self.pins_fallen = random.randint(0, 2)
            self.result = "bad"
    
    def check_win(self):
        """Check if user won based on pins_fallen (from dice result)"""
        # Если pins_fallen ещё не установлен, генерируем случайно (fallback)
        if self.pins_fallen is None:
            self.generate_result()
        
        # Маппим dice значение (1-6) на реальное количество кегель для игрока:
        # dice 1 -> 0 кегель (мимо)
        # dice 2 -> 1 кегля
        # dice 3 -> 3 кегли
        # dice 4 -> 4 кегли
        # dice 5 -> 5 кегель
        # dice 6 -> 6 кегель (страйк)
        dice_to_pins_map = {
            1: 0,  # мимо
            2: 1,  # 1 кегля
            3: 3,  # 3 кегли
            4: 4,  # 4 кегли
            5: 5,  # 5 кегель
            6: 6   # страйк
        }
        
        actual_pins = dice_to_pins_map.get(self.pins_fallen, self.pins_fallen)  # type: ignore
        
        # Преобразуем выбор пользователя в число для сравнения
        # user_choice теперь содержит строку с числом: "0", "1", "3", "4", "5", "6"
        try:
            predicted_pins = int(self.user_choice) # type: ignore
        except (ValueError, TypeError):
            # Если не удалось преобразовать, считаем проигрышем
            self.multiplier = 0
            self.winnings = 0
            return False
        
        # Сравниваем предсказание с фактическим результатом
        if predicted_pins == actual_pins:
            # Рандомный множитель от 2.0 до 5.0 (с шагом 0.1)
            self.multiplier = round(random.uniform(2.0, 5.0), 1)
            self.winnings = int(self.bet * self.multiplier)
            return True
        else:
            self.multiplier = 0
            self.winnings = 0
            return False
    
    def get_emoji_animation(self):
        """Get emoji representation of pins falling"""
        fallen = self.pins_fallen or 0
        standing = 10 - fallen
        
        # Show bowling pins emoji 🎳 and animation
        if fallen == 10:
            return "🎳" * 5 + " → " + "💥" * 5 + f" (ВСЕ 10 кегель упали!)"
        elif fallen >= 7:
            return "🎳" * standing + " → " + "💥" * fallen + f" ({fallen} упало)"
        elif fallen >= 4:
            return "🎳" * standing + " → " + "💥" * fallen + f" ({fallen} упало)"
        else:
            return "🎳" * standing + " → " + "💥" * fallen + f" ({fallen} упало)"
    
    def get_status_text(self):
        """Get formatted game status text - новый формат как в примере"""
        if self.winnings > 0:
            # Победа
            text = "🎉 <b>Боулинг · Победа!</b> ✅\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"🎲 <b>Выбрано:</b> {self._choice_to_emoji_text()}\n"
            text += f"💰 <b>Выигрыш:</b> х{self.multiplier:.1f} / {self.winnings} Дань\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_emoji_text()}</blockquote>"
        else:
            # Проигрыш
            text = "🫣 <b>Боулинг · Проигрыш!</b>\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"🎲 <b>Выбрано:</b> {self._choice_to_emoji_text()}\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_emoji_text()}</blockquote>"
        
        return text
    
    def _choice_to_text(self):
        """Convert choice to readable text"""
        choices = {
            "strike": "🎳 СТРАЙК (6 кегель)",
            "spare": "⚡ ОТЛИЧНО (5 кегель)",
            "good": "🤔 СРЕДНЕЕ (3-4 кегель)",
            "medium": "😐 СЛАБО (2 кегля)",
            "bad": "😢 МИМО (1 кегля)"
        }
        return choices.get(self.user_choice, "Не выбрано") if self.user_choice else "Не выбрано"
    
    def _choice_to_emoji_text(self):
        """Convert choice to emoji text for new format"""
        # Маппинг выбора (теперь числа) на текст с эмодзи
        emoji_map = {
            "0": "мимо 😧",
            "1": "1⃣ кегля",
            "3": "3⃣ кегли",
            "4": "4⃣ кегли",
            "5": "5⃣ кегель",
            "6": "страйк 🎳"
        }
        return emoji_map.get(self.user_choice or "", "не выбрано")
    
    def _result_to_emoji_text(self):
        """Convert result to emoji text for new format"""
        # Telegram dice для боулинга возвращает 1-6, маппим на понятные значения:
        # dice 1 = мимо (0 кегель), dice 2 = 1 кегля, dice 3 = 3 кегли
        # dice 4 = 4 кегли, dice 5 = 5 кегель, dice 6 = страйк
        if self.pins_fallen == 6:
            return "страйк 🎳"
        elif self.pins_fallen == 5:
            return "5⃣ кегель"
        elif self.pins_fallen == 4:
            return "4⃣ кегли"
        elif self.pins_fallen == 3:
            return "3⃣ кегли"
        elif self.pins_fallen == 2:
            return "1⃣ кегля"
        elif self.pins_fallen == 1:
            return "мимо 😧"
        else:
            return f"{self.pins_fallen} кегель"
    
    def _result_to_text(self):
        """Convert result to readable text"""
        results = {
            "strike": "🎳 СТРАЙК! 6 кегель упало!",
            "spare": "⚡ ОТЛИЧНО! 5 кегель упало!",
            "good": "🤔 СРЕДНЕЕ. 3-4 кегель упало",
            "medium": "😐 СЛАБО. 2 кегли упало",
            "bad": "😢 МИМО. 1 кегля упала"
        }
        return results.get(self.result, "Неизвестный результат") if self.result else "Неизвестный результат"


def build_choice_keyboard():
    """Build keyboard for outcome selection - структура 2x2 + 1 + 1 + 1"""
    kb = InlineKeyboardBuilder()
    
    # Первая строка: 2 кнопки
    kb.button(text="1️⃣ кегля", callback_data="bowling_choice:1")
    kb.button(text="3️⃣ кегли", callback_data="bowling_choice:3")
    
    # Вторая строка: 2 кнопки
    kb.button(text="4️⃣ кегли", callback_data="bowling_choice:4")
    kb.button(text="5️⃣ кегель", callback_data="bowling_choice:5")
    
    # Третья строка: 1 кнопка - Страйк
    kb.button(text="🎳 Страйк", callback_data="bowling_choice:6")
    
    # Четвёртая строка: 1 кнопка - Мимо
    kb.button(text="😁 Мимо", callback_data="bowling_choice:0")
    
    # Пятая строка: 1 кнопка - Отмена
    kb.button(text="Отменить ❌", callback_data="bowling_cancel")
    
    # Раскладка: 2, 2, 1, 1, 1 (кнопок в каждой строке)
    kb.adjust(2, 2, 1, 1, 1)
    return kb.as_markup()


def get_nick(user):
    """Get display name from user"""
    username = getattr(user, 'username', None)
    if username:
        return f'@{username}'
    return f"User_{user.id}"


# Импорт функции счетчика игр
def get_increment_games_count():
    try:
        from main import increment_games_count
        return increment_games_count
    except ImportError:
        return lambda: None  # заглушка если не удается импортировать

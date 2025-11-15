"""
🎯 Darts Game
Игра в дартс с четырьмя исходами: мимо / рядом / близко / попал (категории по dice 1-6)
"""

import random
from aiogram.utils.keyboard import InlineKeyboardBuilder

class DartsGame:
    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.user_choice: str | None = None  # 'miss' | 'near' | 'close' | 'hit'
        self.dice_value: int | None = None
        self.multiplier: float = 0.0
        self.winnings: int = 0

    def check_win(self):
        # Если результат ещё не установлен — проигрыш по умолчанию
        if self.dice_value is None:
            self.multiplier = 0.0
            self.winnings = 0
            return False

        category = self.category_from_dice(self.dice_value)
        predicted = (self.user_choice or "").strip()

        if predicted == category:
            # Выплаты по категориям при верном угадывании:
            # miss -> 2.0–3.0x, near -> 1.6–3.0x, close -> 2.2–3.5x, hit -> 4.0–6.0x
            if category == "miss":
                self.multiplier = round(random.uniform(2.0, 3.0), 1)
            elif category == "near":
                self.multiplier = round(random.uniform(1.6, 3.0), 1)
            elif category == "close":
                self.multiplier = round(random.uniform(2.2, 3.5), 1)
            else:  # hit
                self.multiplier = round(random.uniform(4.0, 6.0), 1)
            self.winnings = int(self.bet * self.multiplier)
            return True
        self.multiplier = 0.0
        self.winnings = 0
        return False

    @staticmethod
    def category_from_dice(value: int) -> str:
        # 1-2: мимо, 3-4: рядом, 5: близко, 6: попал (булл)
        if value == 6:
            return "hit"
        if value == 5:
            return "close"
        if value in (3, 4):
            return "near"
        return "miss"

    def _choice_to_text(self) -> str:
        mapping = {
            "hit": "попал 👑",
            "close": "близко",
            "near": "рядом",
            "miss": "мимо"
        }
        return mapping.get(self.user_choice or "", "не выбрано")

    def _result_to_text(self) -> str:
        if self.dice_value is None:
            return "—"
        mapping = {
            6: "булл 👑",
            5: "очень близко",
            4: "внутренний круг",
            3: "сектор",
            2: "край",
            1: "мимо"
        }
        return mapping.get(self.dice_value, str(self.dice_value))

    def get_status_text(self) -> str:
        if self.winnings > 0:
            text = "🎉 <b>Дартс · Победа!</b> ✅\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"🎯 <b>Выбрано:</b> {self._choice_to_text()}\n"
            text += f"💰 <b>Выигрыш:</b> х{self.multiplier:.1f} / {self.winnings} Дань\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_text()}</blockquote>"
        else:
            text = "🫣 <b>Дартс · Проигрыш!</b>\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"🎯 <b>Выбрано:</b> {self._choice_to_text()}\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_text()}</blockquote>"
        return text


def build_choice_keyboard():
    kb = InlineKeyboardBuilder()
    # Четыре кнопки: мимо, рядом, близко, попал
    kb.button(text="😁 Мимо 2–3x", callback_data="darts_choice:miss")
    kb.button(text="🤏 Рядом 1.6–3x", callback_data="darts_choice:near")
    kb.button(text="🟡 Близко 2.2–3.5x", callback_data="darts_choice:close")
    kb.button(text="🎯 Попал 4–6x", callback_data="darts_choice:hit")
    kb.adjust(2, 2)
    kb.button(text="Отменить ❌", callback_data="darts_cancel")
    kb.adjust(2, 2, 1)
    return kb.as_markup()

"""
⚽ Soccer Game
Игра в футбол с угадыванием результата броска (dice 1-6)
"""

import random
from aiogram.utils.keyboard import InlineKeyboardBuilder

class SoccerGame:
    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.user_choice: str | None = None
        self.dice_value: int | None = None
        self.multiplier: float = 0.0
        self.winnings: int = 0

    def check_win(self):
        if self.dice_value is None:
            self.multiplier = 0.0
            self.winnings = 0
            return False

        # Категоризация результата: мимо / сейв / штанга/перекладина / гол
        category = self.category_from_dice(self.dice_value)
        predicted = (self.user_choice or "").strip()

        if predicted == category:
            # Выплаты по категориям при верном угадывании:
            # miss, save, near -> 1.7–2.5x, goal -> 3.0–5.0x
            if category == "goal":
                self.multiplier = round(random.uniform(3.0, 5.0), 1)
            else:  # miss, save, near
                self.multiplier = round(random.uniform(1.7, 2.5), 1)
            self.winnings = int(self.bet * self.multiplier)
            return self.winnings > 0

        self.multiplier = 0.0
        self.winnings = 0
        return False

    @staticmethod
    def category_from_dice(value: int) -> str:
        # 1–2: мимо, 3: сейв, 4–5: штанга/перекладина, 6: гол
        if value == 6:
            return "goal"
        if value in (4, 5):
            return "near"
        if value == 3:
            return "save"
        return "miss"

    def _choice_to_text(self) -> str:
        mapping = {
            "goal": "гол",
            "near": "штанга/перекладина",
            "save": "сейв",
            "miss": "мимо"
        }
        return mapping.get(self.user_choice or "", "не выбрано")

    def _result_to_text(self) -> str:
        if self.dice_value is None:
            return "—"
        mapping = {
            6: "ГОООЛ! 🥳",
            5: "штанга",
            4: "перекладина",
            3: "сейв",
            2: "мимо",
            1: "промах"
        }
        return mapping.get(self.dice_value, str(self.dice_value))

    def get_status_text(self) -> str:
        if self.winnings > 0:
            text = "🎉 <b>Футбол · Победа!</b> ✅\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"⚽ <b>Выбрано:</b> {self._choice_to_text()}\n"
            text += f"💰 <b>Выигрыш:</b> х{self.multiplier:.1f} / {self.winnings} Дань\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_text()}</blockquote>"
        else:
            text = "🫣 <b>Футбол · Проигрыш!</b>\n"
            text += "-------------------------\n"
            text += f"💸 <b>Ставка:</b> {self.bet} Дань\n"
            text += f"⚽ <b>Выбрано:</b> {self._choice_to_text()}\n"
            text += "-------------\n"
            text += f"<blockquote>⚡️ Итог: {self._result_to_text()}</blockquote>"
        return text


def build_choice_keyboard():
    kb = InlineKeyboardBuilder()
    # Четыре кнопки: мимо, сейв, штанга/перекладина, гол
    kb.button(text="😁 Мимо", callback_data="soccer_choice:miss")
    kb.button(text="🧤 Сейв", callback_data="soccer_choice:save")
    kb.button(text="🤏 Штанга/перекладина", callback_data="soccer_choice:near")
    kb.button(text="🥳 Гол", callback_data="soccer_choice:goal")
    kb.adjust(2, 1, 1)
    kb.button(text="Отменить ❌", callback_data="soccer_cancel")
    kb.adjust(2, 1, 1, 1)
    return kb.as_markup()

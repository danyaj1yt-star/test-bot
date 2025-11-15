# case_system.py - Система открытия кейсов/сундуков
import random
import sqlite3
from typing import Dict, List, Tuple, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import database as db

# NOTE: Экономика кейсов переработана: ограничены максимальные выигрыши.
# Level1 price (получение через предмет) – не продаётся напрямую, балансируем содержимое отдельно.
# Level2 потолок выигрыша 50k, Level3 потолок 100k. Добавлен pity (гарант НЕпустой после серии пустых/низких).

# Конфигурация кейсов (шансы в сумме ~100). Денежные диапазоны жестко ограничены.
CASE_CONFIG = {
    "chest_level1": {
        "price": 2000,
        "name": "Сундук 1 уровня",
        "photo": "C:/BotKruz/ChatBotKruz/photo/chest1.png",
        "slots": 9,
        "max_opens": 3,
        "pity_threshold": 5,
        "rewards": {
            "empty": {"chance": 28, "emoji": "▫️", "name": "Пусто"},
            "money_small": {"chance": 30, "emoji": "💰", "name": "Деньги", "min_amount": 500, "max_amount": 1500},
            "money_mid": {"chance": 18, "emoji": "💰", "name": "Деньги", "min_amount": 1500, "max_amount": 2500},
            "money_high": {"chance": 10, "emoji": "💰", "name": "Деньги", "min_amount": 2500, "max_amount": 5000},
            "wheat": {"chance": 15, "emoji": "🌾", "name": "Пшеница", "item_id": "06", "min_count": 1, "max_count": 2},
            "corn": {"chance": 20, "emoji": "🌽", "name": "Кукуруза", "item_id": "07", "min_count": 1, "max_count": 2}
        }
    },
    "chest_level2": {
        "price": 10000,
        "name": "Сундук 2 уровня",
        "photo": "C:/BotKruz/ChatBotKruz/photo/chest2.png",
        "slots": 9,
        "max_opens": 3,
        "pity_threshold": 5,
        # Limits to avoid huge payouts
    "max_slot_amount": 5000,
    "session_max_payout": 15000,
        "rewards": {
            # Chest level2 should only give money in the 2k-5k range (randomized)
            "empty": {"chance": 14, "emoji": "▫️", "name": "Пусто"},
            "money": {"chance": 86, "emoji": "💰", "name": "Деньги", "min_amount": 2000, "max_amount": 5000},
            "wheat": {"chance": 15, "emoji": "🌾", "name": "Пшеница", "item_id": "06", "min_count": 3, "max_count": 7},
            "corn": {"chance": 20, "emoji": "🌽", "name": "Кукуруза", "item_id": "07", "min_count": 3, "max_count": 7}
        }
    },
    "chest_level3": {
        "price": 50000,
        "name": "Сундук 3 уровня",
        "photo": "C:/BotKruz/ChatBotKruz/photo/chest3.png",
        "slots": 9,
        "max_opens": 3,
        "pity_threshold": 6,
        "max_slot_amount": 23000,
        "session_max_payout": 75000,
        "rewards": {
            # Tuned bands to target ~44k average session payout
            # Higher empty chance reduces average; adjust bands and chances below
            "empty": {"chance": 40, "emoji": "▫️", "name": "Пусто"},
            "money_small": {"chance": 15, "emoji": "💰", "name": "Малый куш", "min_amount": 5000, "max_amount": 15000},
            "money_mid": {"chance": 39, "emoji": "💰", "name": "Средний куш", "min_amount": 20000, "max_amount": 35000},
            "money_big": {"chance": 6, "emoji": "🔥", "name": "Большой куш", "min_amount": 35000, "max_amount": 70000},
            "wheat": {"chance": 15, "emoji": "🌾", "name": "Пшеница", "item_id": "06", "min_count": 4, "max_count": 13},
            "corn": {"chance": 20, "emoji": "🌽", "name": "Кукуруза", "item_id": "07", "min_count": 6, "max_count": 15}
        }
    }
}

# Активные сессии открытия кейсов
active_case_sessions = {}

_user_fail_streak: Dict[int, int] = {}

# Minimum payout for any money reward
MIN_PAYOUT = 1000

class CaseSession:
    def __init__(self, user_id: int, case_type: str, message_id: int):
        self.user_id = user_id
        self.case_type = case_type  
        self.message_id = message_id
        self.slots = [None] * CASE_CONFIG[case_type]["slots"]  # None = не открыто
        self.opened_count = 0
        # track total money awarded this session
        self.total_payout = 0
        
    def open_slot(self, slot_index: int) -> dict:
        """Открывает слот и возвращает награду"""
        if self.slots[slot_index] is not None:
            return {"error": "Слот уже открыт"}
        
        # Проверяем лимит открытий
        max_opens = CASE_CONFIG[self.case_type]["max_opens"]
        if self.opened_count >= max_opens:
            return {"error": f"Можно открыть только {max_opens} слота"}
            
        reward = self.roll_reward()
        self.slots[slot_index] = reward
        self.opened_count += 1
        # If reward has money, accumulate to session total
        if reward and isinstance(reward, dict) and 'amount' in reward:
            try:
                self.total_payout = getattr(self, 'total_payout', 0) + int(reward['amount'])
            except Exception:
                pass
        
        return reward
    
    def roll_reward(self) -> dict:
        """Определяет награду по шансам с учетом fail streak (pity)."""
        cfg = CASE_CONFIG[self.case_type]
        rewards = cfg["rewards"]
        fail_streak = _user_fail_streak.get(self.user_id, 0)
        pity_threshold = cfg.get("pity_threshold", 999)

        # Если игрок достиг порога неудач – исключаем 'empty'
        weighted = []
        for r_type, r_cfg in rewards.items():
            if fail_streak >= pity_threshold and r_type == "empty":
                continue
            weighted.extend([r_type] * r_cfg["chance"])
        if not weighted:  # fallback
            weighted = [r for r in rewards.keys() if r != 'empty'] or list(rewards.keys())
        chosen = random.choice(weighted)
        rcfg = rewards[chosen]

        # Обновление fail streak
        if chosen == 'empty':
            _user_fail_streak[self.user_id] = fail_streak + 1
        else:
            _user_fail_streak[self.user_id] = 0

        res = {"type": chosen, "emoji": rcfg["emoji"], "name": rcfg["name"]}
        # Денежные типы: используем конфиг вознаграждения, если задан min/max/fixed
        price = int(cfg.get('price', 1000))
        # session cap relative to price (soft cap) used earlier was price*1.7, we still respect per-case session_max_payout if provided
        soft_session_cap = int(price * 1.7)
        # detect money reward by presence of min/max/fixed or by name
        is_money_reward = any(k in rcfg for k in ('min_amount', 'max_amount', 'fixed_amount')) or rcfg.get('name','').lower().find('день') != -1
        if is_money_reward:
            # Determine base min/max from reward config, fallback to MIN_PAYOUT/soft cap
            min_amount = int(rcfg.get('min_amount', MIN_PAYOUT))
            max_amount = int(rcfg.get('max_amount', soft_session_cap))
            if 'fixed_amount' in rcfg:
                amount = int(rcfg['fixed_amount'])
            else:
                # ensure bounds sensible
                if max_amount < min_amount:
                    max_amount = min_amount
                amount = random.randint(min_amount, max_amount)

            # enforce overall per-session cap (explicit session_max_payout has priority)
            session_cap_cfg = cfg.get('session_max_payout')
            if session_cap_cfg is not None:
                remaining = int(session_cap_cfg) - int(getattr(self, 'total_payout', 0))
            else:
                remaining = soft_session_cap - int(getattr(self, 'total_payout', 0))

            # If remaining budget is less than the reward's minimum, treat as empty (no tiny partial payouts)
            if remaining < min_amount:
                return {"type": "empty", "emoji": cfg['rewards']['empty']['emoji'], "name": "Пусто"}

            if amount > remaining:
                # If remaining is smaller than min_amount -> empty (already handled), else clamp to remaining
                amount = remaining

            res['amount'] = int(amount)
            res['subtype'] = chosen
            res['type'] = 'money'
        # Clamp amounts by per-slot and per-session caps
        if 'amount' in res:
            # per-slot cap
            slot_cap = cfg.get('max_slot_amount')
            if slot_cap is not None:
                res['amount'] = min(int(res['amount']), int(slot_cap))
            # per-session cap
            session_cap = cfg.get('session_max_payout')
            if session_cap is not None:
                remaining = int(session_cap) - int(getattr(self, 'total_payout', 0))
                if remaining <= 0:
                    # no payout left in this session -> treat as empty
                    return {"type": "empty", "emoji": cfg['rewards']['empty']['emoji'], "name": "Пусто"}
                if res['amount'] > remaining:
                    # reduce to remaining (but if remaining too small, convert to empty)
                    if remaining < 50:
                        return {"type": "empty", "emoji": cfg['rewards']['empty']['emoji'], "name": "Пусто"}
                    res['amount'] = remaining
    # Кейс апгрейд
    # Пшеница / кукуруза (предметы) остаются
        if 'item_id' in rcfg:
            res['item_id'] = rcfg['item_id']
            if 'min_count' in rcfg and 'max_count' in rcfg:
                res['count'] = random.randint(rcfg['min_count'], rcfg['max_count'])
            else:
                res['count'] = 1
        return res
    
    def is_complete(self) -> bool:
        """Проверяет, достигнут ли лимит открытий"""
        max_opens = CASE_CONFIG[self.case_type]["max_opens"]
        return self.opened_count >= max_opens
    
    def get_status_text(self) -> str:
        """Возвращает текст со статусом слотов"""
        case_name = CASE_CONFIG[self.case_type]["name"]
        max_opens = CASE_CONFIG[self.case_type]["max_opens"]
        remaining = max_opens - self.opened_count
        
        lines = [f"🎁 {case_name}"]
        lines.append(f"Открыто: {self.opened_count}/{max_opens} | Осталось: {remaining}")
        lines.append("")
        
        # helper to format money amounts similarly to main.format_number_beautiful
        def _fmt_amount(amount) -> str:
            try:
                amt = int(amount)
            except Exception:
                try:
                    amt = int(float(amount))
                except Exception:
                    return str(amount)
            return f"{amt:,}".replace(",", " ") + ".00"

        opened_slots = []
        for i, slot in enumerate(self.slots):
            if slot is not None:
                if slot["type"] == "empty":
                    opened_slots.append(f"Слот {i+1}: {slot['emoji']} {slot['name']}")
                elif slot["type"] == "money":
                    opened_slots.append(f"Слот {i+1}: {slot['emoji']} {_fmt_amount(slot['amount'])} Дань")
                else:
                    count = slot.get("count", 1)
                    if count > 1:
                        opened_slots.append(f"Слот {i+1}: {slot['emoji']} {slot['name']} x{count}")
                    else:
                        opened_slots.append(f"Слот {i+1}: {slot['emoji']} {slot['name']}")
        
        if opened_slots:
            lines.extend(opened_slots)
            # Show session total of money awarded so far
            try:
                total = int(getattr(self, 'total_payout', 0) or 0)
            except Exception:
                try:
                    total = int(float(getattr(self, 'total_payout', 0) or 0))
                except Exception:
                    total = 0
            lines.append("")
            lines.append(f"Всего: {_fmt_amount(total)} дань")
        else:
            lines.append("Выберите слоты для открытия:")
        
        return "\n".join(lines)
    
    def get_keyboard(self) -> InlineKeyboardMarkup:
        """Создает клавиатуру 3x3 для выбора слотов"""
        buttons = []
        for i in range(9):  # Всегда 9 кнопок
            if i < len(self.slots) and self.slots[i] is not None:
                # Открытый слот показывает награду
                emoji = self.slots[i]["emoji"]
            else:
                # Закрытый слот
                emoji = "◾️"
            
            buttons.append(InlineKeyboardButton(
                text=emoji, 
                callback_data=f"open_slot:{self.case_type}:{i}"
            ))
        
        # Разбиваем на 3 ряда по 3 кнопки
        keyboard = [
            buttons[0:3],   # Первый ряд
            buttons[3:6],   # Второй ряд  
            buttons[6:9]    # Третий ряд
        ]
        
        # Добавляем кнопки управления: всегда показываем кнопку "Забрать"
        max_opens = CASE_CONFIG[self.case_type]["max_opens"]
        remaining = max_opens - self.opened_count
        if not self.is_complete():
            keyboard.append([
                InlineKeyboardButton(text=f"Осталось открытий: {remaining}", callback_data="noop")
            ])
        keyboard.append([InlineKeyboardButton(text="✅ Забрать", callback_data="close_case")])
            
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

def start_case_opening(user_id: int, case_type: str, message_id: int) -> CaseSession:
    """Начинает сессию открытия кейса"""
    session = CaseSession(user_id, case_type, message_id)
    active_case_sessions[f"{user_id}:{message_id}"] = session
    return session

def get_case_session(user_id: int, message_id: int) -> Optional[CaseSession]:
    """Получает активную сессию"""
    return active_case_sessions.get(f"{user_id}:{message_id}")

def close_case_session(user_id: int, message_id: int):
    """Закрывает сессию"""
    key = f"{user_id}:{message_id}"
    if key in active_case_sessions:
        del active_case_sessions[key]

def give_reward_to_user(user_id: int, reward: dict):
    """Выдает награду пользователю согласно новой конфигурации."""
    rtype = reward.get("type")
    if rtype == "empty":
        return
    if rtype and (rtype.startswith("money") or rtype.startswith('m')) and 'amount' in reward:
        amt = reward.get('amount')
        if isinstance(amt, int):
            db.add_dan(user_id, amt)
        return
    # Универсальные предметы
    if 'item_id' in reward:
        db.add_item(user_id, reward['item_id'], reward.get('count', 1))

def get_case_photo_path(case_type: str) -> str:
    """Возвращает путь к фото сундука"""
    return CASE_CONFIG[case_type]["photo"]

# === РОУТЕР ДЛЯ ОБРАБОТЧИКОВ КЕЙСОВ ===

from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message
from typing import cast

def setup_case_router() -> Router:
    """Создаёт и настраивает роутер для обработчиков кейсов"""
    router = Router(name="case_system")
    
    @router.callback_query(F.data.startswith("open_slot:"))
    async def handle_open_slot(callback: CallbackQuery):
        """Обработчик открытия слота в кейсе"""
        if not callback.from_user or not callback.data or not callback.message:
            return
        
        user_id = callback.from_user.id
        message_id = callback.message.message_id
        
        try:
            # Парсим данные колбека
            parts = callback.data.split(":")
            if len(parts) != 3:
                await callback.answer("❌ Ошибка данных")
                return
                
            case_type = parts[1]
            slot_index = int(parts[2])
            
            # Получаем активную сессию
            session = get_case_session(user_id, message_id)
            
            if session is None:
                await callback.answer("❌ Сессия не найдена")
                return
            
            # Открываем слот
            reward = session.open_slot(slot_index)
            
            # Обновляем сообщение
            try:
                msg: Message = cast(Message, callback.message)
                await msg.edit_text(
                    session.get_status_text(),
                    reply_markup=session.get_keyboard()
                )
            except Exception:
                await callback.answer("❌ Ошибка обновления")
                return
                
            await callback.answer()
            
        except Exception as e:
            print(f"Ошибка в handle_open_slot: {e}")
            await callback.answer("❌ Произошла ошибка")

    @router.callback_query(F.data == "close_case")
    async def handle_close_case(callback: CallbackQuery):
        """Обработчик закрытия кейса и возврата в инвентарь"""
        if not callback.from_user or not callback.message:
            return
        
        user_id = callback.from_user.id
        message_id = callback.message.message_id
        
        try:
            # Закрываем сессию
            close_case_session(user_id, message_id)
            
            # Импортируем функции инвентаря
            from inv_py.inventory import get_user_inventory, build_inventory_markup
            from inv_py.config_inventory import ITEMS_CONFIG, NULL_ITEM
            
            # Возвращаем в инвентарь с принудительной синхронизацией
            items, total, max_page = get_user_inventory(user_id, page=1, force_sync=True)
            
            # Подготавливаем данные для рендера с поддержкой животных
            grid_items = []
            item_images = {}
            for item_id, count in items:
                if item_id == "empty":
                    name = "Пусто"
                    icon_path = NULL_ITEM["photo_square"]
                else:
                    # Поддержка индивидуальных животных с форматом ID вида 08@123
                    if "@" in item_id:
                        base_id, owned_id = item_id.split("@", 1)
                    else:
                        base_id, owned_id = item_id, None
                    cfg = ITEMS_CONFIG.get(base_id)
                    if not cfg:
                        name = "Неизвестно"
                        icon_path = NULL_ITEM["photo_square"]
                    else:
                        name = cfg["name"] if not owned_id else f"{cfg['name']}"
                        icon_path = cfg["photo_square"]
                grid_items.append((item_id, count, name))
                item_images[item_id] = icon_path
            
            try:
                # Используем кешированное изображение
                import sys
                import os
                main_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                if main_dir not in sys.path:
                    sys.path.insert(0, main_dir)
                from main import get_cached_image
                
                out_path = get_cached_image(grid_items, item_images)
                kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
                
                media = InputMediaPhoto(
                    media=FSInputFile(str(out_path)),
                    caption=f"🎒 Ваш инвентарь\nВсего предметов: {total}"
                )
                msg: Message = cast(Message, callback.message)
                await msg.edit_media(media=media, reply_markup=kb)
                
            except Exception as e:
                print(f"Ошибка при отправке инвентаря: {e}")
                msg: Message = cast(Message, callback.message)
                await msg.edit_text(
                    f"🎒 Ваш инвентарь\nВсего предметов: {total}\n\n❌ Ошибка загрузки изображения",
                    reply_markup=build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
                )
            
            await callback.answer("✅ Возвращение в инвентарь")
            
        except Exception as e:
            print(f"Ошибка в handle_close_case: {e}")
            await callback.answer("❌ Произошла ошибка")
    
    return router
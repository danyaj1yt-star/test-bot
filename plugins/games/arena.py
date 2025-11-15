"""
🏟️ АРЕНА - PvP система с рейтингом и тактическими боями
Будущее: NFT собаки как персонажи
"""

import random
import time
import asyncio
from typing import Dict, Optional, Tuple, List
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
import arena_database as arena_db

# Глобальные переменные для bot и dp - будут установлены через register_handlers
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

# Импорт функций для красивых имен (будет работать после инициализации main.py)
def get_display_name_safe(user_id: int, username: Optional[str] = None) -> str:
    """Безопасная версия get_display_name с fallback"""
    try:
        # Попытка использовать функцию из main.py если она доступна
        import main
        return main.get_display_name(user_id, username)
    except:
        # Fallback если main.py недоступен
        if username and 3 <= len(username) <= 15:
            return username
        return f"Игрок №{abs(user_id) % 1000}"

def format_clickable_name_safe(user_id: int, display_name: Optional[str] = None) -> str:
    """Безопасная версия format_clickable_name с fallback"""
    try:
        # Попытка использовать функцию из main.py если она доступна
        import main
        return main.format_clickable_name(user_id, display_name)
    except:
        # Fallback без кликабельности
        if not display_name:
            display_name = get_display_name_safe(user_id, None)
        return display_name

# Активные арены и поиски
active_arenas: Dict[str, 'ArenaGame'] = {}
arena_queue: List[Dict] = []  # Очередь поиска игры
arena_search_timeouts: Dict[int, float] = {}  # Таймауты поиска для ботов

# Конфигурация арены
ARENA_CONFIG = {
    'START_RATING': 200,
    'SEARCH_RANGE': 200,  # ±200 PTS первую 1 минуту
    'EXPANDED_SEARCH_TIME': 60,  # 1 минута - после этого ищем любого
    'SEARCH_TIMEOUT': 3600,  # 1 час общий тайм-аут
    'GAME_DURATION': 300,  # 5 минут на бой (было 600 - 10 минут)
    'TURN_TIMEOUT': 45,  # 45 секунд на ход
    
    # Базовые характеристики
    'BASE_HP': 100,
    'BASE_DAMAGE': (15, 25),  # Максимальный урон 25 (было 30)
    'HEAL_AMOUNT': (10, 20),  # Лечение от 10 до 20 HP
    'FIRST_BLOCK_REDUCTION': 75,  # % блокированного урона при первой защите
    'SECOND_BLOCK_REDUCTION': 50,  # % блокированного урона при повторной защите
    
    # Критические удары и промахи
    'CRIT_CHANCE': 8,  # Уменьшено с 15% до 8% - каждый 12-13 удар
    'CRIT_MULTIPLIER': 1.5,
    'MISS_CHANCE': 10,
    
    # PTS система
    'WIN_PTS_BASE': 20,
    'WIN_STREAK_BONUS': 2,
    'WIN_STREAK_START': 3,
}

class ArenaFighter:
    """Боец арены (в будущем - NFT собака)"""
    def __init__(self, user_id: int, username: str):
        self.user_id = user_id
        self.username = username
        self.max_hp = ARENA_CONFIG['BASE_HP']
        self.current_hp = self.max_hp
        
        # Статусные эффекты
        self.armor = 0  # Броня на следующий ход
        self.bleeding = 0  # Кровотечение (ходы)
        self.regeneration = 0  # Регенерация (ходы)
        self.stunned = False  # Оглушение
        self.defending = False  # Постоянная защита до следующего действия
        self.defend_count = 0  # Количество защит подряд (для ослабления)
        
        # Комбо система
        self.last_actions = []  # Последние 3 действия
        self.combo_ready = False
        
        # Анти-абуз система
        self.mega_attacks_used = 0  # Счетчик использованных мега ударов
        self.attack_blocked_rounds = 0  # Блокировка атак на раунды (устаревшее)
        self.actions_to_unlock_attack = 0  # Счетчик действий для разблокировки атаки
        
        # Отображение урона
        self.last_damage_taken = 0  # Урон, полученный в последнем раунде
        
    def reset_for_battle(self):
        """Сброс состояния для нового боя"""
        self.current_hp = self.max_hp
        self.armor = 0
        self.bleeding = 0
        self.regeneration = 0
        self.stunned = False
        self.defending = False
        self.defend_count = 0
        self.last_actions = []
        self.combo_ready = False
        self.last_damage_taken = 0
        self.mega_attacks_used = 0
        self.attack_blocked_rounds = 0
        self.actions_to_unlock_attack = 0
        
    def add_action(self, action: str):
        """Добавить действие в историю для комбо"""
        self.last_actions.append(action)
        if len(self.last_actions) > 3:
            self.last_actions.pop(0)
        
        # Проверка комбо (3 одинаковых действия подряд, только атака и лечение)
        if len(self.last_actions) == 3 and all(a == action for a in self.last_actions):
            if action in ["attack", "heal"]:  # Только атака и лечение могут активировать комбо
                self.combo_ready = action
            
    def apply_status_effects(self) -> str:
        """Применить статусные эффекты в начале хода"""
        effects = []
        
        # Блокировка атак (новая система - через действия)
        if self.actions_to_unlock_attack > 0:
            effects.append(f"🚫 Атаки заблокированы: нужно {self.actions_to_unlock_attack} действий")
        
        # Старая система блокировки (для совместимости)
        if self.attack_blocked_rounds > 0:
            effects.append(f"🚫 Атаки заблокированы: {self.attack_blocked_rounds} ход(ов)")
            self.attack_blocked_rounds -= 1
        
        # Кровотечение
        if self.bleeding > 0:
            damage = 3
            self.current_hp = max(0, self.current_hp - damage)
            self.last_damage_taken += damage  # Добавляем урон от кровотечения
            effects.append(f"🩸 Кровотечение: -{damage} HP")
            self.bleeding -= 1
            
        # Регенерация
        if self.regeneration > 0:
            heal = 5
            self.current_hp = min(self.max_hp, self.current_hp + heal)
            effects.append(f"💚 Регенерация: +{heal} HP")
            self.regeneration -= 1
            
        return " | ".join(effects) if effects else ""
        
    def get_hp_bar(self) -> str:
        """Визуальная полоска HP"""
        hp_percent = self.current_hp / self.max_hp
        
        # Визуальная полоска (10 сегментов)
        filled_segments = int(hp_percent * 10)
        empty_segments = 10 - filled_segments
        bar = "█" * filled_segments + "░" * empty_segments
        
        if hp_percent > 0.75:
            return f"❤️{self.current_hp}/{self.max_hp} {bar}"
        elif hp_percent > 0.5:
            return f"🧡{self.current_hp}/{self.max_hp} {bar}"
        elif hp_percent > 0.25:
            return f"💛{self.current_hp}/{self.max_hp} {bar}"
        else:
            return f"💔{self.current_hp}/{self.max_hp} {bar}"
            
    def get_status_icons(self) -> str:
        """Иконки статусных эффектов"""
        effects = []
        if self.armor > 0:
            effects.append(f"🛡️Броня {self.armor}")
        if self.defending:
            if self.defend_count == 1:
                effects.append("🛡️Защита -75%")
            else:
                effects.append("🛡️Защита -50%")
        if self.bleeding > 0:
            effects.append(f"🩸Кровь {self.bleeding}х")
        if self.regeneration > 0:
            effects.append(f"💚Реген {self.regeneration}х")
        if self.stunned:
            effects.append("😵Оглушен")
        return " | ".join(effects)

class ArenaGame:
    """Игра в арене"""
    def __init__(self, player1_data: Dict, player2_data: Dict, bet: int = 0):
        # Используем короткий timestamp для экономии места в callback_data
        short_time = int(time.time()) % 100000  # Последние 5 цифр timestamp
        self.game_id = f"{player1_data['user_id']}_{player2_data['user_id']}_{short_time}"
        
        self.fighter1 = ArenaFighter(player1_data['user_id'], player1_data['username'])
        self.fighter2 = ArenaFighter(player2_data['user_id'], player2_data['username'])
        
        self.bet = bet
        self.start_time = time.time()
        self.current_round = 1
        self.max_rounds = 60  # Увеличено с 15 до 60 раундов (5 минут / 5 сек за раунд)
        
        # Состояние игры
        self.is_active = True
        self.waiting_for = {self.fighter1.user_id: None, self.fighter2.user_id: None}  # Выбранные действия
        self.last_result = ""
        
        # Сообщения для обновления
        self.message_ids = {}
        
        # Информация о чате для результата
        self.source_chat_id = None
        self.source_message_id = None
        
    def is_expired(self) -> bool:
        """Проверка истечения времени игры"""
        return time.time() - self.start_time > ARENA_CONFIG['GAME_DURATION']
        
    def both_players_ready(self) -> bool:
        """Проверка готовности обоих игроков"""
        return all(action is not None for action in self.waiting_for.values())
        
    def get_fighter(self, user_id: int) -> Optional[ArenaFighter]:
        """Получить бойца по ID"""
        if self.fighter1.user_id == user_id:
            return self.fighter1
        elif self.fighter2.user_id == user_id:
            return self.fighter2
        return None
        
    def get_opponent(self, user_id: int) -> Optional[ArenaFighter]:
        """Получить противника по ID"""
        if self.fighter1.user_id == user_id:
            return self.fighter2
        elif self.fighter2.user_id == user_id:
            return self.fighter1
        return None
        
    def process_round(self) -> Tuple[str, bool]:
        """Обработать раунд боя"""
        if not self.both_players_ready():
            return "Ошибка: не все игроки готовы", False
            
        action1 = self.waiting_for[self.fighter1.user_id]
        action2 = self.waiting_for[self.fighter2.user_id]
        
        # Применяем статусные эффекты
        status1 = self.fighter1.apply_status_effects()
        status2 = self.fighter2.apply_status_effects()
        
        # Обрабатываем действия
        result = self._process_actions(action1, action2)
        
        # Добавляем статусные эффекты в результат
        if status1 or status2:
            status_text = f"\n\n🔮 Эффекты: {status1}" + (f" | {status2}" if status2 else "")
            result += status_text
            
        # Проверяем окончание игры
        game_over = self._check_game_over()
        
        # Проверяем лимит раундов
        if self.current_round >= self.max_rounds:
            game_over = True
            result += f"\n⏰ Достигнут лимит раундов ({self.max_rounds})! Бой завершен."
        
        # Сброс ходов
        self.waiting_for = {self.fighter1.user_id: None, self.fighter2.user_id: None}
        self.current_round += 1
        self.last_result = result
        
        return result, game_over
        
    def _process_actions(self, action1: str, action2: str) -> str:
        """Обработка взаимодействия действий"""
        # Сбрасываем счетчик урона перед новым раундом
        self.fighter1.last_damage_taken = 0
        self.fighter2.last_damage_taken = 0
        
        # Получаем красивые имена для отображения
        name1 = get_display_name_safe(self.fighter1.user_id, self.fighter1.username)
        name2 = get_display_name_safe(self.fighter2.user_id, self.fighter2.username)
        
        # Управление защитой и счетчиком защит
        if action1 == "defend":
            self.fighter1.defending = True
            self.fighter1.defend_count += 1
        else:
            self.fighter1.defending = False
            self.fighter1.defend_count = 0
        
        if action2 == "defend":
            self.fighter2.defending = True
            self.fighter2.defend_count += 1
        else:
            self.fighter2.defending = False
            self.fighter2.defend_count = 0
            
        # Добавляем действия в историю для комбо
        self.fighter1.add_action(action1)
        self.fighter2.add_action(action2)
        
        results = []
        
        # Обработка комбо
        combo1_text = self._check_combo(self.fighter1, action1)
        combo2_text = self._check_combo(self.fighter2, action2)
        
        if combo1_text:
            results.append(combo1_text)
        if combo2_text:
            results.append(combo2_text)
        
        # Основная логика взаимодействий
        if action1 == "attack" and action2 == "attack":
            # Оба атакуют
            combo1_active = combo1_text != ""
            combo2_active = combo2_text != ""
            damage1 = self._calculate_damage(self.fighter1, self.fighter2, combo_active=combo1_active)
            damage2 = self._calculate_damage(self.fighter2, self.fighter1, combo_active=combo2_active)
            results.append(f"⚔️ {name1} атакует за {damage1} урона!")
            results.append(f"⚔️ {name2} атакует за {damage2} урона!")
            
        elif action1 == "attack" and action2 == "defend":
            # Первый атакует, второй защищается
            combo1_active = combo1_text != ""
            damage = self._calculate_damage(self.fighter1, self.fighter2, combo_active=combo1_active)
            defense_level = "первый раз" if self.fighter2.defend_count == 1 else "повторно"
            results.append(f"⚔️ {name1} атакует!")
            results.append(f"🛡️ {name2} защищается ({defense_level}) и получает {damage} урона!")
            
        elif action1 == "defend" and action2 == "attack":
            # Первый защищается, второй атакует
            combo2_active = combo2_text != ""
            damage = self._calculate_damage(self.fighter2, self.fighter1, combo_active=combo2_active)
            defense_level = "первый раз" if self.fighter1.defend_count == 1 else "повторно"
            results.append(f"🛡️ {name1} защищается ({defense_level})!")
            results.append(f"⚔️ {name2} атакует, но наносит только {damage} урона!")
            
        elif action1 == "attack" and action2 == "heal":
            # Первый атакует, второй лечится
            combo1_active = combo1_text != ""
            combo2_active = combo2_text != ""
            
            # Сначала лечим
            heal = self._calculate_heal(self.fighter2)
            
            # Потом применяем урон
            damage = self._calculate_damage(self.fighter1, self.fighter2, combo_active=combo1_active)
            
            results.append(f"⚔️ {name1} атакует за {damage} урона!")
            results.append(f"💚 {name2} лечится на {heal} HP, но получает полный урон!")
            
        elif action1 == "heal" and action2 == "attack":
            # Первый лечится, второй атакует
            combo1_active = combo1_text != ""
            combo2_active = combo2_text != ""
            
            # Сначала лечим
            heal = self._calculate_heal(self.fighter1)
            
            # Потом применяем урон
            damage = self._calculate_damage(self.fighter2, self.fighter1, combo_active=combo2_active)
            
            results.append(f"💚 {name1} лечится на {heal} HP!")
            results.append(f"⚔️ {name2} атакует за {damage} урона - плохая идея лечиться под атакой!")
            
        elif action1 == "defend" and action2 == "defend":
            # Оба защищаются
            results.append("🛡️ Оба игрока осторожничают и укрепляют оборону!")
            
        elif action1 == "heal" and action2 == "heal":
            # Оба лечатся
            heal1 = self._calculate_heal(self.fighter1)
            heal2 = self._calculate_heal(self.fighter2)
            results.append(f"💚 Оба бойца восстанавливают силы!")
            results.append(f"💚 {name1}: +{heal1} HP, {name2}: +{heal2} HP")
            
        elif action1 == "defend" and action2 == "heal":
            # Первый защищается, второй лечится
            heal = self._calculate_heal(self.fighter2)
            self.fighter1.armor = 20  # Больше брони за бездействие
            results.append(f"🛡️ {name1} готовится к бою!")
            results.append(f"💚 {name2} спокойно лечится на {heal} HP!")
            
        elif action1 == "heal" and action2 == "defend":
            # Первый лечится, второй защищается
            heal = self._calculate_heal(self.fighter1)
            self.fighter2.armor = 20  # Больше брони за бездействие
            results.append(f"💚 {name1} спокойно лечится на {heal} HP!")
            results.append(f"🛡️ {name2} готовится к бою!")
            
        # Обработка разблокировки атак (уменьшаем счетчик при ЛЮБОМ действии)
        if self.fighter1.actions_to_unlock_attack > 0:
            self.fighter1.actions_to_unlock_attack -= 1
            if self.fighter1.actions_to_unlock_attack == 0:
                self.fighter1.mega_attacks_used = 0  # Сбрасываем счетчик мега ударов
                results.append(f"✅ {name1} может снова атаковать!")
        
        if self.fighter2.actions_to_unlock_attack > 0:
            self.fighter2.actions_to_unlock_attack -= 1
            if self.fighter2.actions_to_unlock_attack == 0:
                self.fighter2.mega_attacks_used = 0  # Сбрасываем счетчик мега ударов
                results.append(f"✅ {name2} может снова атаковать!")
            
        return "\n".join(results)
        
    def _check_combo(self, fighter: ArenaFighter, action: str) -> str:
        """Проверка и активация комбо"""
        # Получаем красивое имя для отображения
        fighter_name = get_display_name_safe(fighter.user_id, fighter.username)
        
        # БЕРСЕРК активируется автоматически при третьем ударе подряд
        if fighter.combo_ready == "attack" and action == "attack":
            opponent = self.get_opponent(fighter.user_id)
            if opponent:
                opponent.bleeding = 3
            fighter.combo_ready = False
            # Увеличиваем счетчик мега ударов
            fighter.mega_attacks_used += 1
            
            # Проверяем, достиг ли лимит 3 мега удара
            if fighter.mega_attacks_used >= 3:
                fighter.attack_blocked_rounds = 2  # Блокируем атаки на 2 раунда
                return f"💥 {fighter_name} входит в БЕРСЕРК! Противник истекает кровью!\n🚫 Атаки заблокированы на 2 раунда!"
            
            return f"💥 {fighter_name} входит в БЕРСЕРК! Противник истекает кровью!"
            
        # МОЩ.ИСЦЕЛЕНИЕ активируется только при выборе лечения с готовым комбо
        elif fighter.combo_ready == "heal" and action == "heal":
            fighter.regeneration = 3  # Регенерация на 3 хода
            fighter.combo_ready = False
            return f"✨ {fighter_name} использует МОЩНОЕ ИСЦЕЛЕНИЕ (усиленное лечение + регенерация)!"
                
        return ""
        
    def _calculate_damage(self, attacker: ArenaFighter, defender: ArenaFighter, defending: bool = False, combo_active: bool = False) -> int:
        """Расчет урона с учетом всех модификаторов"""
        base_damage = random.randint(*ARENA_CONFIG['BASE_DAMAGE'])
        
        # Проверка промаха
        if random.randint(1, 100) <= ARENA_CONFIG['MISS_CHANCE']:
            return 0  # Промах
            
        # Усиление урона для комбо-атаки (БЕРСЕРК)
        if combo_active:
            base_damage = random.randint(30, 40)  # Фиксированный урон 30-40 для берсерка
            
        # Проверка критического удара
        if random.randint(1, 100) <= ARENA_CONFIG['CRIT_CHANCE']:
            base_damage = int(base_damage * ARENA_CONFIG['CRIT_MULTIPLIER'])
            # Критический удар может вызвать кровотечение
            if random.randint(1, 100) <= 30:  # 30% шанс
                defender.bleeding = 2
                
        # Применение брони
        if defender.armor > 0:
            blocked = min(defender.armor, base_damage // 2)
            base_damage -= blocked
            defender.armor = max(0, defender.armor - blocked)
            
        # Дополнительное снижение при защите
        if defending or defender.defending:
            if defender.defend_count == 1:
                # Первая защита - 75% блокирование
                block_percent = ARENA_CONFIG['FIRST_BLOCK_REDUCTION']
            else:
                # Повторная защита - 50% блокирование
                block_percent = ARENA_CONFIG['SECOND_BLOCK_REDUCTION']
            base_damage = int(base_damage * (100 - block_percent) / 100)
            
        # Применение урона
        final_damage = max(1, base_damage)  # Минимум 1 урон
        defender.current_hp = max(0, defender.current_hp - final_damage)
        
        # Отслеживаем полученный урон для отображения
        defender.last_damage_taken = final_damage
        
        # Увеличиваем счетчик мега ударов для любой атаки
        attacker.mega_attacks_used += 1
        
        # Проверяем, достиг ли лимит 3 мега удара (блокировка до 2 действий)
        if attacker.mega_attacks_used >= 3:
            attacker.actions_to_unlock_attack = 2  # Нужно 2 действия для разблокировки
        
        return final_damage
        
    def _calculate_heal(self, fighter: ArenaFighter) -> int:
        """Расчет лечения"""
        heal_amount = random.randint(*ARENA_CONFIG['HEAL_AMOUNT'])
        
        # Комбо значительно увеличивает лечение (25-35 HP вместо 10-20)
        if fighter.combo_ready == "heal":
            heal_amount = random.randint(25, 35)
            
        old_hp = fighter.current_hp
        fighter.current_hp = min(fighter.max_hp, fighter.current_hp + heal_amount)
        actual_heal = fighter.current_hp - old_hp
        
        return actual_heal
        
    def _check_game_over(self) -> bool:
        """Проверка окончания игры"""
        # Кто-то умер
        if self.fighter1.current_hp <= 0 or self.fighter2.current_hp <= 0:
            return True
            
        # Время истекло
        if self.is_expired():
            return True
            
        return False
        
    def get_winner(self) -> Optional[ArenaFighter]:
        """Определить победителя"""
        if self.fighter1.current_hp <= 0:
            return self.fighter2
        elif self.fighter2.current_hp <= 0:
            return self.fighter1
        elif self.is_expired():
            # По времени - у кого больше HP
            if self.fighter1.current_hp > self.fighter2.current_hp:
                return self.fighter1
            elif self.fighter2.current_hp > self.fighter1.current_hp:
                return self.fighter2
            else:
                return None  # Ничья
        return None
        
    def get_arena_display(self, for_user_id: int) -> str:
        """Получить отображение арены для игрока"""
        time_left = max(0, ARENA_CONFIG['GAME_DURATION'] - (time.time() - self.start_time))
        minutes = int(time_left // 60)
        seconds = int(time_left % 60)
        
        text = f"🏟️ <b>Арена Раунд {self.current_round}</b> ⏱️ {minutes:02d}:{seconds:02d}\n\n"
        
        # Красивые кликабельные имена
        name1 = format_clickable_name_safe(self.fighter1.user_id, get_display_name_safe(self.fighter1.user_id, self.fighter1.username))
        name2 = format_clickable_name_safe(self.fighter2.user_id, get_display_name_safe(self.fighter2.user_id, self.fighter2.username))
        
        # Статус бойцов - основная информация
        text += f"👤 {name1}: {self.fighter1.get_hp_bar()}"
        if self.fighter1.last_damage_taken > 0:
            text += f" <b>-{self.fighter1.last_damage_taken} hp</b>"
        else:
            text += " -0 hp"
        text += "\n"
        
        text += f"👤 {name2}: {self.fighter2.get_hp_bar()}"
        if self.fighter2.last_damage_taken > 0:
            text += f" <b>-{self.fighter2.last_damage_taken} hp</b>"
        else:
            text += " -0 hp"
        text += "\n"
        
        # Эффекты и статусы (если есть)
        effects_line = ""
        if self.fighter1.get_status_icons():
            effects_line += f"🔸 {name1}: {self.fighter1.get_status_icons()}"
        if self.fighter2.get_status_icons():
            if effects_line:
                effects_line += "\n"
            effects_line += f"🔸 {name2}: {self.fighter2.get_status_icons()}"
        
        if effects_line:
            text += f"\n{effects_line}\n"
        text += "\n"
        
        # Последний результат если есть
        if self.last_result:
            text += f"📋 <b>Последний раунд:</b>\n{self.last_result}\n\n"
            
        # Статус игры внизу
        opponent = self.get_opponent(for_user_id)
        
        if opponent is None:
            text += "❌ Ошибка: противник не найден"
            return text
        
        player_action = self.waiting_for[for_user_id] 
        opponent_action = self.waiting_for[opponent.user_id]
        
        if player_action is not None:
            # Игрок уже выбрал действие
            action_names = {"attack": "Атака", "defend": "Защита", "heal": "Лечение"}
            chosen_action = action_names.get(player_action, "Действие")
            
            if opponent_action is not None:
                # Оба выбрали - показываем выборы
                action_icons = {"attack": "⚔️", "defend": "🛡️", "heal": "💚"}
                action1 = self.waiting_for[self.fighter1.user_id]
                action2 = self.waiting_for[self.fighter2.user_id]
                text += f"🎯 <b>Результат раунда:</b>\n"
                text += f"{action_icons.get(action1 or 'attack', '❓')} {name1}: {(action1 or 'нет').upper()}\n"
                text += f"{action_icons.get(action2 or 'attack', '❓')} {name2}: {(action2 or 'нет').upper()}\n"
            else:
                # Только игрок выбрал
                text += f"✅ Вы выбрали: {chosen_action}, ожидаем"
        else:
            # Игрок еще не выбрал
            if opponent_action is not None:
                text += "⏳ Противник выбрал, ваш ход!"
            else:
                text += "⏳ Ожидаем противника"
            
            # Показываем информацию о блокировке атаки
            player_fighter = self.get_fighter(for_user_id)
            if player_fighter and player_fighter.actions_to_unlock_attack > 0:
                text += f"\n\n🚫 <b>Атака заблокирована: нужно {player_fighter.actions_to_unlock_attack} действий</b>"
            elif player_fighter and player_fighter.attack_blocked_rounds > 0:
                text += f"\n\n🚫 <b>Атака заблокирована на {player_fighter.attack_blocked_rounds} раунд(ов)</b>"
            elif player_fighter and player_fighter.mega_attacks_used >= 3:
                text += "\n\n🚫 <b>Атака заблокирована</b> (использовано 3 мега удара)"
            elif player_fighter and player_fighter.mega_attacks_used > 0:
                text += f"\n\n⚠️ Мега ударов использовано: {player_fighter.mega_attacks_used}/3"
            
        return text
        
    def get_keyboard(self, user_id: int) -> InlineKeyboardMarkup:
        """Получить клавиатуру действий"""
        # Если игрок уже выбрал действие - кнопки пропадают
        if self.waiting_for[user_id] is not None:
            return InlineKeyboardMarkup(inline_keyboard=[])
            
        fighter = self.get_fighter(user_id)
        buttons = []
        
        # Основные действия (с анти-абуз проверкой)
        action_row = []
        
        # Кнопка атаки доступна только если использовано менее 3 мега ударов И нет блокировки
        if fighter and fighter.mega_attacks_used < 3 and fighter.attack_blocked_rounds == 0 and fighter.actions_to_unlock_attack == 0:
            action_row.append(InlineKeyboardButton(text="⚔️ Атака", callback_data=f"arena_action:{self.game_id}:attack"))
        
        # Защита и лечение всегда доступны
        action_row.extend([
            InlineKeyboardButton(text="🛡️ Защита", callback_data=f"arena_action:{self.game_id}:defend"),
            InlineKeyboardButton(text="💚 Лечение", callback_data=f"arena_action:{self.game_id}:heal")
        ])
        
        buttons.append(action_row)
        
        # Показать комбо, если доступно (после 3 одинаковых действий)
        if fighter and fighter.combo_ready and fighter.combo_ready != False:
            combo_action = str(fighter.combo_ready)
            combo_names = {"attack": "БЕРСЕРК", "heal": "МОЩ.ИСЦЕЛЕНИЕ"}
            combo_text = f"💥 {combo_names.get(combo_action, 'КОМБО')}"
            buttons.append([InlineKeyboardButton(text=combo_text, callback_data="arena_combo_info")])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# Функции для работы с базой данных
def init_arena_tables():
    """Инициализация таблиц арены"""
    arena_db.init_arena_database()
    
def get_arena_rating(user_id: int, username: Optional[str] = None) -> Dict:
    """Получить рейтинг игрока"""
    return arena_db.get_player_rating(user_id, username)

def get_player_rank(user_id: int) -> int:
    """Получить ранг игрока в общей таблице"""
    return arena_db.get_player_rank(user_id)

def update_arena_rating(user_id: int, rating_change: int, is_win: bool, 
                       damage_dealt: int = 0, damage_taken: int = 0, healing: int = 0, username: Optional[str] = None):
    """Обновить рейтинг игрока"""
    return arena_db.update_player_rating(user_id, username or f"Player_{user_id}", rating_change, is_win, 
                                        damage_dealt, damage_taken, healing)

def calculate_pts_change(winner_rating: int, loser_rating: int, 
                        winner_hp_percent: float, loser_hp_percent: float,
                        winner_streak: int) -> Tuple[int, int]:
    """Расчет изменения PTS"""
    # Базовые очки за победу/поражение
    if winner_hp_percent > 0.5:
        win_pts = 20
    elif winner_hp_percent > 0.25:
        win_pts = 15
    else:
        win_pts = 10
        
    if loser_hp_percent > 0.5:
        lose_pts = -20
    elif loser_hp_percent > 0.25:
        lose_pts = -15
    else:
        lose_pts = -10
    
    # Бонус за серию побед
    if winner_streak >= ARENA_CONFIG['WIN_STREAK_START']:
        streak_bonus = (winner_streak - ARENA_CONFIG['WIN_STREAK_START'] + 1) * ARENA_CONFIG['WIN_STREAK_BONUS']
        win_pts += streak_bonus
    
    return win_pts, lose_pts

def get_arena_leaderboard(limit: int = 10) -> List[Dict]:
    """Получить таблицу лидеров"""
    return arena_db.get_top_players(limit)

# Функции поиска игры
def add_to_arena_queue(user_id: int, username: str, bet: int = 0) -> bool:
    """Добавить игрока в очередь поиска"""
    # Проверяем, не в очереди ли уже
    for player in arena_queue:
        if player['user_id'] == user_id:
            return False
    
    rating = get_arena_rating(user_id)
    
    arena_queue.append({
        'user_id': user_id,
        'username': username,
        'rating': rating['rating'],
        'bet': bet,
        'search_start': time.time()
    })
    
    arena_search_timeouts[user_id] = time.time()
    return True

def find_arena_opponent(user_id: int) -> Optional[Dict]:
    """Найти противника для игрока"""
    player = None
    player_index = -1
    
    for i, p in enumerate(arena_queue):
        if p['user_id'] == user_id:
            player = p
            player_index = i
            break
    
    if not player:
        return None
    
    # Ищем подходящего противника
    rating_range = ARENA_CONFIG['SEARCH_RANGE']
    search_time = time.time() - player['search_start']
    
    # Расширяем диапазон поиска со временем
    if search_time > ARENA_CONFIG['EXPANDED_SEARCH_TIME']:  # 1 минута - ищем любого противника
        rating_range = 9999  # Любой противник в игре
    
    best_opponent = None
    best_opponent_index = -1
    min_rating_diff = float('inf')
    
    for i, opponent in enumerate(arena_queue):
        if (opponent['user_id'] != user_id and 
            opponent['bet'] == player['bet'] and
            abs(opponent['rating'] - player['rating']) <= rating_range):
            
            rating_diff = abs(opponent['rating'] - player['rating'])
            if rating_diff < min_rating_diff:
                min_rating_diff = rating_diff
                best_opponent = opponent
                best_opponent_index = i
    
    if best_opponent:
        # Удаляем обоих игроков из очереди
        arena_queue.pop(max(player_index, best_opponent_index))
        arena_queue.pop(min(player_index, best_opponent_index))
        
        # Удаляем таймауты
        arena_search_timeouts.pop(user_id, None)
        arena_search_timeouts.pop(best_opponent['user_id'], None)
        
        return best_opponent
    
    return None

def remove_from_arena_queue(user_id: int) -> bool:
    """Удалить игрока из очереди"""
    for i, player in enumerate(arena_queue):
        if player['user_id'] == user_id:
            arena_queue.pop(i)
            arena_search_timeouts.pop(user_id, None)
            return True
    return False

def check_arena_timeouts() -> List[int]:
    """Проверить таймауты поиска и создать игры с ботами"""
    timed_out_players = []
    current_time = time.time()
    
    for user_id, start_time in list(arena_search_timeouts.items()):
        if current_time - start_time >= ARENA_CONFIG['SEARCH_TIMEOUT']:
            timed_out_players.append(user_id)
            arena_search_timeouts.pop(user_id, None)
    
    return timed_out_players

def check_expired_games() -> List[str]:
    """Проверить истекшие игры и вернуть их ID для завершения"""
    expired_games = []
    
    for game_id, game in list(active_arenas.items()):
        if game.is_active and game.is_expired():
            expired_games.append(game_id)
    
    return expired_games

def get_search_failed_message() -> str:
    """Сообщение когда поиск не удался"""
    return (
        "⏰ <b>ПОИСК НЕ УДАЛСЯ</b>\n\n"
        "🔍 К сожалению, за час поиска не удалось найти подходящего противника.\n\n"
        "💡 <b>Попробуйте:</b>\n"
        "• Повторить поиск в другое время\n"
        "• Сыграть с ботом для разминки\n"
        "• Проверить свой рейтинг арены\n\n"
        "🎯 <i>Поиск будет более успешным в часы пик!</i>"
    )

# Основные функции геймплея
def create_arena_game(player1_data: Dict, player2_data: Dict, bet: int = 0) -> str:
    """Создать новую игру в арене"""
    game = ArenaGame(player1_data, player2_data, bet)
    active_arenas[game.game_id] = game
    return game.game_id

def get_arena_game(game_id: str) -> Optional[ArenaGame]:
    """Получить игру по ID"""
    return active_arenas.get(game_id)

def process_arena_action(game_id: str, user_id: int, action: str) -> Tuple[bool, str]:
    """Обработать действие игрока"""
    game = get_arena_game(game_id)
    if not game or not game.is_active:
        return False, "Игра не найдена или завершена"
    
    if user_id not in game.waiting_for:
        return False, "Вы не участвуете в этой игре"
    
    if game.waiting_for[user_id] is not None:
        return False, "Вы уже выбрали действие в этом раунде"
    
    game.waiting_for[user_id] = action
    
    # НЕ обрабатываем раунд здесь - оставляем это для arena_action_callback
    return True, "Действие выбрано"

def end_arena_game(game_id: str) -> Optional[Dict]:
    """Завершить игру и подсчитать результаты"""
    game = active_arenas.pop(game_id, None)
    if not game:
        return None
    
    winner = game.get_winner()
    loser = None
    
    if winner:
        loser = game.get_opponent(winner.user_id)
    
    result = {
        'winner': winner,
        'loser': loser,
        'game': game,
        'is_draw': winner is None
    }
    
    # Обновляем рейтинги
    if not result['is_draw'] and winner and loser:
        # Определяем, есть ли бот в игре (отрицательный user_id)
        is_bot_game = winner.user_id < 0 or loser.user_id < 0
        
        if is_bot_game:
            # Фиксированные очки для игры с ботом
            if winner.user_id > 0:  # Человек победил бота
                win_pts = 10  # Награда за победу над ботом
                lose_pts = 0  # Бот не теряет очки
                update_arena_rating(winner.user_id, win_pts, True)
            else:  # Бот победил человека
                win_pts = 0  # Бот не получает очки
                lose_pts = -15  # Увеличено с -10 до -15 PTS за поражение
                update_arena_rating(loser.user_id, lose_pts, False)
                
            result['winner_pts'] = win_pts if winner.user_id > 0 else 0
            result['loser_pts'] = lose_pts if loser.user_id > 0 else 0
        else:
            # Обычная игра между людьми
            winner_rating = get_arena_rating(winner.user_id)
            loser_rating = get_arena_rating(loser.user_id)
            
            winner_hp_percent = winner.current_hp / winner.max_hp
            loser_hp_percent = loser.current_hp / loser.max_hp
            
            win_pts, lose_pts = calculate_pts_change(
                winner_rating['rating'], loser_rating['rating'],
                winner_hp_percent, loser_hp_percent,
                winner_rating['win_streak']
            )
            
            update_arena_rating(winner.user_id, win_pts, True)
            update_arena_rating(loser.user_id, lose_pts, False)
            
            result['winner_pts'] = win_pts
            result['loser_pts'] = lose_pts
    
    return result

# Еженедельный сброс рейтинга
def weekly_rating_reset():
    """Еженедельный сброс части рейтинга"""
    # Пока что пустая функция, можно реализовать позже через arena_db
    return []

# ============================================================================
# ОБРАБОТЧИКИ КОМАНД И CALLBACK'ОВ ДЛЯ АРЕНЫ
# ============================================================================

async def update_arena_interface(game, user_id):
    """Обновляет интерфейс арены для пользователя"""
    if not bot or not game or user_id not in game.message_ids:
        return False
    
    try:
        text = game.get_arena_display(user_id)
        keyboard = game.get_keyboard(user_id)
        
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=game.message_ids[user_id],
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return True
    except Exception:
        return False

def register_arena_handlers(bot_instance: Bot, dp_instance: Dispatcher):
    """Регистрирует все обработчики арены
    
    ВАЖНО: Эта функция должна быть вызвана из main.py после инициализации bot и dp
    Пример: arena.register_arena_handlers(bot, dp)
    """
    global bot, dp
    bot = bot_instance
    dp = dp_instance
    
    print("✅ Обработчики арены готовы к регистрации (вызовите из main.py)")
    # Примечание: обработчики остаются в main.py для доступа к другим функциям
    # Этот модуль предоставляет игровую логику и API для использования в main.py

# === ИИ БОТА ДЛЯ АРЕНЫ ===

async def bot_arena_ai(game_id: str, bot_user_id: int):
    """ИИ для бота в арене с быстрой реакцией"""
    try:
        print(f"🤖 bot_arena_ai запущен для игры {game_id}, бот {bot_user_id}")
        # Короткая пауза для реалистичности
        await asyncio.sleep(1)
        
        game = get_arena_game(game_id)
        if not game or not game.is_active:
            print(f"🤖 Игра {game_id} не найдена или неактивна")
            return
        
        # Если бот должен сделать ход
        if game.waiting_for.get(bot_user_id) is None:
            print(f"🤖 Бот {bot_user_id} делает ход в игре {game_id}")
            human_player = game.get_opponent(bot_user_id)
            if not human_player or human_player.user_id < 0:
                print(f"🤖 Человек не найден или некорректен")
                return
            
            # Простая логика бота
            bot_fighter = game.get_fighter(bot_user_id)
            opponent = game.get_opponent(bot_user_id)
            
            if not bot_fighter or not opponent:
                return
            
            # СУПЕР АГРЕССИВНАЯ логика выбора действия бота (70% атак!)
            can_attack = bot_fighter.mega_attacks_used < 3 and bot_fighter.attack_blocked_rounds == 0 and bot_fighter.actions_to_unlock_attack == 0
            
            # 🧠 АНАЛИЗ ПОВЕДЕНИЯ ПРОТИВНИКА: Если противник не атакует 2 раза подряд - максимальное лечение!
            opponent_last_actions = opponent.last_actions
            opponent_passive = False
            if len(opponent_last_actions) >= 2:
                # Проверяем последние 2 действия противника
                last_two = opponent_last_actions[-2:]
                opponent_passive = all(action in ["defend", "heal"] for action in last_two)
                if opponent_passive:
                    print(f"🤖 Противник пассивен (последние действия: {last_two}), бот переходит в режим СЕЙВ!")
            
            # 🎯 АБСОЛЮТНЫЙ ПРИОРИТЕТ: Добивание противника с низким HP (важнее СЕЙВ режима!)
            if opponent.current_hp < 25 and can_attack:
                action = "attack"
                print(f"🤖 Бот добивает противника (HP: {opponent.current_hp}) - приоритет над СЕЙВ режимом!")
            
            # 💊 РЕЖИМ СЕЙВ: Противник пассивен - максимальное лечение!
            elif opponent_passive and bot_fighter.current_hp < 80:  # Лечимся если не полное HP
                action = "heal"
                print(f"🤖 Бот максимально лечится (СЕЙВ режим, HP: {bot_fighter.current_hp})")
            
            # 🚫 НЕ МОЖЕМ АТАКОВАТЬ: Быстро разблокироваться
            elif not can_attack:
                if bot_fighter.current_hp < 30:  # Только при очень критичном HP лечимся
                    action = "heal"
                    print(f"🤖 Бот не может атаковать, критично лечится (HP: {bot_fighter.current_hp})")
                else:
                    action = "defend"
                    print(f"🤖 Бот не может атаковать, защищается для разблокировки")
            
            # ⚔️ ГЛАВНАЯ ЛОГИКА: 70% АТАК когда можем!
            elif can_attack:
                # При HP >= 40 - НЕ лечимся, только атакуем или защищаемся
                if bot_fighter.current_hp >= 40:
                    if random.random() < 0.7:  # 70% АТАК!
                        action = "attack"
                        print(f"🤖 Бот агрессивно атакует! (HP: {bot_fighter.current_hp}, атака {bot_fighter.mega_attacks_used + 1}/3)")
                    else:  # 30% защиты
                        action = "defend"
                        print(f"🤖 Бот защищается (30% шанс)")
                
                # При HP < 40 - может лечиться, но все еще агрессивен
                else:  # HP < 40
                    if opponent.current_hp < 30:  # Если противник слаб - добиваем несмотря на низкое HP
                        action = "attack"
                        print(f"🤖 Бот добивает слабого противника (HP бота: {bot_fighter.current_hp})")
                    elif random.random() < 0.5:  # 50% атак даже при низком HP
                        action = "attack"
                        print(f"🤖 Бот рискованно атакует при низком HP ({bot_fighter.current_hp})")
                    elif random.random() < 0.7:  # 35% лечения
                        action = "heal"
                        print(f"🤖 Бот лечится при критичном HP ({bot_fighter.current_hp})")
                    else:  # 15% защиты
                        action = "defend"
                        print(f"🤖 Бот защищается при критичном HP ({bot_fighter.current_hp})")
            
            # 🛡️ РЕЗЕРВНАЯ ЛОГИКА (на всякий случай)
            else:
                action = "attack" if can_attack else "defend"
                print(f"🤖 Бот: резервное действие - {action}")
            
            # Делаем ход
            success, result = process_arena_action(game_id, bot_user_id, action)
            
            if success:
                game = get_arena_game(game_id)
                if game:
                    # Обновляем интерфейс для человека
                    await update_arena_interface(game, human_player.user_id)
                    
                    # Если оба выбрали - мгновенно обрабатываем раунд
                    if game.both_players_ready():
                        await asyncio.sleep(1)  # Короткая пауза чтобы показать выборы
                        
                        round_result, game_ended = game.process_round()
                        if game_ended:
                            game.is_active = False
                            result_data = end_arena_game(game_id)
                            if result_data:
                                await send_bot_arena_result(result_data)
                        else:
                            # Обновляем интерфейс после раунда
                            await update_arena_interface(game, human_player.user_id)
    except Exception as e:
        print(f"Ошибка в bot_arena_ai: {e}")

async def send_bot_arena_result(result_data):
    """Отправить результат игры с ботом"""
    if not bot:
        print("❌ Bot не инициализирован")
        return
        
    game = result_data['game']
    
    # Находим игрока-человека
    human_player = None
    bot_player = None
    
    for fighter in [game.fighter1, game.fighter2]:
        if fighter.user_id > 0:
            human_player = fighter
        else:
            bot_player = fighter
    
    if not human_player:
        return
    
    if result_data['is_draw']:
        text = f"🤝 <b>НИЧЬЯ С БОТОМ!</b>\n\n"
        text += f"⏰ Время истекло, но вы достойно сражались!\n"
        text += f"🏆 Рейтинг не изменился"
    elif result_data['winner'] == human_player:
        pts = result_data['winner_pts']
        
        # Отслеживаем победу для заданий (бот - не реальный игрок)
        try:
            import main
            if hasattr(main, '_tasks'):
                main._tasks.record_arena_win(human_player.user_id, vs_real=False)
        except Exception as e:
            print(f"❌ Ошибка записи победы в арене для {human_player.user_id}: {e}")
        
        text = f"🏆 <b>ПОБЕДА НАД БОТОМ!</b>\n\n"
        text += f"🤖 You defeated {bot_player.username}!\n"
        text += f"🏆 <b>Рейтинг:</b> +{pts} PTS\n"
        text += f"💪 Отличная работа!"
    else:
        pts = result_data['loser_pts']
        text = f"🤖 <b>БОТ ПОБЕДИЛ</b>\n\n"
        text += f"💔 {bot_player.username} оказался сильнее\n"
        text += f"📉 <b>Рейтинг:</b> {pts} PTS\n"
        text += f"🔄 Тренируйтесь и возвращайтесь!"
    
    # Кнопка возврата в меню арены
    arena_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню арены", callback_data="arena_back_to_menu")]
    ])
    
    try:
        await bot.send_message(
            chat_id=human_player.user_id,
            text=text,
            reply_markup=arena_keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка отправки результата игры с ботом: {e}")

# Инициализация при импорте
init_arena_tables()
import random
import os
import logging
from aiogram import types
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database as db  # твоя работа с базой

# Настроим логгер
logger = logging.getLogger("battle")
logging.basicConfig(level=logging.INFO)

# Словарь для отслеживания владельцев игр по message_id
game_owners = {}

# Photo assets directory (change if your images are elsewhere)
PHOTO_DIR = "C:\\BotKruz\\ChatBotKruz\\photo"
WIN_IMAGES = [os.path.join(PHOTO_DIR, f"win{i}.png") for i in range(1, 6)]
LOSE_IMAGES = [os.path.join(PHOTO_DIR, f"lose{i}.png") for i in range(1, 4)]

# Placeholder image for "repeat" flow (460x100 grey)
PLACEHOLDER_PATH = os.path.join(PHOTO_DIR, "placeholder_gray_460x100.png")

def ensure_placeholder_image(width: int = 460, height: int = 100, color=(235, 235, 235)) -> str | None:
    """Ensure placeholder exists; create with PIL if missing. Returns path or None."""
    try:
        if os.path.exists(PLACEHOLDER_PATH):
            return PLACEHOLDER_PATH
        # Try to create via PIL
        try:
            from PIL import Image  # type: ignore
            img = Image.new("RGB", (int(width), int(height)), color)
            os.makedirs(os.path.dirname(PLACEHOLDER_PATH), exist_ok=True)
            img.save(PLACEHOLDER_PATH)
            return PLACEHOLDER_PATH
        except Exception:
            return None
    except Exception:
        return None

# Комиссия (сжигание) для PvP батлов (от общего банка 2 * bet)
PVP_COMMISSION_RATE = 0.10  # 10% пота – по запросу

ACCEPT_PREFIX = "battle_accept:"
DECLINE_PREFIX = "battle_decline:"

def build_battle_keyboard(initiator_id: int, bet: int, target_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Принять", callback_data=f"battle_button_accept:{initiator_id}:{target_id}:{bet}")
    kb.button(text="Отказать", callback_data=f"battle_button_decline:{initiator_id}:{target_id}:{bet}")
    kb.adjust(2)
    return kb.as_markup()

active_battles = {}  # key: target_id, value: (initiator_id, bet, chat_id)

def get_nick(user):
    username = getattr(user, 'username', None)
    if username:
        return f'@{username}'
    name = (user.full_name or '').strip()
    if len(name) < 2:
        name = 'игрок'
    name = name[:20]
    return name

async def initiate_battle(message: types.Message, initiator_id: int, bet: int):
    target_msg = message.reply_to_message
    if not target_msg or not getattr(target_msg, "from_user", None):
        await message.reply("Чтобы начать батл, ответь на сообщение игрока и напиши 'бет X'.")
        return
    target_user = target_msg.from_user
    if target_user is None:
        await message.reply("Игрок не найден.")
        return
    if target_user.id == initiator_id:
        await message.reply("Нельзя сражаться с самим собой.")
        return

    initiator = db.get_user(initiator_id)
    target = db.get_user(target_user.id)
    if not initiator or not target:
        await message.reply("Оба игрока должны быть зарегистрированы.")
        return
    if initiator["dan"] < bet:
        await message.reply("У тебя недостаточно Дани для этой ставки.")
        return
    if target["dan"] < bet:
        await message.reply("У оппонента недостаточно Дани для этой ставки.")
        return

    kb = build_battle_keyboard(initiator_id, bet, target_user.id)
    initiator_nick = get_nick(message.from_user)
    target_nick = get_nick(target_user)
    # Сохраняем активный батл для target_id
    active_battles[target_user.id] = (initiator_id, bet, message.chat.id, initiator_nick, target_nick)
    await message.reply(
        f"🛡️ Батл: {initiator_nick} вызывает {target_nick} на {bet} Дань ✨\n\n"
        f"Удачи боец.\n",
        reply_markup=kb,
        parse_mode="HTML"
    )


# Новый способ: обработка кнопок — кнопки реально принимают/отклоняют батл
async def handle_accept_button(callback: types.CallbackQuery):
    data = callback.data or ""
    try:
        _, initiator_id, target_id, bet = data.split(":")
        initiator_id = int(initiator_id)
        target_id = int(target_id)
        bet = int(bet)
    except Exception:
        await callback.answer("Ошибка батла.", show_alert=True)
        return
    if not callback.from_user or not callback.message or not callback.message.chat:
        await callback.answer("Некорректный callback", show_alert=True)
        return
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    if user_id != target_id:
        await callback.answer("Только приглашённый игрок может принять батл.", show_alert=True)
        return
    battle = active_battles.get(user_id)
    if not battle or battle[2] != chat_id:
        await callback.answer("У вас нет активного батла.", show_alert=True)
        return
    initiator_id, bet, _, initiator_nick, target_nick = battle
    initiator = db.get_user(initiator_id)
    target = db.get_user(user_id)
    if not initiator or not target:
        await callback.answer("Ошибка: игрок не найден.", show_alert=True)
        return
    if initiator["dan"] < bet:
        await callback.answer("Инициатор не имеет нужной суммы.", show_alert=True)
        return
    if target["dan"] < bet:
        await callback.answer("У тебя недостаточно Дани.", show_alert=True)
        return
    winner_id = random.choice([initiator_id, user_id])
    loser_id = user_id if winner_id == initiator_id else initiator_id
    winner = initiator_nick if winner_id == initiator_id else target_nick
    loser = target_nick if loser_id == user_id else initiator_nick
    # Сбор банка и применение комиссии
    db.withdraw_dan(initiator_id, bet)
    db.withdraw_dan(user_id, bet)
    total_pot = bet * 2
    commission = int(total_pot * PVP_COMMISSION_RATE)
    payout = total_pot - commission
    db.add_dan(winner_id, payout)
    db.increment_games(initiator_id)
    db.increment_games(user_id)
    m = callback.message
    if m and hasattr(m, "edit_reply_markup"):
        try:
            await m.edit_reply_markup(reply_markup=None) # type: ignore
        except Exception:
            pass
    if m and hasattr(m, "answer"):
        await m.answer(
        (
            f"🎲 Результат батла!\n\n"
            f"Победитель: {winner} (+{payout - bet} чистыми)\n"
            f"Проигравший: {loser} (-{bet})\n"
            f"Комиссия с пота: {commission} Дань (сожжено)"
        ),
        parse_mode="HTML"
        )
    del active_battles[user_id]
    await callback.answer("Батл завершён.")

async def handle_decline_button(callback: types.CallbackQuery):
    data = callback.data or ""
    try:
        _, initiator_id, target_id, bet = data.split(":")
        initiator_id = int(initiator_id)
        target_id = int(target_id)
        bet = int(bet)
    except Exception:
        await callback.answer("Ошибка батла.", show_alert=True)
        return
    if not callback.from_user or not callback.message or not callback.message.chat:
        await callback.answer("Некорректный callback", show_alert=True)
        return
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    if user_id != target_id:
        await callback.answer("Только приглашённый может отклонить.", show_alert=True)
        return
    battle = active_battles.get(user_id)
    if not battle or battle[2] != chat_id:
        await callback.answer("У вас нет активного батла.", show_alert=True)
        return
    del active_battles[user_id]
    m = callback.message
    if m and hasattr(m, "edit_reply_markup"):
        try:
            await m.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    if m and hasattr(m, "answer"):
        await m.answer("❌ Батл отклонён игроком.")
    await callback.answer("Отклонено.")


# Новый способ: handle_accept_message вызывается только из команды "принять" в main.py
async def handle_accept_message(message: types.Message):
    if not message.from_user or not message.chat:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    battle = active_battles.get(user_id)
    if not battle or battle[2] != chat_id:
        await message.reply("У вас нет активного батла.")
        return
    initiator_id, bet, _, initiator_name, target_name = battle
    initiator = db.get_user(initiator_id)
    target = db.get_user(user_id)
    if not initiator or not target:
        await message.reply("Ошибка: игрок не найден.")
        return
    if initiator["dan"] < bet:
        await message.reply("Инициатор не имеет нужной суммы.")
        return
    if target["dan"] < bet:
        await message.reply("У тебя недостаточно Дани.")
        return
    winner_id = random.choice([initiator_id, user_id])
    loser_id = user_id if winner_id == initiator_id else initiator_id
    winner = initiator_name if winner_id == initiator_id else target_name
    loser = target_name if loser_id == user_id else initiator_name
    # Сбор банка и комиссия
    db.withdraw_dan(initiator_id, bet)
    db.withdraw_dan(user_id, bet)
    total_pot = bet * 2
    commission = int(total_pot * PVP_COMMISSION_RATE)
    payout = total_pot - commission
    db.add_dan(winner_id, payout)
    db.increment_games(initiator_id)
    db.increment_games(user_id)
    await message.reply(
        (
            f"🎲 Результат батла!\n"
            f"Победитель: {winner} (+{payout - bet} чистыми)\n"
            f"Проигравший: {loser} (-{bet})\n"
            f"Комиссия с пота: {commission} Дань (сожжено)"
        ),
        parse_mode="HTML"
    )
    del active_battles[user_id]


# Новый способ: handle_decline_message вызывается только из команды "отменить" в main.py
async def handle_decline_message(message: types.Message):
    if not message.from_user or not message.chat:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    battle = active_battles.get(user_id)
    if not battle or battle[2] != chat_id:
        await message.reply("У вас нет активного батла.")
        return
    del active_battles[user_id]
    await message.reply("❌ Батл отклонён игроком.")

async def solo_bet(message: types.Message, user_id: int, bet: int):
    username = message.from_user.username if message.from_user else None
    db.ensure_user(user_id, username or "player")
    user = db.get_user(user_id)
    if not user or user.get("dan", 0) < bet:
        await message.reply(f"Недостаточно Дани. Ваш баланс: {user.get('dan',0) if user else 0}")
        return
    # Withdraw stake and record first bet
    ok = db.withdraw_dan(user_id, bet)
    if not ok:
        await message.reply("Ошибка списания ставки.")
        return
    try:
        db.set_first_bet(user_id, bet)
    except Exception:
        pass

    r = random.random()
    if r < 0.48:
        mult = 0.0
        won = 0
        result_text = f"😢 Вы проиграли.\n\n💶Ставка: {bet}.\n🤣 Пройгрыш: {bet}."
        img_path = random.choice(LOSE_IMAGES)
        try:
            from database import increment_dan_lose
            increment_dan_lose(user_id, bet)
        except Exception:
            pass
    elif r < 0.95:
        mult = round(random.uniform(1.7, 2.1), 2)
        won = int(bet * mult)
        db.add_dan(user_id, won)
        result_text = f"🙂 Вы выиграли!\n\n💶Ставка: {bet}.\n🎲 Множитель: {mult}x.\n💰 Выигрыш: {won}."
        img_path = random.choice(WIN_IMAGES)
        try:
            from database import increment_dan_win, increment_dan_lose
            increment_dan_win(user_id, max(won - bet, 0))
            increment_dan_lose(user_id, bet)
        except Exception:
            pass
    else:
        mult = round(random.uniform(2.2, 2.5), 2)
        won = int(bet * mult)
        db.add_dan(user_id, won)
        result_text = f"🔥 Большой выигрыш!\n\n💶Ставка: {bet}.\n🎲 Множитель: {mult}x.\n💰 Выигрыш: {won}."
        img_path = random.choice(WIN_IMAGES)
        try:
            from database import increment_dan_win, increment_dan_lose
            increment_dan_win(user_id, max(won - bet, 0))
            increment_dan_lose(user_id, bet)
        except Exception:
            pass

    db.increment_games(user_id)
    user_row = db.get_user(user_id)
    balance = user_row["dan"] if user_row else 0
    plus_text = f" (+{won} ДАНЬ)" if won > 0 else ""
    result_text += f"\n\n😎 Ваш баланс: {balance:.2f} Дань{plus_text}."

    # Кнопка повторить игру, если хватает баланса
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = None
    if balance >= bet:
        callback_data = f"repeat_bet:{bet}"
        print(f"🔘 Создаем кнопку с callback_data: {callback_data}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить игру", callback_data=callback_data)]
        ])
    else:
        print(f"❌ Недостаточно баланса для кнопки: {balance} < {bet}")

    try:
        if img_path and os.path.exists(img_path):
            from aiogram.types import FSInputFile
            photo = FSInputFile(img_path)
            sent = await message.answer_photo(photo=photo, caption=result_text, reply_markup=kb)
            # Сохраняем владельца игры
            if sent and kb:
                game_owners[sent.message_id] = user_id
        else:
            sent = await message.reply(result_text, reply_markup=kb)
            # Сохраняем владельца игры
            if sent and kb:
                game_owners[sent.message_id] = user_id
    except Exception as e:
        sent = await message.reply(result_text, reply_markup=kb)
        # Сохраняем владельца игры даже в случае ошибки
        if sent and kb:
            game_owners[sent.message_id] = user_id
# НОВАЯ ФУНКЦИЯ ПОВТОРИТЬ БЕТ
async def repeat_bet_callback(callback: types.CallbackQuery):
    """Новый простой обработчик для повтора бета"""
    
    try:
        if not callback.data or not callback.data.startswith("repeat_bet:"):
            await callback.answer("Ошибка callback data", show_alert=True)
            return
            
        try:
            bet = int(callback.data.split(":")[1])
        except (IndexError, ValueError):
            await callback.answer("Ошибка ставки", show_alert=True)
            return
        
        user_id = callback.from_user.id
        
        # ПРОВЕРКА ВЛАДЕЛЬЦА: только автор последней игры может повторять
        message_id = callback.message.message_id if callback.message else None
        if message_id and message_id in game_owners:
            if game_owners[message_id] != user_id:
                await callback.answer("Только автор игры может повторять!", show_alert=True)
                return
        
        # Проверяем баланс
        user = db.get_user(user_id)
        if not user or user["dan"] < bet:
            await callback.answer(f"Недостаточно средств! Нужно {bet} ДАНЬ", show_alert=True)
            return
        
        # Регистрируем прогресс задач (аналог обычной ставки)
        try:
            import tasks
            tasks.record_battle_play(user_id)
            tasks.record_bet_play(user_id, bet)
        except Exception:
            pass

        # Списываем ставку
        if not db.withdraw_dan(user_id, bet):
            await callback.answer("Ошибка списания ставки", show_alert=True)
            return
        
        # Запускаем игру: при повторе используем плейсхолдер 600x100 серый вместо реального фото
        await run_bet_game_and_update_message(callback, user_id, bet, show_image="placeholder")
        
    except Exception as e:
        try:
            await callback.answer("Критическая ошибка игры", show_alert=True)
        except:
            pass


async def run_bet_game_and_update_message(callback: types.CallbackQuery, user_id: int, bet: int, show_image: bool | str = True):
    """Запускает игру бет и обновляет сообщение"""
    # Логика игры
    r = random.random()
    # Та же матрица, что и в solo_bet
    if r < 0.48:
        won = 0
        result_text = f"😢 Вы проиграли.\n\n💶Ставка: {bet}.\n🤣Проигрыш: {bet}."
        img_path = random.choice(LOSE_IMAGES)
        try:
            db.increment_dan_lose(user_id, bet)
        except Exception:
            pass
    elif r < 0.95:
        mult = round(random.uniform(1.7, 2.1), 2)
        won = int(bet * mult)
        db.add_dan(user_id, won)
        result_text = f"🙂 Вы выиграли!\n\n💶Ставка: {bet}.\n🎲 Множитель: {mult}x.\n💰 Выигрыш: {won}."
        img_path = random.choice(WIN_IMAGES)
        try:
            db.increment_dan_win(user_id, max(won - bet, 0))
            db.increment_dan_lose(user_id, bet)
        except Exception:
            pass
    else:
        mult = round(random.uniform(2.2, 2.5), 2)
        won = int(bet * mult)
        db.add_dan(user_id, won)
        result_text = f"🔥 Большой выигрыш!\n\n💶Ставка: {bet}.\n🎲 Множитель: {mult}x.\n💰 Выигрыш: {won}."
        img_path = random.choice(WIN_IMAGES)
        try:
            db.increment_dan_win(user_id, max(won - bet, 0))
            db.increment_dan_lose(user_id, bet)
        except Exception:
            pass

    # Обновляем счетчик игр
    try:
        db.increment_games(user_id)
    except Exception:
        pass
    
    # Получаем новый баланс
    user = db.get_user(user_id)
    balance = user["dan"] if user else 0
    plus_text = f" (+{won} ДАНЬ)" if won > 0 else ""
    result_text += f"\n\n😎 Ваш баланс: {balance:.2f} Дань{plus_text}."
    
    # Создаем кнопку если есть баланс
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = None
    if balance >= bet:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить игру", callback_data=f"repeat_bet:{bet}")]
        ])
    
    # Сохраняем владельца игры
    if callback.message:
        game_owners[callback.message.message_id] = user_id
    
    # Обновляем сообщение
    try:
        if callback.message:
            # decide image to use
            placeholder_path = None
            if show_image == "placeholder":
                placeholder_path = ensure_placeholder_image()
            selected_image_path = None
            if show_image == "placeholder":
                selected_image_path = placeholder_path
            elif show_image is True:
                selected_image_path = img_path
            else:
                selected_image_path = None

            if selected_image_path and os.path.exists(selected_image_path) and hasattr(callback.message, "edit_media"):
                try:
                    photo = FSInputFile(selected_image_path)
                    media = types.InputMediaPhoto(media=photo, caption=result_text)
                    await callback.message.edit_media(media=media, reply_markup=kb)
                except Exception:
                    # Fallback: try update caption if message is a photo
                    try:
                        if getattr(callback.message, "photo", None) is not None and hasattr(callback.message, "edit_caption"):
                            await callback.message.edit_caption(caption=result_text, reply_markup=kb)
                        elif hasattr(callback.message, "edit_text"):
                            await callback.message.edit_text(result_text, reply_markup=kb)
                    except Exception:
                        pass
            else:
                # No image change: update caption for photo messages, or text otherwise
                try:
                    if getattr(callback.message, "photo", None) is not None and hasattr(callback.message, "edit_caption"):
                        await callback.message.edit_caption(caption=result_text, reply_markup=kb)
                    elif hasattr(callback.message, "edit_text"):
                        await callback.message.edit_text(result_text, reply_markup=kb)
                except Exception:
                    pass
        await callback.answer("Новая игра!")
    except Exception:
        try:
            await callback.answer("Игра сыграна, но ошибка обновления", show_alert=True)
        except Exception:
            pass

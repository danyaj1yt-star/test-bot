# Для ограничения по времени
import time

# user_id: timestamp последней игры
last_dice_time = {}

import random
import asyncio
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database as db

# Импорт функции счетчика игр
def get_increment_games_count():
    try:
        from main import increment_games_count
        return increment_games_count
    except ImportError:
        return lambda: None  # заглушка если не удается импортировать


# key: target_id, value: {
#   'initiator_id': int,
#   'bet': int,
#   'chat_id': int,
#   'initiator_nick': str,
#   'target_nick': str,
#   'initiator_roll': int or None,
#   'target_roll': int or None
# }
active_dice_battles = {}


def build_dice_keyboard(initiator_id: int, bet: int, target_id: int):
	kb = InlineKeyboardBuilder()
	kb.button(text="Принять", callback_data=f"dice_accept:{initiator_id}:{target_id}:{bet}")
	kb.button(text="Отказать", callback_data=f"dice_decline:{initiator_id}:{target_id}:{bet}")
	kb.adjust(2)
	return kb.as_markup()

def build_roll_keyboard(target_id: int):
	kb = InlineKeyboardBuilder()
	kb.button(text="Бросить кости", callback_data=f"dice_roll:{target_id}")
	kb.adjust(1)
	return kb.as_markup()

def get_nick(user):
	username = getattr(user, 'username', None)
	if username:
		return f'@{username}'
	name = (user.full_name or '').strip()
	if len(name) < 2:
		name = 'игрок'
	name = name[:20]
	return name

async def initiate_dice_battle(message: types.Message, initiator_id: int, bet: int):
	now = time.time()
	# Проверка паузы для инициатора
	last_time = last_dice_time.get(initiator_id, 0)
	if now - last_time < 5:
		try:
			await message.delete()
		except Exception:
			pass
		await message.reply("Бро, не забывай про паузу в 5 секунд")
		return
	last_dice_time[initiator_id] = now
	target_msg = message.reply_to_message
	if not target_msg:
		await message.reply("Чтобы вызвать на кости, ответь на сообщение игрока и напиши 'кости N'.")
		return
	target_user = target_msg.from_user
	if target_user.id == initiator_id:
		await message.reply("Нельзя играть с самим собой.")
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
	kb = build_dice_keyboard(initiator_id, bet, target_user.id)
	initiator_nick = get_nick(message.from_user)
	target_nick = get_nick(target_user)
	active_dice_battles[target_user.id] = {
		'initiator_id': initiator_id,
		'bet': bet,
		'chat_id': message.chat.id,
		'initiator_nick': initiator_nick,
		'target_nick': target_nick,
		'initiator_roll': None,
		'target_roll': None
	}
	await message.reply(
		f"🎲 КОСТИ: {initiator_nick} вызывает {target_nick} на {bet} Дань ✨\n"
		f"Чтобы принять — нажмите кнопку ниже\n"
		f"Чтобы отклонить — нажмите кнопку ниже",
		reply_markup=kb,
		parse_mode="HTML"
	)


async def handle_dice_accept(callback: types.CallbackQuery):
	now = time.time()
	# Проверка паузы для второго игрока
	last_time = last_dice_time.get(callback.from_user.id, 0)
	if now - last_time < 5:
		await callback.answer("Бро, не забывай про паузу в 5 секунд", show_alert=True)
		return
	last_dice_time[callback.from_user.id] = now
	data = callback.data or ""
	try:
		_, initiator_id, target_id, bet = data.split(":")
		initiator_id = int(initiator_id)
		target_id = int(target_id)
		bet = int(bet)
	except Exception:
		await callback.answer("Ошибка батла.", show_alert=True)
		return
	user_id = callback.from_user.id
	chat_id = callback.message.chat.id
	if user_id != target_id:
		await callback.answer("Только приглашённый игрок может принять кости.", show_alert=True)
		return
	battle = active_dice_battles.get(user_id)
	if not battle or battle['chat_id'] != chat_id:
		await callback.answer("У вас нет активного батла.", show_alert=True)
		return
	initiator_id = battle['initiator_id']
	bet = battle['bet']
	initiator_nick = battle['initiator_nick']
	target_nick = battle['target_nick']
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
	# Списываем ставки (банк формируется и комиссия удерживается позже)
	db.withdraw_dan(initiator_id, bet)
	db.withdraw_dan(user_id, bet)
	
	# Увеличиваем счетчик игр
	increment_func = get_increment_games_count()
	increment_func()
	
	await callback.message.edit_reply_markup(reply_markup=None)
	# Бросок первого игрока
	await callback.message.answer(
		f"Игрок #1 {initiator_nick} кидает кости",
		parse_mode="HTML"
	)
	dice_obj1 = await callback.message.answer_dice(emoji="🎲")
	await asyncio.sleep(4)
	dice1 = dice_obj1.dice.value
	battle['initiator_roll'] = dice1
	# Не пишем отдельное сообщение 'Выпало: ...'
	# Бросок второго игрока
	await callback.message.answer(
		f"Игрок #2 {target_nick} кидает кости",
		parse_mode="HTML"
	)
	dice_obj2 = await callback.message.answer_dice(emoji="🎲")
	await asyncio.sleep(4)
	dice2 = dice_obj2.dice.value
	battle['target_roll'] = dice2
	# Не пишем отдельное сообщение 'Выпало: ...'
	# Итог
	result_text = (
		f"🎲 КОСТИ!\n{initiator_nick}: {dice1}\n{target_nick}: {dice2}\n"
	)
	# Комиссия на PvP (сжигание части банка)
	COMMISSION_RATE = 0.10  # 10% банка
	full_pot = bet * 2
	commission = int(full_pot * COMMISSION_RATE)
	payout = full_pot - commission

	if dice1 > dice2:
		db.add_dan(initiator_id, payout)
		try:
			profit = payout - bet
			db.increment_dan_win(initiator_id, max(profit,0))
			db.increment_dan_lose(user_id, bet)
		except Exception:
			pass
		winner = f"#1 {initiator_nick}"
		loser = f"#2 {target_nick}"
		result_text += (
			f"Выйграл {winner}\n"
			f"Чистый выигрыш: {payout - bet} (пот {full_pot}, комиссия {commission})\n"
			f"{loser} проиграл {bet}"
		)
	elif dice2 > dice1:
		db.add_dan(user_id, payout)
		try:
			profit = payout - bet
			db.increment_dan_win(user_id, max(profit,0))
			db.increment_dan_lose(initiator_id, bet)
		except Exception:
			pass
		winner = f"#2 {target_nick}"
		loser = f"#1 {initiator_nick}"
		result_text += (
			f"Выйграл {winner}\n"
			f"Чистый выигрыш: {payout - bet} (пот {full_pot}, комиссия {commission})\n"
			f"{loser} проиграл {bet}"
		)
	else:
		# Ничья: удерживаем половину комиссии (чтобы не слишком наказывать), остальное возвращаем
		# При ничьей удерживаем половину обычной комиссии (то есть 5% если базовая 10%)
		commission_tie = int(full_pot * 0.05)
		refund_each = (full_pot - commission_tie) // 2
		db.add_dan(initiator_id, refund_each)
		db.add_dan(user_id, refund_each)
		result_text += (
			f"Ничья! Возврат каждому: {refund_each}. Комиссия удержана: {commission_tie}"
		)
	db.increment_games(initiator_id)
	db.increment_games(user_id)
	await callback.message.answer(result_text, parse_mode="HTML")
	del active_dice_battles[user_id]
	await callback.answer("Батл завершён.")

async def handle_dice_roll(callback: types.CallbackQuery):
	# Теперь не используется, броски происходят автоматически
	await callback.answer("Бросок происходит автоматически.", show_alert=True)

async def handle_dice_decline(callback: types.CallbackQuery):
	data = callback.data or ""
	try:
		_, initiator_id, target_id, bet = data.split(":")
		initiator_id = int(initiator_id)
		target_id = int(target_id)
		bet = int(bet)
	except Exception:
		await callback.answer("Ошибка батла.", show_alert=True)
		return
	user_id = callback.from_user.id
	chat_id = callback.message.chat.id
	if user_id != target_id:
		await callback.answer("Только приглашённый может отклонить.", show_alert=True)
		return
	battle = active_dice_battles.get(user_id)
	if not battle or battle['chat_id'] != chat_id:
		await callback.answer("У вас нет активного батла.", show_alert=True)
		return
	del active_dice_battles[user_id]
	await callback.message.edit_reply_markup(reply_markup=None)
	await callback.message.answer("❌ Батл отклонён игроком.")
	await callback.answer("Отклонено.")
#nt
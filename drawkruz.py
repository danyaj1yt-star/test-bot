from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime
import random
import sqlite3
import os

ADMIN_ID = 1425069841  # твой Telegram user_id

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "game_bot.db")

# === инициализация базы ===
def init_draws_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            conditions TEXT,
            tickets INTEGER DEFAULT 0
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS draw_participants (
            draw_id INTEGER,
            user_id INTEGER,
            username TEXT,
            PRIMARY KEY (draw_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()

init_draws_table()

# === функции базы ===
def add_draw(date, conditions):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT INTO draws (date, conditions) VALUES (?, ?)', (date, conditions))
    draw_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draw_id

def get_draws():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, date, conditions, tickets FROM draws ORDER BY id DESC')
    data = cur.fetchall()
    conn.close()
    return data

def get_draw(draw_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, date, conditions, tickets FROM draws WHERE id=?', (draw_id,))
    data = cur.fetchone()
    conn.close()
    return data

# Временное состояние для установки условий через меню
pending_condition = {}  # admin_id -> draw_id

def add_draw_participant(draw_id, user_id, username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO draw_participants (draw_id, user_id, username) VALUES (?, ?, ?)', (draw_id, user_id, username))
    conn.commit()
    conn.close()

def get_draw_participants(draw_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT user_id, username FROM draw_participants WHERE draw_id=?', (draw_id,))
    data = cur.fetchall()
    conn.close()
    return data

# === команды админа ===
ADMIN_COMMANDS = [
    "/drawlist — список розыгрышей",
    "/drawadd — добавить конкурс",
    "/drawcond # условие — изменить условие",
    "/drawpart # — список участников",
    "/drawwin # [id] — выбрать победителя",
    "/deldraw # — удалить конкурс"
]

# === меню ===
async def handle_draw_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Только для администратора!")
        return
    text = "🎲 Главное меню розыгрышей\n\n" + "\n".join(ADMIN_COMMANDS)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Список розыгрышей", callback_data="draw_list")],
        [InlineKeyboardButton(text="+ Добавить", callback_data="draw_add")],
        [InlineKeyboardButton(text="Закрыть", callback_data="draw_close")]
    ])
    await message.reply(text, reply_markup=kb)

# === обработка ===
async def process_draw_commands(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Только для администратора!")
        return

    text = message.text.strip()
    if text.startswith("/drawlist"):
        await show_draw_list(message)
    elif text.startswith("/drawadd"):
        await add_draw_start(message)
    elif text.startswith("/drawcond"):
        parts = text.split()
        if len(parts) >= 3 and parts[1].isdigit():
            draw_id = int(parts[1])
            cond = " ".join(parts[2:])
            await add_draw_condition(message, draw_id, cond)
        else:
            await message.reply("Формат: /drawcond # условие")
    elif text.startswith("/drawpart"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            await show_draw_participants(message, int(parts[1]))
        else:
            await message.reply("Формат: /drawpart #")
    elif text.startswith("/drawwin"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            draw_id = int(parts[1])
            winner_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
            await pick_draw_winner(message, draw_id, winner_id)
        else:
            await message.reply("Формат: /drawwin # [id]")
    elif text.startswith("/deldraw"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            await delete_draw(message, int(parts[1]))
        else:
            await message.reply("Формат: /deldraw #")
    elif text.startswith("/draw"):
        parts = text.split()
        if len(parts) >= 3 and parts[1].isdigit():
            draw_id = int(parts[1])
            check_id = int(parts[2])
            await show_draw_result(message, draw_id, check_id)
        else:
            await handle_draw_command(message)
    else:
        await handle_draw_command(message)

# === список розыгрышей ===
async def show_draw_list(message: types.Message):
    draws = get_draws()
    if not draws:
        await message.reply("Пока нет розыгрышей.")
        return

    kb_rows = []
    header = f"У вас {sum(len(get_draw_participants(d[0])) for d in draws)} участников, билетов {sum(d[3] for d in draws)}\n"
    # For each draw add a row with action buttons
    for d in draws:
        draw_id = d[0]
        date = d[1]
        participants_count = len(get_draw_participants(draw_id))
        # row: [View, Cond, Win, Del]
        kb_rows.append([
            InlineKeyboardButton(text=f"#{draw_id} {date} (U:{participants_count})", callback_data=f"draw_view:{draw_id}"),
        ])
        kb_rows.append([
            InlineKeyboardButton(text="👥 Участники", callback_data=f"draw_view:{draw_id}"),
            InlineKeyboardButton(text="✏️ Условия", callback_data=f"draw_setcond:{draw_id}"),
            InlineKeyboardButton(text="🏆 Победитель", callback_data=f"draw_win:{draw_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"draw_del:{draw_id}")
        ])

    kb_rows.append([InlineKeyboardButton(text="⬅️ Закрыть", callback_data="draw_close")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.reply(header, reply_markup=kb)

# === участники ===
async def show_draw_participants(message: types.Message, draw_id: int):
    parts = get_draw_participants(draw_id)
    if not parts:
        await message.reply("Нет участников.")
        return
    lines = [f"Участники #{draw_id}:"]
    for p in parts[:30]:
        lines.append(f"{p[1]} (<a href='tg://user?id={p[0]}'>{p[0]}</a>)")
    await message.reply("\n".join(lines), parse_mode="HTML")

# === победитель ===
async def pick_draw_winner(message: types.Message, draw_id: int, winner_id: int = 0):
    parts = get_draw_participants(draw_id)
    if not parts:
        await message.reply("Нет участников.")
        return
    winner = random.choice(parts) if winner_id == 0 else next((p for p in parts if p[0] == winner_id), None)
    if not winner:
        await message.reply("Участник не найден.")
        return
    await message.reply(f"Победитель: <a href='tg://user?id={winner[0]}'>{winner[1]}</a>", parse_mode="HTML")
    try:
        await message.bot.send_message(winner[0], "🎉 Ты победил в розыгрыше!")
    except Exception:
        pass

# === добавить конкурс ===
async def add_draw_start(message: types.Message):
    draw_date = datetime.datetime.now().strftime('%d.%m.%y')
    draw_id = add_draw(draw_date, "")
    await message.reply(f"Конкурс #{draw_id} создан!\nНапиши условие (через запятую или 0 если нет условий).")

async def add_draw_condition(message: types.Message, draw_id: int, condition_text: str):
    if condition_text.strip() == "0":
        await message.reply(f"✅ Условия для #{draw_id}: нет условий.")
    else:
        conds = [c.strip() for c in condition_text.split(",") if c.strip()]
        await message.reply(f"✅ Условия для #{draw_id}: {', '.join(conds)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE draws SET conditions=? WHERE id=?', (condition_text, draw_id))
    conn.commit()
    conn.close()

# === удалить конкурс ===
async def delete_draw(message: types.Message, draw_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('DELETE FROM draws WHERE id=?', (draw_id,))
    cur.execute('DELETE FROM draw_participants WHERE draw_id=?', (draw_id,))
    conn.commit()
    conn.close()
    await message.reply(f"🗑 Розыгрыш #{draw_id} удалён.")

# === показать итоги ===
async def show_draw_result(message: types.Message, draw_id: int, check_id: int):
    parts = get_draw_participants(draw_id)
    if not parts:
        await message.reply("Нет участников.")
        return
    winner = random.choice(parts)
    draw = get_draw(draw_id)
    conds = [c.strip() for c in (draw[2] or "").split(",") if c.strip()]

    text = f"🏆 Победитель <a href='tg://user?id={winner[0]}'>{winner[1]}</a>!\n\n"
    if conds:
        for c in conds:
            text += f"{c} - ❌\n"
    else:
        text += "Без условий.\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Отправить итоги", callback_data=f"send_results_{draw_id}")]
    ])
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


def register_draw_handlers(dp):
    """Register callback handlers on provided Dispatcher (idempotent).

    This lets main.py keep only /draw and delegate all button/menu logic to this module.
    """
    # avoid double registration
    if getattr(dp, "_drawkruz_registered", False):
        return
    dp._drawkruz_registered = True

    # Список розыгрышей
    @dp.callback_query(lambda c: c.data == 'draw_list')
    async def _cb_draw_list(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        # quick ack so user sees button press registered
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_list invoked by {getattr(callback.from_user,'id',None)}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_list blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            # If original message is accessible, use it. Otherwise send DM to admin.
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await show_draw_list(msg)
            else:
                draws = get_draws()
                if not draws:
                    await callback.bot.send_message(callback.from_user.id, "Пока нет розыгрышей.")
                    return
                total_participants = sum(len(get_draw_participants(d[0])) for d in draws)
                total_tickets = sum(d[3] for d in draws)
                lines = [f"У вас {total_participants} участников, билетов {total_tickets}\n"]
                for d in draws:
                    lines.append(f"#{d[0]} — {d[1]} | Участников: {len(get_draw_participants(d[0]))}")
                try:
                    await callback.bot.send_message(callback.from_user.id, "\n".join(lines))
                except Exception:
                    print("[drawkruz] failed to DM draw list to admin")
        except Exception:
            try:
                await callback.answer('Ошибка при показе списка', show_alert=True)
            except Exception:
                pass

    # Добавить розыгрыш
    @dp.callback_query(lambda c: c.data == 'draw_add')
    async def _cb_draw_add(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_add invoked by {getattr(callback.from_user,'id',None)}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_add blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await add_draw_start(msg)
            else:
                # create draw and inform admin via DM
                draw_date = datetime.datetime.now().strftime('%d.%m.%y')
                draw_id = add_draw(draw_date, "")
                try:
                    await callback.bot.send_message(callback.from_user.id, f"Конкурс #{draw_id} создан!\nНапиши условие (через запятую или 0 если нет условий).")
                except Exception:
                    print("[drawkruz] failed to DM new draw to admin")
        except Exception:
            try:
                await callback.answer('Ошибка при создании', show_alert=True)
            except Exception:
                pass

    # Просмотр участников / детальный просмотр розыгрыша
    @dp.callback_query(lambda c: c.data and c.data.startswith('draw_view:'))
    async def _cb_draw_view(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_view invoked by {getattr(callback.from_user,'id',None)} data={callback.data}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_view blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            draw_id = int(callback.data.split(':', 1)[1])
        except Exception:
            await callback.answer('Ошибка данных', show_alert=True)
            return
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await show_draw_participants(msg, draw_id)
            else:
                parts = get_draw_participants(draw_id)
                if not parts:
                    try:
                        await callback.bot.send_message(callback.from_user.id, 'Нет участников.')
                    except Exception:
                        print('[drawkruz] failed to DM no participants')
                    return
                lines = [f'Участники #{draw_id}:']
                for p in parts[:30]:
                    lines.append(f"{p[1]} (<a href='tg://user?id={p[0]}'>{p[0]}</a>)")
                await callback.bot.send_message(callback.from_user.id, '\n'.join(lines), parse_mode='HTML')
        except Exception:
            try:
                await callback.answer('Ошибка при показе', show_alert=True)
            except Exception:
                pass

    # Установить условие — переводим в pending состояние
    @dp.callback_query(lambda c: c.data and c.data.startswith('draw_setcond:'))
    async def _cb_draw_setcond(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_setcond invoked by {getattr(callback.from_user,'id',None)} data={callback.data}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_setcond blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            draw_id = int(callback.data.split(':', 1)[1])
        except Exception:
            await callback.answer('Ошибка данных', show_alert=True)
            return
        # mark pending and ask for text
        pending_condition[callback.from_user.id] = draw_id
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await msg.reply(f'Отправьте текст условий для конкурса #{draw_id}. Отправьте 0 для отмены.')
            else:
                try:
                    await callback.bot.send_message(callback.from_user.id, f'Отправьте текст условий для конкурса #{draw_id}. Отправьте 0 для отмены.')
                except Exception:
                    print('[drawkruz] failed to DM setcond prompt')
        except Exception:
            try:
                await callback.answer('Готово — пришлите условия', show_alert=False)
            except Exception:
                pass

    # Выбрать победителя
    @dp.callback_query(lambda c: c.data and c.data.startswith('draw_win:'))
    async def _cb_draw_win(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_win invoked by {getattr(callback.from_user,'id',None)} data={callback.data}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_win blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            draw_id = int(callback.data.split(':', 1)[1])
        except Exception:
            await callback.answer('Ошибка данных', show_alert=True)
            return
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await pick_draw_winner(msg, draw_id, 0)
            else:
                parts = get_draw_participants(draw_id)
                if not parts:
                    try:
                        await callback.bot.send_message(callback.from_user.id, 'Нет участников.')
                    except Exception:
                        print('[drawkruz] failed to DM no participants on win')
                    return
                winner = random.choice(parts)
                try:
                    await callback.bot.send_message(callback.from_user.id, f"Победитель: <a href='tg://user?id={winner[0]}'>{winner[1]}</a>", parse_mode='HTML')
                except Exception:
                    print('[drawkruz] failed to DM winner')
        except Exception:
            try:
                await callback.answer('Ошибка при выборе', show_alert=True)
            except Exception:
                pass

    # Удалить розыгрыш
    @dp.callback_query(lambda c: c.data and c.data.startswith('draw_del:'))
    async def _cb_draw_del(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        try:
            await callback.answer()
        except Exception:
            pass
        print(f"[drawkruz] cb_draw_del invoked by {getattr(callback.from_user,'id',None)} data={callback.data}")
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            print(f"[drawkruz] cb_draw_del blocked non-admin {getattr(callback.from_user,'id',None)}")
            return
        try:
            draw_id = int(callback.data.split(':', 1)[1])
        except Exception:
            await callback.answer('Ошибка данных', show_alert=True)
            return
        try:
            msg = getattr(callback, 'message', None)
            await delete_draw(msg if msg is not None and hasattr(msg, 'reply') else callback.message, draw_id)
            try:
                await callback.answer('Удалено', show_alert=False)
            except Exception:
                pass
        except Exception:
            try:
                await callback.answer('Ошибка при удалении', show_alert=True)
            except Exception:
                pass

    # Обработчик сообщений для установки условий (pending)
    @dp.message(lambda m: getattr(m, 'from_user', None) and m.from_user.id in pending_condition)
    async def _handle_pending_condition(message: types.Message):
        user_id = message.from_user.id
        print(f"[drawkruz] pending condition message from {user_id}: {message.text[:80] if message.text else '<no-text>'}")
        try:
            draw_id = pending_condition.pop(user_id, None)
            if draw_id is None:
                return
            # if user sent '0' — cancel
            if message.text.strip() == '0':
                await message.reply(f'Установка условий для #{draw_id} отменена.')
                return
            await add_draw_condition(message, draw_id, message.text)
            await message.reply(f'Условия для конкурса #{draw_id} сохранены.')
        except Exception as e:
            try:
                await message.reply('Ошибка при сохранении условия')
            except Exception:
                pass

    # Закрыть меню
    @dp.callback_query(lambda c: c.data == 'draw_close')
    async def _cb_draw_close(callback: types.CallbackQuery):
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'delete'):
                await msg.delete()
            else:
                try:
                    await callback.answer('Закрыто', show_alert=False)
                except Exception:
                    pass
        except Exception:
            try:
                await callback.answer('Закрыто', show_alert=False)
            except Exception:
                pass

    # Отправить итоги
    @dp.callback_query(lambda c: c.data and c.data.startswith('send_results_'))
    async def _cb_draw_send_results(callback: types.CallbackQuery):
        if not getattr(callback, 'from_user', None):
            return
        if callback.from_user.id != ADMIN_ID:
            await callback.answer('⛔ Только для администратора!', show_alert=True)
            return
        try:
            draw_id = int(callback.data.split('_')[-1])
        except Exception:
            await callback.answer('Ошибка данных', show_alert=True)
            return
        try:
            msg = getattr(callback, 'message', None)
            if msg is not None and hasattr(msg, 'reply'):
                await show_draw_result(msg, draw_id, 0)
            else:
                # send result DM to admin
                parts = get_draw_participants(draw_id)
                if not parts:
                    await callback.bot.send_message(callback.from_user.id, 'Нет участников.')
                    return
                winner = random.choice(parts)
                draw = get_draw(draw_id)
                conds = [c.strip() for c in (draw[2] or "").split(",") if c.strip()]
                text = f"🏆 Победитель <a href='tg://user?id={winner[0]}'>{winner[1]}</a>!\n\n"
                if conds:
                    for c in conds:
                        text += f"{c} - ❌\n"
                else:
                    text += "Без условий.\n"
                await callback.bot.send_message(callback.from_user.id, text, parse_mode='HTML')
        except Exception:
            try:
                await callback.answer('Ошибка при отправке итогов', show_alert=True)
            except Exception:
                pass

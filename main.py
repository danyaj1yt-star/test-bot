# type: ignore
import os
import sys
import asyncio
import logging
import time
import sqlite3
import datetime
import hashlib
import queue
import threading
import random
import importlib
from typing import Optional, Union
import re
import html
import pytz  # timezones used across lottery/daily features
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, 
    ContentType, FSInputFile, InputMediaPhoto, InlineQuery,
    InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Ensure project root is importable when running the bot directly
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Helper to try loading module from inv_py then fallback to top-level module
def load_module(name: str):
    """Try import 'inv_py.<name>' first, then fall back to '<name>'. Returns module or raises ImportError."""
    try:
        return importlib.import_module(f"inv_py.{name}")
    except Exception:
        return importlib.import_module(name)


logging.basicConfig(level=logging.INFO)
VOICE_LOGGER = logging.getLogger("voice_handler")
VOICE_LOGGER.setLevel(logging.INFO)
if not VOICE_LOGGER.handlers:
    # Ensure at least one handler exists so messages do not get swallowed
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s: %(message)s"))
    VOICE_LOGGER.addHandler(stream_handler)
VOICE_LOGGER.propagate = False
# ID бота для защиты от вызовов на дуэли и переводов
BOT_ID = 8432092298
API_TOKEN = os.getenv("BOT_TOKEN") or "8224775217:AAFANNRP1AkWfdLdriUP_XWpTCNKdjNcE9M"
bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# Load inventory helpers, config and renderer modules via the helper above.
inv_inventory = load_module('inventory')
inv_config = load_module('config_inventory')
inv_renderer = load_module('render_inventory')
get_user_inventory = getattr(inv_inventory, 'get_user_inventory')
build_inventory_markup = getattr(inv_inventory, 'build_inventory_markup')
show_item_card = getattr(inv_inventory, 'show_item_card')
use_item = getattr(inv_inventory, 'use_item')
ITEMS_CONFIG = getattr(inv_config, 'ITEMS_CONFIG')
NULL_ITEM = getattr(inv_config, 'NULL_ITEM')

# Кешируем часто используемые данные конфигурации
CONFIG_CACHE = {
    'items_config': ITEMS_CONFIG,
    'null_item': NULL_ITEM,
    'items_by_id': {item_id: config for item_id, config in ITEMS_CONFIG.items()},
    'items_by_price': sorted([(config.get('price', 0), item_id, config) for item_id, config in ITEMS_CONFIG.items()]),
    'item_names': {item_id: config.get('name', f'Товар {item_id}') for item_id, config in ITEMS_CONFIG.items()}
}

print("✅ Конфигурация предзагружена и закеширована")

# Вспомогательные функции для быстрого доступа к конфигурации
def get_item_config(item_id: str):
    """Быстрый доступ к конфигурации предмета из кеша"""
    return CONFIG_CACHE['items_by_id'].get(item_id, {})

def get_item_name(item_id: str):
    """Быстрый доступ к имени предмета из кеша"""
    return CONFIG_CACHE['item_names'].get(item_id, f'Товар {item_id}')

def get_item_price(item_id: str):
    """Быстрый доступ к цене предмета из кеша"""
    config = get_item_config(item_id)
    return config.get('price', 0)

def get_item_photo(item_id: str):
    """Быстрый доступ к фото предмета из кеша"""
    config = get_item_config(item_id)
    return config.get('photo_square', NULL_ITEM.get("photo_square", ""))

print("✅ Вспомогательные функции для кешированной конфигурации созданы")

render_inventory_grid = getattr(inv_renderer, 'render_inventory_grid')

# Auction UI helpers (hoisted imports for hot paths)
from inv_py.auction import (
    get_auction_display_data,
    render_auction_grid_cached,
    format_auction_caption,
)

# === LAZY IMPORTS (будут загружены при первом использовании) ===
def lazy_import_heavy_modules():
    """Ленивый импорт тяжелых модулей для ускорения старта бота"""
    global betcosty, battles, PIL
    try:
        from plugins.games import betcosty, battles
        from PIL import Image, ImageDraw, ImageFont
        PIL = {'Image': Image, 'ImageDraw': ImageDraw, 'ImageFont': ImageFont}
        print("✅ Тяжелые модули загружены")
    except ImportError as e:
        print(f"❌ Ошибка загрузки тяжелых модулей: {e}")

# Импорты для игровых модулей (теперь через plugins)
def import_game_modules():
    """Импорт игровых модулей при необходимости"""
    global start_clad_game, get_keyboard, step_clad_game, take_clad_game, MULTS, active_clads
    global saper_message_handler, saper_callback_handler, start_saper_game, active_saper_games
    global battles, betcosty
    try:
        from plugins.games import clad, saper, battles, betcosty
        # Экспортируем функции из модулей
        start_clad_game = clad.start_clad_game
        get_keyboard = clad.get_keyboard
        step_clad_game = clad.step_clad_game
        take_clad_game = clad.take_clad_game
        MULTS = clad.MULTS
        active_clads = clad.active_clads
        
        saper_message_handler = saper.saper_message_handler
        saper_callback_handler = saper.saper_callback_handler
        start_saper_game = saper.start_saper_game
        active_saper_games = saper.active_saper_games
        return True
    except ImportError as e:
        print(f"❌ Ошибка импорта игровых модулей: {e}")
        return False

# Основные импорты проекта
from ferma import get_farm, get_farm_leaderboard_position
import database as db
from database import (
    add_xp, get_user_xp_data, claim_level_reward, 
    generate_random_level_rewards, add_dan, add_kruz
)
from bank import (
    bank_system, format_amount, format_full_amount, DEPOSIT_PLANS, get_deposit_plan_text, 
    format_deposit_button_text, get_deposit_action_emoji, paginate_deposits
)
from plugins.games import arena
import tasks
import tasks as _tasks  # Алиас для новых интеграций

# --- Store last saper, bet, and clad stakes per user ---
last_saper_stake = {}
last_bet_stake = {}
last_clad_bet = {}
active_bowling_games = {}  # Активные игры в боулинг
active_darts_games = {}    # Активные игры в дартс
active_soccer_games = {}   # Активные игры в футбол

# Простая защита от flood control для edit_media
LAST_EDIT_MEDIA = {}
EDIT_MEDIA_COOLDOWN = 0.3  # 300ms между edit_media для одного пользователя

def can_edit_media(user_id: int) -> bool:
    """Проверяет, можно ли выполнить edit_media для пользователя"""
    now = time.time()
    last_edit = LAST_EDIT_MEDIA.get(user_id, 0)
    if now - last_edit < EDIT_MEDIA_COOLDOWN:
        return False
    LAST_EDIT_MEDIA[user_id] = now
    return True

# Добавляем недостающие функции для статистики
def get_today_games_count():
    """Заглушка для подсчета игр за сегодня"""
    return {"saper": 42, "clad": 38, "battle": 15}

def make_stat_image(count, base_path, out_path):
    """Заглушка для создания изображения статистики"""
    try:
        # Копируем базовое изображение
        import shutil
        shutil.copy2(base_path, out_path)
    except Exception:
        pass
    
class DBConnectionPool:
    def __init__(self, database_file: str, max_connections: int = 5):
        self.database_file = database_file
        self.pool = queue.Queue(maxsize=max_connections)
        self.lock = threading.Lock()
        # Заполняем pool соединениями
        for _ in range(max_connections):
            conn = sqlite3.connect(database_file, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")  # Оптимизация для множественного доступа
            self.pool.put(conn)
    
    def get_connection(self):
        return self.pool.get()
    
    def return_connection(self, conn):
        self.pool.put(conn)
    
    def execute_query(self, query: str, params=None):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            result = cursor.fetchall()
            conn.commit()
            return result
        finally:
            self.return_connection(conn)
    
    def execute_one(self, query: str, params=None):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            result = cursor.fetchone()
            conn.commit()
            return result
        finally:
            self.return_connection(conn)
db_pool = None
user_game_times = {}
user_ban_until = {}
try:
    from aiogram.dispatcher.middlewares import BaseMiddleware
except Exception:
    BaseMiddleware = None

if BaseMiddleware is not None:

    import time as _time

    class UsernameLoggingMiddleware(BaseMiddleware):
        async def __call__(self, handler, event, data):
            t0 = _time.perf_counter()
            # extract username if present
            username = None
            try:
                # Update may contain message, callback_query, edited_message, etc.
                if getattr(event, 'message', None) and getattr(event.message, 'from_user', None):
                    u = event.message.from_user
                    username = getattr(u, 'username', None) or f"{getattr(u, 'id', 'unknown')}"
                elif getattr(event, 'callback_query', None) and getattr(event.callback_query, 'from_user', None):
                    u = event.callback_query.from_user
                    username = getattr(u, 'username', None) or f"{getattr(u, 'id', 'unknown')}"
                elif getattr(event, 'inline_query', None) and getattr(event.inline_query, 'from_user', None):
                    u = event.inline_query.from_user
                    username = getattr(u, 'username', None) or f"{getattr(u, 'id', 'unknown')}"
            except Exception:
                username = None

            try:
                result = await handler(event, data)
                return result
            finally:
                try:
                    duration_ms = int((_time.perf_counter() - t0) * 1000)
                    logger = logging.getLogger("aiogram.event")
                    update_id = getattr(event, 'update_id', 'unknown')
                    bot_id = getattr(bot, 'id', None) or API_TOKEN.split(':')[0]
                    # Format username inside brackets if present, otherwise empty brackets
                    uname = username if username else ""
                    logger.info(f"Update id={update_id} is handled. [{uname}] - {duration_ms} ms id={bot_id}")
                except Exception:
                    pass

    middleware_instance = UsernameLoggingMiddleware()
    registration_attempts = [
        lambda m: dp.message.middleware(m),
        lambda m: dp.callback_query.middleware(m),
        lambda m: dp.update.middleware(m),
        lambda m: dp.router.middleware(m),
        lambda m: dp.middleware.register(m),
    ]
    for reg in registration_attempts:
        try:
            reg(middleware_instance)
        except Exception:
            # ignore and try next registration method
            pass

    # Pre-logging middleware: logs incoming update with username immediately (covers not-handled updates)
    class PreLoggingMiddleware(BaseMiddleware):
        async def __call__(self, handler, event, data):
            try:
                logger = logging.getLogger('aiogram.event')
                update_id = getattr(event, 'update_id', 'unknown')
                username = ''
                try:
                    if getattr(event, 'message', None) and getattr(event.message, 'from_user', None):
                        u = event.message.from_user
                        username = getattr(u, 'username', None) or str(getattr(u, 'id', ''))
                    elif getattr(event, 'callback_query', None) and getattr(event.callback_query, 'from_user', None):
                        u = event.callback_query.from_user
                        username = getattr(u, 'username', None) or str(getattr(u, 'id', ''))
                    elif getattr(event, 'inline_query', None) and getattr(event.inline_query, 'from_user', None):
                        u = event.inline_query.from_user
                        username = getattr(u, 'username', None) or str(getattr(u, 'id', ''))
                except Exception:
                    username = ''
                logger.info(f"Update id={update_id} received. [{username}]")
            except Exception:
                pass
            # continue to next middleware/handler
            return await handler(event, data)

    pre_mw = PreLoggingMiddleware()
    for reg in registration_attempts:
        try:
            reg(pre_mw)
        except Exception:
            pass

    # Task command tracking middleware
    class TaskCommandMiddleware(BaseMiddleware):
        async def __call__(self, handler, event, data):
            # Отслеживаем команды для заданий
            try:
                if hasattr(event, 'message') and event.message:
                    msg = event.message
                    if hasattr(msg, 'text') and msg.text and msg.text.startswith('/'):
                        if hasattr(msg, 'from_user') and msg.from_user:
                            try:
                                _tasks.record_command_use(msg.from_user.id)
                            except Exception as e:
                                print(f"❌ Ошибка записи выполнения команды для {msg.from_user.id}: {e}")
            except Exception:
                pass
            # Продолжаем обработку
            return await handler(event, data)

    task_cmd_mw = TaskCommandMiddleware()
    for reg in registration_attempts:
        try:
            reg(task_cmd_mw)
        except Exception:
            pass



def is_bot_user(user_id):
    """Проверяет является ли пользователь ботом"""
    return user_id == BOT_ID

# === РАННЯЯ РЕГИСТРАЦИЯ ОБРАБОТЧИКА ТРАНСКРИПЦІЇ (ВЫСОКИЙ ПРИОРИТЕТ) ===
@dp.message(lambda m: (
    m.reply_to_message is not None and 
    getattr(m.reply_to_message, 'voice', None) is not None and 
    m.text is not None and 
    ("гс" in m.text.lower() or "текст" in m.text.lower() or "текстом" in m.text.lower())
))
async def handle_voice_reply_with_gs(message: types.Message):
    """Транскрибує голосове повідомлення при відповіді з 'гс', 'текст', 'текстом'.
    Якщо користувач згадав бота (@username) — надсилаємо голосове та текст у ЛС."""
    VOICE_LOGGER.info(
        "Voice handler fired (chat=%s user=%s via_bot=%s is_reply=%s)",
        message.chat.id,
        message.from_user.id,
        getattr(message, 'via_bot', None),
        bool(message.reply_to_message),
    )
    VOICE_LOGGER.debug("Trigger text: %s", message.text)
    
    from plugins.api_soft_ai import transcribe_voice_message

    me = await bot.get_me()
    bot_mention = f"@{me.username.lower()}" if me.username else None
    text_lower = message.text.lower()
    mention_mode = bot_mention and bot_mention in text_lower

    voice_file_id = message.reply_to_message.voice.file_id
    voice_sender = message.reply_to_message.from_user
    sender_name = voice_sender.first_name or ""
    if voice_sender.last_name:
        sender_name += f" {voice_sender.last_name}"
    if not sender_name.strip():
        sender_name = f"Користувач {voice_sender.id}"

    ack = None
    dm_ready = False

    if mention_mode:
        ack = await message.reply("📩 Отправляю голосовое в личные сообщения, ждите текст там.")
        dm_chat_id = message.from_user.id

        try:
            await bot.copy_message(
                chat_id=dm_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            VOICE_LOGGER.info(
                "Copied voice %s from chat %s to user %s",
                message.reply_to_message.message_id,
                message.chat.id,
                dm_chat_id,
            )
            processing_msg = await bot.send_message(
                dm_chat_id,
                "🎙️ Розпізнаю голосове повідомлення..."
            )
            target_msg = processing_msg
            dm_ready = True
        except Exception as dm_err:
            VOICE_LOGGER.warning(
                "Failed to deliver voice/text to DM (user=%s chat=%s): %s",
                dm_chat_id,
                message.chat.id,
                dm_err,
            )
            if ack:
                try:
                    hint_username = me.username or "aichattwitchbot"
                    await ack.edit_text(
                        "⚠️ Не могу написать вам в личные сообщения. Откройте чат с ботом и попробуйте снова: "
                        f"https://t.me/{hint_username}"
                    )
                except Exception:
                    pass

    # Если в ЛС написать не получилось, продолжаем обработку прямо в чате
    if not dm_ready:
        VOICE_LOGGER.info(
            "Processing voice inline в чате (chat=%s user=%s) dm_ready=%s",
            message.chat.id,
            message.from_user.id,
            dm_ready,
        )
        processing_msg = await message.reply("🎙️ Розпізнаю голосове повідомлення...")
        target_msg = processing_msg

    try:
        VOICE_LOGGER.info(
            "Starting transcription (voice_file_id=%s chat=%s user=%s)",
            voice_file_id,
            message.chat.id,
            message.from_user.id,
        )
        transcript = await transcribe_voice_message(bot, voice_file_id)
        if transcript:
            result_text = f"🎙️ <b>{sender_name} сказав:</b>\n\n{transcript}"
            await target_msg.edit_text(result_text, parse_mode="HTML")
            if dm_ready and ack:
                await ack.edit_text("✅ Текст отправлен в личные сообщения.")
        else:
            await target_msg.edit_text("❌ Не вдалося розпізнати голосове повідомлення.")
            if dm_ready and ack:
                await ack.edit_text("⚠️ Не вдалося розпізнати голосове. Спробуйте ще раз у ЛС.")
    except Exception as e:
        VOICE_LOGGER.exception(
            "Transcription failed (chat=%s user=%s voice_id=%s)",
            message.chat.id,
            message.from_user.id,
            voice_file_id,
        )
        try:
            await target_msg.edit_text("❌ Сталася помилка при розпізнаванні.")
        except Exception:
            pass

# === РАННЯЯ РЕГИСТРАЦИЯ ОБРАБОТЧИКА REPEAT BET ===
@dp.callback_query(lambda c: c.data and c.data.startswith("repeat_bet:"))
async def early_repeat_bet_handler(callback: types.CallbackQuery):
    try:
        increment_games_count()
        # Импортируем battles только когда нужно (через plugins.games)
        try:
            from plugins.games import battles as _battles  # type: ignore
        except Exception:
            # Пытаемся загрузить игровые модули и повторить импорт
            if not import_game_modules():
                await callback.answer("Игра недоступна", show_alert=True)
                return
            try:
                from plugins.games import battles as _battles  # type: ignore
            except Exception:
                await callback.answer("Игра недоступна", show_alert=True)
                return
        await _battles.repeat_bet_callback(callback)
    except Exception as e:
        await callback.answer("Ошибка игры", show_alert=True)

# --- ОПТИМИЗАЦИЯ: Кеш для изображений ---
IMAGE_CACHE = {}
CACHE_DIR = "C:/BotKruz/ChatBotKruz/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_key(grid_items, item_images):
    """Создает уникальный ключ кеша на основе содержимого"""
    content = str(sorted(grid_items)) + str(sorted(item_images.items()))
    return hashlib.md5(content.encode()).hexdigest()

def get_cached_image(grid_items, item_images, font_path="C:/Windows/Fonts/arial.ttf"):
    """Получает изображение из кеша или создает новое"""
    cache_key = get_cache_key(grid_items, item_images)
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    
    # Проверяем есть ли в файловом кеше
    if os.path.exists(cache_path):
        return cache_path
    
    # Создаем новое изображение
    img = render_inventory_grid(grid_items, item_images, font_path=font_path)
    img.save(cache_path)
    
    # Очистка старого кеша (оставляем только последние 50 изображений)
    cache_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.png')]
    if len(cache_files) > 50:
        cache_files.sort(key=lambda x: os.path.getctime(os.path.join(CACHE_DIR, x)))
        for old_file in cache_files[:-50]:
            try:
                os.remove(os.path.join(CACHE_DIR, old_file))
            except Exception:
                pass
    
    return cache_path

# === СИСТЕМА БИЛЕТОВ ЛОТЕРЕИ ===
def init_tickets_db():
    """Инициализация таблиц для системы билетов"""
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Таблица билетов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            draw_date DATE NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Таблица розыгрышей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_date DATE UNIQUE NOT NULL,
            winner_user_id INTEGER,
            winner_username TEXT,
            total_tickets INTEGER DEFAULT 0,
            prize_amount INTEGER DEFAULT 0,
            draw_time TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''')

    # Таблица для сохранения заранее сгенерированных бонусов по дате
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_meta (
            meta_date DATE PRIMARY KEY,
            bonus INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def get_total_tickets_info():
    """Получить общую информацию о билетах"""
    
    
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    cursor.execute('''
        SELECT COUNT(*), COUNT(*) * 100 
        FROM lottery_tickets 
        WHERE draw_date = ? AND status = 'active'
    ''', (today_kyiv,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result if result else (0, 0)

def get_user_tickets_count(user_id: int):
    """Получить количество билетов пользователя на сегодня"""
    
    
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    cursor.execute('''
        SELECT COUNT(*) 
        FROM lottery_tickets 
        WHERE user_id = ? AND draw_date = ? AND status = 'active'
    ''', (user_id, today_kyiv))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else 0

def get_daily_lottery_bonus():
    """Получает статичный бонус лотереи на указанный день (или сегодня, если не указан).

    Приоритет: если в БД (messages DB) для даты уже сохранён бонус, возвращаем его.
    Это позволяет сгенерировать и зафиксировать бонус сразу после розыгрыша, чтобы
    пользователи видели новый бонус для следующего дня сразу, а не с 00:00.
    """
    import random
    import datetime

    # Поддерживаем опциональный аргумент даты через глобалную переменную "_override_date"
    # (совместимость с вызовами без аргументов сохранена)
    # Но удобнее: если вызывающий хочет бонус для конкретной даты, он может передать
    # строку даты в формате YYYY-MM-DD через временную глоб. Перепределять это не нужно
    # в большинстве вызовов; для наших нужд мы добавим вспомогательные функции ниже.

    today = datetime.date.today()

    # Попытка получить сохранённый бонус из messages DB для сегодня
    try:
        stored = get_stored_lottery_bonus_for_date(today.isoformat())
        if stored is not None:
            return int(stored)
    except Exception:
        # Если что-то с БД, падаем дальше к проверке розыгрыша/генерации
        pass

    # Если розыгрыш за сегодня уже проведён, попробуем вернуть сохранённый бонус для завтра
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT status FROM lottery_draws WHERE draw_date = ?', (today.isoformat(),))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] in ('drawn', 'done', 'finished'):
            # Возвращаем сохранённый бонус для следующего дня, если он есть
            tomorrow = (today + datetime.timedelta(days=1)).isoformat()
            try:
                tb = get_stored_lottery_bonus_for_date(tomorrow)
                if tb is not None:
                    return int(tb)
            except Exception:
                pass
    except Exception:
        pass

    # Если в БД нет сохранённого бонуса для сегодня — генерируем детерминированно
    seed = int(today.strftime("%Y%m%d"))  # Например: 20251001
    random.seed(seed)
    chance = random.random()

    if chance < 0.7:  # 70% шанс - низкий бонус (1000-3000)
        daily_bonus = random.randint(1000, 3000)
    elif chance < 0.9:  # 20% шанс - средний бонус (2000-3000)
        daily_bonus = random.randint(2000, 3000)
    elif chance < 0.97:  # 7% шанс - высокий бонус (3000-4500)
        daily_bonus = random.randint(3000, 4500)
    else:  # 3% шанс - очень высокий бонус (4000-5000)
        daily_bonus = random.randint(4000, 5000)

    random.seed()
    return daily_bonus


def get_stored_lottery_bonus_for_date(date_str: str):
    """Возвращает сохранённый бонус (int) для даты YYYY-MM-DD либо None."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT bonus FROM lottery_meta WHERE meta_date = ?', (date_str,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def set_stored_lottery_bonus_for_date(date_str: str, bonus: int):
    """Сохраняет/перезаписывает бонус для даты (YYYY-MM-DD) в messages DB."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO lottery_meta (meta_date, bonus) VALUES (?, ?)', (date_str, int(bonus)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Не удалось сохранить бонус для {date_str}: {e}")
        return False


def generate_deterministic_lottery_bonus_for_date(date_obj):
    """Генерирует детерминированный бонус для переданного date объектa (datetime.date).

    Использует тот же алгоритм, что и get_daily_lottery_bonus, но без проверки БД.
    """
    import random
    try:
        d = date_obj
        seed = int(d.strftime("%Y%m%d"))
    except Exception:
        import datetime
        d = datetime.date.today()
        seed = int(d.strftime("%Y%m%d"))

    random.seed(seed)
    chance = random.random()
    if chance < 0.7:
        daily_bonus = random.randint(1000, 3000)
    elif chance < 0.9:
        daily_bonus = random.randint(2000, 3000)
    elif chance < 0.97:
        daily_bonus = random.randint(3000, 4500)
    else:
        daily_bonus = random.randint(4000, 5000)
    random.seed()
    return daily_bonus

def buy_lottery_ticket(user_id: int, username: str):
    """Купить билет лотереи"""
    
    
    # Проверяем, есть ли достаточно денег
    user = db.get_user(user_id)
    if not user:
        return False, "Пользователь не найден"
    
    dan_balance = float(user.get("dan", 0))
    if dan_balance < 100:
        return False, "Недостаточно средств"
    
    # Проверяем лимит билетов (максимум 10)
    user_tickets = get_user_tickets_count(user_id)
    if user_tickets >= 10:
        return False, "Достигнут максимум билетов (10)"
    
    # Списываем деньги
    from database import set_dan
    set_dan(user_id, dan_balance - 100)
    
    # Добавляем билет
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время для определения draw_date
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    cursor.execute('''
        INSERT INTO lottery_tickets (user_id, username, draw_date)
        VALUES (?, ?, ?)
    ''', (user_id, username, today_kyiv))
    
    conn.commit()
    conn.close()
    
    return True, "Билет успешно куплен!"

def cleanup_old_tickets():
    """Очистка старых билетов и розыгрышей (используя киевское время)"""
    
    
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    # Удаляем разыгранные билеты за вчерашний день и раньше
    cursor.execute('''
        DELETE FROM lottery_tickets 
        WHERE draw_date < ? AND status = 'drawn'
    ''', (today_kyiv,))
    
    drawn_deleted = cursor.rowcount
    print(f"🧹 Удалено {drawn_deleted} разыгранных билетов")
    
    # Удаляем старые активные билеты (которые не были разыграны вчера)
    cursor.execute('''
        DELETE FROM lottery_tickets 
        WHERE draw_date < ? AND status = 'active'
    ''', (today_kyiv,))
    
    active_deleted = cursor.rowcount
    print(f"🧹 Удалено {active_deleted} неразыгранных билетов")
    
    # Оставляем только последние 7 розыгрышей для истории
    cutoff_date = (now_kyiv.date() - datetime.timedelta(days=7)).isoformat()
    cursor.execute('''
        DELETE FROM lottery_draws 
        WHERE draw_date < ?
    ''', (cutoff_date,))
    
    draws_deleted = cursor.rowcount
    print(f"🧹 Удалено {draws_deleted} старых розыгрышей")
    
    conn.commit()
    conn.close()
    
    return drawn_deleted + active_deleted

def get_lottery_statistics():
    """Получить подробную статистику лотереи"""
    
    
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    # Статистика за сегодня
    cursor.execute('''
        SELECT COUNT(*), SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END)
        FROM lottery_tickets 
        WHERE draw_date = ?
    ''', (today_kyiv,))
    
    today_stats = cursor.fetchone() or (0, 0)
    
    # Всего билетов в системе
    cursor.execute('SELECT COUNT(*) FROM lottery_tickets')
    total_tickets = cursor.fetchone()[0]
    
    # Количество уникальных игроков за сегодня
    cursor.execute('''
        SELECT COUNT(DISTINCT user_id) 
        FROM lottery_tickets 
        WHERE draw_date = ?
    ''', (today_kyiv,))
    unique_players_today = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'today_total': today_stats[0],
        'today_active': today_stats[1],
        'total_tickets_ever': total_tickets,
        'unique_players_today': unique_players_today
    }

def conduct_lottery_draw():
    """Проводит розыгрыш лотереи и определяет победителя"""
    import random
    import time
    
    
    conn = None
    try:
        # Подключаемся к базе с таймаутом для избежания блокировки
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE, timeout=30.0)
        cursor = conn.cursor()
        
        # Используем киевское время
        kyiv_tz = pytz.timezone('Europe/Kiev')
        now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
        today_kyiv = now_kyiv.date().isoformat()
        
        # Получаем всех участников с их билетами
        cursor.execute('''
            SELECT user_id, username, COUNT(*) as ticket_count
            FROM lottery_tickets 
            WHERE draw_date = ? AND status = 'active'
            GROUP BY user_id, username
        ''', (today_kyiv,))
        
        participants = cursor.fetchall()
        
        if not participants:
            # Используем дневной бонус (теперь может быть от 1000 до 9000)
            bonus = get_daily_lottery_bonus()
            prize_pool = bonus  # Только бонус, так как билетов нет
            print(f"❌ Нет участников лотереи на сегодня")
            print(f"💸 Упущенный бонус составил бы: {prize_pool} дань")
            
            # Если бонус больше 7000 дань, отправляем уведомление всем пользователям
            if prize_pool > 7000:
                return "no_participants_high_prize", 0, prize_pool  
            else:
                return None, 0, prize_pool
        
        total_tickets = sum(ticket_count for _, _, ticket_count in participants)
        # краткая сводка: участников и билетов (лог DEBUG убран)
        
        # Создаем взвешенный список участников
        weighted_participants = []
        for user_id, username, ticket_count in participants:
            weighted_participants.extend([user_id] * ticket_count)
        
        # Выбираем случайного победителя
        winner_user_id = random.choice(weighted_participants)
        
        # Находим информацию о победителе
        winner_info = None
        winner_username = "Unknown"
        winner_ticket_count = 0
        
        for user_id, username, ticket_count in participants:
            if user_id == winner_user_id:
                winner_info = (user_id, username, ticket_count)
                winner_username = username or f"User_{user_id}"
                winner_ticket_count = ticket_count
                break
        
        # Вычисляем призовой фонд = ВСЕ билеты ВСЕХ участников + бонус
        total_base_prize = total_tickets * 100  # Все билеты всех участников
        # Добавляем статичный дневной бонус
        bonus = get_daily_lottery_bonus()
        prize_pool = total_base_prize + bonus
        
        # Логирование призового фонда — свести к одному сообщению
        print(f"🏆 Розыгрыш: участников={len(participants)}, билетов={total_tickets}, призовой фонд={prize_pool} дань")
        
        # Записываем результат розыгрыша (заменяем если уже есть запись на сегодня)
        # Также фиксируем время розыгрыша и помечаем статус как 'drawn'
        draw_time_str = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT OR REPLACE INTO lottery_draws (draw_date, winner_user_id, winner_username, total_tickets, prize_amount, draw_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (today_kyiv, winner_user_id, winner_username, total_tickets, prize_pool, draw_time_str, 'drawn'))
        
        # Помечаем все билеты как разыгранные
        cursor.execute('''
            UPDATE lottery_tickets 
            SET status = 'drawn' 
            WHERE draw_date = ? AND status = 'active'
        ''', (today_kyiv,))
        
        print(f"✅ Помечено {cursor.rowcount} билетов как разыгранные")

        # Сначала фиксируем изменения в лотерейных таблицах, затем начисляем выигрыш,
        # чтобы избежать блокировок БД при параллельной записи
        conn.commit()
        conn.close()
        conn = None

        # Начисляем выигрыш победителю (отдельным соединением после коммита)
        try:
            db.add_dan(winner_user_id, prize_pool)
            print(f"💰 Начислено {prize_pool} дань пользователю {winner_user_id}")
        except Exception as e:
            print(f"❌ Ошибка начисления выигрыша: {e}")

        return winner_info, total_tickets, prize_pool
        
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e):
            print(f"❌ База данных заблокирована, повторяю попытку через 5 секунд...")
            time.sleep(5)
            return None, 0, 0
        else:
            print(f"❌ Ошибка базы данных: {e}")
            return None, 0, 0
            
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            print(f"❌ Розыгрыш уже проводился сегодня")
            # Возвращаем данные существующего розыгрыша
            try:
                # Используем киевское время
                kyiv_tz = pytz.timezone('Europe/Kiev')
                now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
                today_kyiv = now_kyiv.date().isoformat()
                cursor.execute('''
                    SELECT winner_user_id, winner_username, total_tickets, prize_amount
                    FROM lottery_draws WHERE draw_date = ?
                ''', (today_kyiv,))
                result = cursor.fetchone()
                if result:
                    winner_user_id, winner_username, total_tickets, prize_pool = result
                    return (winner_user_id, winner_username, 0), total_tickets, prize_pool
            except Exception:
                pass
        print(f"❌ Ошибка целостности данных: {e}")
        return None, 0, 0
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка при проведении розыгрыша: {e}")
        return None, 0, 0
        
    finally:
        if conn:
            conn.close()

async def send_lottery_results(winner_info, total_tickets, prize_pool):
    """Отправляет сообщение о результатах лотереи всем участникам в ЛС"""
    if not winner_info:
        return
    
    winner_user_id, winner_username, winner_ticket_count = winner_info
    
    # Получаем красивое имя победителя с учетом приватности
    winner_display_name = get_display_name(winner_user_id, winner_username)
    winner_display = format_clickable_name(winner_user_id, winner_display_name)
    
    win_chance = (winner_ticket_count / total_tickets * 100) if total_tickets > 0 else 0
    
    # Вычисляем общую стоимость всех билетов и бонус для отображения
    total_base_prize = total_tickets * 100  # Все билеты всех участников
    bonus = prize_pool - total_base_prize   # Дневной бонус
    
    # Получаем список всех участников лотереи за сегодня
    conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
    cursor = conn.cursor()
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    today_kyiv = now_kyiv.date().isoformat()
    
    cursor.execute('''
        SELECT DISTINCT user_id, username 
        FROM lottery_tickets 
        WHERE draw_date = ? AND status IN ('active', 'drawn')
    ''', (today_kyiv,))
    
    participants = cursor.fetchall()
    conn.close()
    
    # Сообщения для победителя и остальных участников
    winner_message = (
        f"🎉 <b>ПОЗДРАВЛЯЕМ! ВЫ ВЫИГРАЛИ!</b> 🎉\n\n"
        f"🏆 Вы стали победителем лотереи!\n"
        f"🎫 У вас было {winner_ticket_count} билетов из {total_tickets}\n"
        f"📈 Ваш шанс на выигрыш был {win_chance:.1f}%\n\n"
        f"💰 <b>ПОЛНЫЙ ПРИЗОВОЙ ФОНД: {prize_pool:,} Дань 🪙</b>\n"
        f"├ 🎫 За ВСЕ билеты всех участников: {total_base_prize:,} Дань 🪙\n"
        f"└ 🎁 Дневной бонус: {bonus:,} Дань 🪙\n\n"
        f"🎊 ВЫ ЗАБИРАЕТЕ ВСЁ! Деньги уже начислены на ваш баланс!\n"
        f"🎫 Новая лотерея начинается завтра!"
    )
    
    other_message = (
        f"🎲 <b>РЕЗУЛЬТАТЫ ЛОТЕРЕИ</b> 🎲\n\n"
        f"🏆 <b>Победитель:</b> {winner_display}\n"
        f"🎫 <b>Билетов у победителя:</b> {winner_ticket_count} из {total_tickets}\n"
        f"📈 <b>Шанс на выигрыш был:</b> {win_chance:.1f}%\n\n"
        f"💰 <b>ПОЛНЫЙ ПРИЗОВОЙ ФОНД: {prize_pool:,} Дань 🪙</b>\n"
        f"├ 🎫 За ВСЕ билеты всех участников: {total_base_prize:,} Дань 🪙\n"
        f"└ 🎁 Дневной бонус: {bonus:,} Дань 🪙\n\n"
        f"😔 В этот раз не повезло, но не расстраивайтесь!\n"
        f"👑 Победитель забрал ВЕСЬ призовой фонд!\n"
        f"🎫 Новая лотерея начинается завтра!"
    )
    
    # Отправляем сообщения всем участникам
    success_count = 0
    for user_id, username in participants:
        try:
            if user_id == winner_user_id:
                await bot.send_message(user_id, winner_message, parse_mode='HTML')
            else:
                await bot.send_message(user_id, other_message, parse_mode='HTML')
            success_count += 1
            await asyncio.sleep(0.1)  # Небольшая задержка между сообщениями
        except Exception as e:
            print(f"❌ Не удалось отправить результат пользователю {user_id}: {e}")
    
    print(f"✅ Результаты лотереи отправлены {success_count}/{len(participants)} участникам")

async def send_missed_lottery_notification(prize_pool):
    """Отправляет уведомление всем пользователям о пропущенной лотерее с высоким бонусом"""
    
    # Получаем список всех пользователей из базы данных
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users')
        all_users = cursor.fetchall()
        conn.close()
        
        if not all_users:
            print("❌ Нет пользователей в базе данных для уведомления")
            return
            
        missed_message = (
            f"� <b>НЕВЕРОЯТНАЯ УПУЩЕННАЯ ВОЗМОЖНОСТЬ!</b> �\n\n"
            f"🎰 Сегодня в лотерее не было участников!\n"
            f"💸 Упущенный МЕГА-БОНУС составил: <b>{prize_pool:,} Дань 🪙</b>\n\n"
            f"⚡ Это был РЕДКИЙ высокий бонус!\n"
            f"� Шанс такого большого приза выпадает очень редко!\n\n"
            f"😭 А ведь ты мог поставить всего 100 Дань 🪙\n"
            f"🏆 И забрать целых {prize_pool:,} Дань 🪙!\n\n"
            f"🔥 Такие суммы бывают крайне редко!\n"
            f"🎫 Не упусти следующий шанс!\n"
            f"📝 Купи билет командой: /ticket"
        )
        
        # Отправляем уведомления всем пользователям
        success_count = 0
        for (user_id,) in all_users:
            try:
                await bot.send_message(user_id, missed_message, parse_mode='HTML')
                success_count += 1
                await asyncio.sleep(0.1)  # Небольшая задержка между сообщениями
            except Exception as e:
                print(f"❌ Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        print(f"✅ Уведомления о пропущенной лотерее отправлены {success_count}/{len(all_users)} пользователям")
        
    except Exception as e:
        print(f"❌ Ошибка при отправке уведомлений о пропущенной лотерее: {e}")


def get_lottery_history_for_date(date_str: str):
    """Возвращает историю лотереи для даты: запись розыгрыша, агрегированные билеты и последние покупки.

    Возвращает кортеж: (draw_row_or_None, aggregated_list, recent_tickets_list)
    - draw_row_or_None: (draw_date, winner_user_id, winner_username, total_tickets, prize_amount, draw_time, status) или None
    - aggregated_list: [(user_id, username, ticket_count), ...] отсортирован по ticket_count desc
    - recent_tickets_list: [(user_id, username, purchase_date), ...] (последние 100 записей по времени)
    """
    try:
        import datetime
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT draw_date, winner_user_id, winner_username, total_tickets, prize_amount, draw_time, status
            FROM lottery_draws WHERE draw_date = ?
        ''', (date_str,))
        draw_row = cursor.fetchone()

        cursor.execute('''
            SELECT user_id, username, COUNT(*) as cnt
            FROM lottery_tickets
            WHERE draw_date = ?
            GROUP BY user_id, username
            ORDER BY cnt DESC
            LIMIT 50
        ''', (date_str,))
        agg = cursor.fetchall()

        cursor.execute('''
            SELECT user_id, username, purchase_date
            FROM lottery_tickets
            WHERE draw_date = ?
            ORDER BY purchase_date DESC
            LIMIT 100
        ''', (date_str,))
        recent = cursor.fetchall()

        conn.close()
        return draw_row, agg, recent
    except Exception as e:
        print(f"❌ Ошибка получения истории лотереи для {date_str}: {e}")
        return None, [], []


@dp.message(Command("lottery_history"))
async def cmd_lottery_history(message: types.Message):
    """Показывает историю лотереи за сегодня (розыгрыш + билеты).

    Команда удобна для администрации — показывает агрегированную информацию и последние покупки.
    """
    # Для безопасности ограничим показ владельцем бота — если нужно, можно снять проверку
    try:
        owner_id = getattr(bot, 'owner_id', None)
    except Exception:
        owner_id = None

    # Если задан owner_id, разрешаем только ему, иначе показываем всем (на ваше усмотрение)
    if owner_id and message.from_user and message.from_user.id != owner_id:
        await message.reply("❌ Доступно только владельцу бота.")
        return

    import datetime
    import pytz
    
    # Используем киевское время
    kyiv_tz = pytz.timezone('Europe/Kiev')
    now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
    date_str = now_kyiv.date().isoformat()
    
    draw_row, agg, recent = get_lottery_history_for_date(date_str)

    lines = [f"📜 История лотереи за {date_str}"]
    if draw_row:
        dd, winner_id, winner_username, total_tickets, prize_amount, draw_time, status = draw_row
        lines.append(f"🏆 Розыгрыш: статус={status}, победитель={winner_username or winner_id}, билетов={total_tickets}, приз={prize_amount}")
    else:
        lines.append("ℹ️ Розыгрыш на эту дату отсутствует в БД.")

    lines.append("")
    lines.append("🔎 Топ участников (аггрегировано по билетам):")
    if not agg:
        lines.append("— Нет купленных билетов —")
    else:
        for user_id, username, cnt in agg:
            uname = username or f"User_{user_id}"
            lines.append(f"{uname} ({user_id}) — {cnt} билет(ов)")

    lines.append("")
    lines.append("🕘 Последние покупки (до 100):")
    if not recent:
        lines.append("— Нет записей о покупках —")
    else:
        for user_id, username, purchase_date in recent[:20]:
            uname = username or f"User_{user_id}"
            lines.append(f"{purchase_date} — {uname} ({user_id})")

    text = "\n".join(lines)
    # Если сообщение слишком длинное, отправляем как файл
    if len(text) > 4000:
        import tempfile, os
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
            tmp.write(text.encode('utf-8'))
            tmp_path = tmp.name
            tmp.close()
            try:
                await message.answer_document(FSInputFile(tmp_path))
            except Exception:
                await message.reply("❌ Не удалось отправить файл с историей лотереи.")
        finally:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    else:
        await message.reply(text)

# Helper: ensure user with safe username (avoid passing None to DB helpers)
def safe_ensure_user(user_id: int, username: str | None, first_name: str | None = None, last_name: str | None = None):
    try:
        db.ensure_user(user_id, username, None, first_name, last_name)
    except Exception:
        # best-effort; ignore errors here
        pass

def safe_ensure_user_from_obj(user_obj):
    """Удобная функция для добавления пользователя из объекта Telegram User"""
    if not user_obj:
        return
    try:
        user_id = user_obj.id
        first_name = getattr(user_obj, 'first_name', None)
        last_name = getattr(user_obj, 'last_name', None) 
        username = getattr(user_obj, 'username', None)
        
        safe_ensure_user(user_id, username, first_name, last_name)
    except Exception:
        pass


# --- DAILY BONUS SYSTEM ---
DAILY_CHANNEL = "@GameNEwKruz"

def get_daily_record(user_id: int):
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cur = conn.cursor()
        cur.execute('SELECT user_id, streak, last_claim_date FROM daily_claims WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {'user_id': row[0], 'streak': row[1] or 0, 'last_claim_date': row[2]}
        return None
    except Exception:
        return None


def get_daily_message_text():
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cur = conn.cursor()
        cur.execute('SELECT value FROM daily_config WHERE key = ?', ('message_text',))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        print(f"❌ Не удалось получить daily message text: {e}")
    # Fallback default
    return (
        "🎁 <b>Ежедневный бонус KRUZ</b> — собери серию из 7 дней! 🎯\n\n"
        "🔹 Каждый день бонус растет: 100 ➕50 ➡️ максимум 500 дань\n"
        "🔸 Для получения — подпишись на канал и нажми на текущий день.\n\n"
        "🔥 Не пропускай — чем дольше серия, тем больше награда! 💪\n"
        "📅 Нажми на номер дня, чтобы получить награду."
    )


def log_daily_claim(user_id: int, streak: int, bonus: int):
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cur = conn.cursor()
        today_iso = datetime.date.today().isoformat()
        cur.execute('INSERT INTO daily_claim_logs (user_id, claim_date, streak, bonus) VALUES (?, ?, ?, ?)', (user_id, today_iso, streak, bonus))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Не удалось залогировать daily claim: {e}")
        return False

def upsert_daily_record(user_id: int, streak: int, last_claim_date: str):
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cur = conn.cursor()
        cur.execute('INSERT OR REPLACE INTO daily_claims (user_id, streak, last_claim_date) VALUES (?, ?, ?)', (user_id, streak, last_claim_date))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Не удалось записать daily_claims: {e}")
        return False

def compute_daily_bonus_for_streak(streak: int) -> int:
    # streak: 1 -> 100, 2 -> 150, 3 -> 200 ... increments by 50 per day, cap at 500
    base = 100 + 50 * (max(1, streak) - 1)
    return min(base, 500)

async def check_channel_membership(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал DAILY_CHANNEL."""
    try:
        member = await bot.get_chat_member(DAILY_CHANNEL, user_id)
        status = getattr(member, 'status', '') or ''
        return status in ('creator', 'administrator', 'member')
    except Exception:
        # по безопасности разрешаем действие (чтобы не блокировать пользователей).
        # Но логируем для отладки.
        print(f"⚠️ Не удалось проверить подписку пользователя {user_id} на канал {DAILY_CHANNEL}")
        return False

def build_daily_keyboard(user_id: int, record: dict | None):
    # record may be None or dict(user_id, streak, last_claim_date)
    today_iso = datetime.date.today().isoformat()

    streak = record.get('streak', 0) if record else 0
    last_claim = record.get('last_claim_date') if record else None

    # Build button rows explicitly (aiogram InlineKeyboardMarkup expects inline_keyboard list)
    # Create day buttons all in a single row
    day_row = []
    for day in range(1, 8):
        text = str(day)
        if streak >= day and last_claim == today_iso:
            btn = InlineKeyboardButton(text=f"{text} ✅", callback_data=f"daily_claimed:{day}:{user_id}")
        else:
            btn = InlineKeyboardButton(text=text, callback_data=f"daily_claim:{day}:{user_id}")
        day_row.append(btn)

    # Close button in the second row
    close_row = [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"daily_close:{user_id}")]

    inline_keyboard = [day_row, close_row]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


@dp.message(Command("daily"))
async def cmd_daily(message: types.Message):
    user_id = message.from_user.id
    # Check channel membership
    try:
        member = await bot.get_chat_member(DAILY_CHANNEL, user_id)
        if getattr(member, 'status', '') not in ('creator', 'administrator', 'member'):
            # Not subscribed
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{DAILY_CHANNEL.lstrip('@')}")], [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"daily_close:{user_id}")]])
            await message.answer("⛔ Для получения ежедневного бонуса необходимо подписаться на канал.", reply_markup=kb)
            return
    except Exception:
        # If checking fails, inform user to subscribe (fail-safe)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть канал", url=f"https://t.me/{DAILY_CHANNEL.lstrip('@')}")], [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"daily_close:{user_id}")]])
        await message.answer("⛔ Не удалось проверить подписку. Пожалуйста, подпишитесь на канал и попробуйте снова.", reply_markup=kb)
        return

    # Build and send keyboard with current claim state
    record = get_daily_record(user_id)
    kb = build_daily_keyboard(user_id, record)
    await message.answer("🎁 Ежедневный бонус — соберите 7 дней подряд. Бонус растет: 100 -> +50 каждый день, максимум 500.", reply_markup=kb)


@dp.callback_query(lambda c: c.data and (c.data.startswith("daily_claim:") or c.data.startswith("daily_close:") or c.data.startswith("daily_claimed:")))
async def daily_callback_handler(callback: types.CallbackQuery):
    data = callback.data or ""
    parts = data.split(":")
    action = parts[0]
    try:
        day = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        owner_id = int(parts[-1]) if parts[-1].isdigit() else None
    except Exception:
        await callback.answer("Неверный callback", show_alert=True)
        return

    if owner_id != callback.from_user.id:
        await callback.answer("Это не ваше меню", show_alert=True)
        return

    if action == 'daily_close':
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.answer("Закрыто", show_alert=False)
            except Exception:
                pass
        return

    if action == 'daily_claimed':
        await callback.answer("День уже взят", show_alert=True)
        return

    # action == daily_claim
    today = datetime.date.today()
    today_iso = today.isoformat()
    record = get_daily_record(owner_id)

    # Prevent double-claim: if last_claim_date is today -> already claimed
    if record and record.get('last_claim_date') == today_iso:
        await callback.answer("Вы уже получили сегодня бонус", show_alert=True)
        # refresh keyboard
        kb = build_daily_keyboard(owner_id, record)
        await safe_edit_message(callback, "🎁 Ежедневный бонус — соберите 7 дней подряд.", reply_markup=kb)
        return

    # Determine new streak: if last_claim_date == yesterday -> streak+1 else reset to 1
    new_streak = 1
    if record and record.get('last_claim_date'):
        try:
            last_date = datetime.date.fromisoformat(record.get('last_claim_date'))
            if (today - last_date).days == 1:
                new_streak = (record.get('streak', 0) or 0) + 1
            else:
                new_streak = 1
        except Exception:
            new_streak = 1

    # Compute bonus and award
    bonus = compute_daily_bonus_for_streak(new_streak)
    try:
        db.add_dan(owner_id, bonus)
    except Exception as e:
        print(f"❌ Ошибка начисления daily бонуса: {e}")
        await callback.answer("Ошибка начисления, попробуйте позже", show_alert=True)
        return

    # Update record
    upsert_daily_record(owner_id, new_streak, today_iso)

    # Reply and update keyboard to show claimed
    await callback.answer(f"Вы получили {bonus} дань! (день {new_streak})", show_alert=True)
    record = get_daily_record(owner_id)
    kb = build_daily_keyboard(owner_id, record)
    await safe_edit_message(callback, f"🎉 Вы получили {bonus} дань! Следующий день — больший бонус.", reply_markup=kb)


# === КОМАНДА /task - ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ===
@dp.message(Command("task"))
async def cmd_task(message: types.Message):
    """Показывает список ежедневных заданий"""
    user_id = message.from_user.id
    
    # Получаем текст с заданиями
    task_text = tasks.format_tasks_text(user_id)
    
    # Создаем клавиатуру с кнопками для получения наград
    user_tasks = tasks.get_user_tasks(user_id)
    buttons = []
    
    for i, task in enumerate(user_tasks, 1):
        if task['completed'] and not task['claimed']:
            # Можно забрать награду
            buttons.append([InlineKeyboardButton(
                text=f"🎁 Получить награду за задание {i}",
                callback_data=f"task_claim:{task['id']}:{user_id}"
            )])
    
    # Кнопка обновления и закрытия
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"task_refresh:{user_id}"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data=f"task_close:{user_id}")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(task_text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(lambda c: c.data and c.data.startswith("task_"))
async def task_callback_handler(callback: types.CallbackQuery):
    """Обработчик callback'ов для системы заданий"""
    data = callback.data or ""
    parts = data.split(":")
    action = parts[0]
    
    # Проверка владельца
    try:
        owner_id = int(parts[-1])
    except Exception:
        await safe_callback_answer(callback, "Ошибка данных", show_alert=True)
        return
    
    if owner_id != callback.from_user.id:
        await safe_callback_answer(callback, "Это не ваше меню", show_alert=True)
        return
    
    # Закрытие меню
    if action == "task_close":
        try:
            await callback.message.delete()
        except Exception:
            await safe_callback_answer(callback, "Закрыто", show_alert=False)
        return
    
    # Обновление списка заданий
    if action == "task_refresh":
        task_text = tasks.format_tasks_text(owner_id)
        user_tasks = tasks.get_user_tasks(owner_id)
        buttons = []
        
        for i, task in enumerate(user_tasks, 1):
            if task['completed'] and not task['claimed']:
                buttons.append([InlineKeyboardButton(
                    text=f"🎁 Получить награду за задание {i}",
                    callback_data=f"task_claim:{task['id']}:{owner_id}"
                )])
        
        buttons.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"task_refresh:{owner_id}"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"task_close:{owner_id}")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        # Используем безопасное редактирование, чтобы игнорировать 'message is not modified'
        edit_ok = await safe_edit_message(callback, task_text, reply_markup=kb, parse_mode="HTML")
        if edit_ok:
            await safe_callback_answer(callback, "Обновлено", show_alert=False)
        return
    
    # Получение награды
    if action == "task_claim":
        try:
            task_id = int(parts[1])
        except Exception:
            await safe_callback_answer(callback, "Ошибка ID задания", show_alert=True)
            return
        
        reward = tasks.claim_task_reward(owner_id, task_id)
        
        if reward is None:
            await safe_callback_answer(callback, "Задание не выполнено или награда уже получена", show_alert=True)
            return
        
        await safe_callback_answer(callback, f"🎉 Вы получили {reward:,} дань!", show_alert=True)
        
        # Обновляем список заданий
        task_text = tasks.format_tasks_text(owner_id)
        user_tasks = tasks.get_user_tasks(owner_id)
        buttons = []
        
        for i, task in enumerate(user_tasks, 1):
            if task['completed'] and not task['claimed']:
                buttons.append([InlineKeyboardButton(
                    text=f"🎁 Получить награду за задание {i}",
                    callback_data=f"task_claim:{task['id']}:{owner_id}"
                )])
        
        buttons.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"task_refresh:{owner_id}"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"task_close:{owner_id}")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        # Безопасное редактирование после получения награды
        await safe_edit_message(callback, task_text, reply_markup=kb, parse_mode="HTML")


# --- Лотерейные помощники (глобальные) ---
def build_lottery_keyboard(owner_id: int):
    cnt = get_user_tickets_count(owner_id)
    if cnt >= 10:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_id}")]])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 КУПИТЬ БИЛЕТ", callback_data=f"buy_ticket:{owner_id}"), InlineKeyboardButton(text="🧺 ДОКУПИТЬ ДО 10", callback_data=f"buy_to_10:{owner_id}")],
        [InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_id}")]
    ])


def render_lottery_text(owner_id: int, status_msg: str | None = None):
    total_tickets_sold, total_tickets_value = get_total_tickets_info()
    user_tickets_count = get_user_tickets_count(owner_id)
    win_chance = (user_tickets_count / total_tickets_sold * 100) if total_tickets_sold > 0 else 0
    user = db.get_user(owner_id)
    dan_balance = float(user.get("dan", 0)) if user else 0
    spent_today = user_tickets_count * 100
    balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань (-{spent_today} дань потрачено сегодня)" if spent_today > 0 else f"💰 Ваш баланс: {dan_balance:,.0f} дань"
    preview_bonus = get_daily_lottery_bonus()
    status_block = f"✅ {status_msg}\n\n" if status_msg else ""
    text = (
        f"🎫 <b>ЛОТЕРЕЯ KRUZCHAT</b> 🎫\n\n"
        f"{status_block}"
        f"📊 <b>Статистика:</b>\n"
        f"🎟️ Сейчас куплено {total_tickets_sold} билетов, на {total_tickets_value:,.0f} дань\n\n"
        f"🎯 <b>Ваши шансы:</b>\n"
        f"📈 Шанс на выигрыш {win_chance:.1f}%\n"
        f"🎫 У вас {user_tickets_count} билетов (максимум 10)\n"
        f"🎁 Сегодня бонус +{preview_bonus:,} дань к призовому фонду!\n"
        f"{balance_text}\n\n"
        f"💰 <b>Условия:</b>\n"
        f"💵 Цена 1 билета: 100 дань\n"
        f"🕛 Ровно в 21:00 рандомно будет выбран победитель\n"
        f"🏆 Победитель получает ВСЕ!"
    )
    keyboard = build_lottery_keyboard(owner_id)
    return text, keyboard

# ID администратора (замените на свой Telegram user_id)
ADMIN_ID = 1425069841  # TODO: замените на ваш реальный user_id

# Универсальная функция для проверки устаревших callback'ов
async def check_callback_validity(callback):
    """
    Проверяет, не устарел ли callback.
    Возвращает True если callback действителен, False если устарел.
    """
    try:
        await callback.answer()
        return True
    except Exception as e:
        error_msg = str(e).lower()
        if "query is too old" in error_msg or "query id is invalid" in error_msg:
            print(f"Устаревший callback: {e}")
            return False
        # Если другая ошибка, считаем что callback действителен
        return True

# Универсальная функция для безопасного редактирования сообщений
async def safe_edit_message(callback, text, reply_markup=None, parse_mode=None):
    """Безопасное редактирование сообщения с обработкой ошибки 'message is not modified'"""
    try:
        if parse_mode:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            try:
                await callback.answer("Сообщение уже актуально", show_alert=False)
            except Exception:
                print("Callback уже устарел, игнорируем")
        elif "query is too old" in error_msg or "query id is invalid" in error_msg:
            print(f"Callback устарел: {e}")
            # Не пытаемся отвечать на устаревший callback
            return False
        else:
            print(f"Ошибка редактирования сообщения: {e}")
            try:
                await callback.answer("Произошла ошибка", show_alert=False)
            except Exception:
                print("Не удалось ответить на callback")
        return False
    return True

# Универсальная функция для безопасного ответа на callback (игнорирует просроченные или невалидные query)
async def safe_callback_answer(callback: types.CallbackQuery, text: str | None = None, show_alert: bool = False) -> bool:
    try:
        if text is None:
            await callback.answer()
        else:
            await callback.answer(text, show_alert=show_alert)
        return True
    except Exception as e:
        error = str(e).lower()
        if "query is too old" in error or "query id is invalid" in error:
            # Нельзя ответить — callback устарел. Просто игнорируем.
            return False
        # Другие ошибки — логируем и не валим поток
        try:
            print(f"safe_callback_answer error: {e}")
        except Exception:
            pass
        return False

class CreateBetStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_options = State()

# FSM для банковской системы
class BankStates(StatesGroup):
    waiting_for_direct_deposit_amount = State()  # Состояние для ввода суммы после выбора плана
    confirming_deposit = State()  # Состояние для подтверждения депозита

# --- Реферальная система ---
REF_DB_FOLDER = os.path.join(os.path.dirname(__file__), "database")
os.makedirs(REF_DB_FOLDER, exist_ok=True)
# Единый файл БД для всех систем (кроме арены): используем DB_PATH из database.py
from database import DB_PATH as _MAIN_DB_PATH
DATABASE_FILE = _MAIN_DB_PATH
# Ранее лотерея/ежедневки/логи использовали messages.db; теперь указываем на основной DB
MESSAGES_DB_FILE_FILE = _MAIN_DB_PATH

# Функции для работы с верификацией
def get_verification_level(user_id: int) -> int:
    """Получить уровень верификации пользователя (0, 1, 2, 3)"""
    user = db.get_user(user_id)
    if not user:
        return 0
    
    # Базовая верификация - всем 1/3
    verification_level = 1
    
    # Проверяем прокачку фермы на 500+ дань для 2/3
    farm_level = user.get('farm_level', 1)
    if farm_level >= 2:  # Если ферма прокачана до 2 уровня (стоимость 500 дань)
        verification_level = 2
    
    return verification_level

def get_verification_status(user_id: int) -> str:
    """Получить строку статуса верификации"""
    level = get_verification_level(user_id)
    if level >= 2:
        return "✅✅⬜ 2/3"
    elif level >= 1:
        return "✅⬜⬜ 1/3"
    else:
        return "⬜⬜⬜ 0/3"

# Инициализируем connection pool после определения DATABASE_FILE
try:
    if 'db_pool' not in locals() or db_pool is None:
        db_pool = DBConnectionPool(DATABASE_FILE, max_connections=10)
        print("✅ Пул соединений с базой данных создан успешно")
except Exception as e:
    print(f"❌ Ошибка создания пула соединений: {e}")
    db_pool = None


# Импорт новых функций из database.py
from database import create_tables as db_create_tables, add_user as db_add_user, set_referrer as db_set_referrer

# Обертки для новых функций, чтобы использовать их с текущими глобальными переменными
def create_tables():
    db_create_tables(db_pool=db_pool, DATABASE_FILE=DATABASE_FILE, MESSAGES_DB_FILE_FILE=MESSAGES_DB_FILE_FILE, _tasks=globals().get('_tasks'))

async def add_user(user_id: int, username: str):
    await db_add_user(user_id, username, db_pool=db_pool, DATABASE_FILE=DATABASE_FILE)

async def set_referrer(user_id: int, referrer_id: int):
    return await db_set_referrer(user_id, referrer_id, db_pool=db_pool, _tasks=globals().get('_tasks'))

async def get_referral_link(user_id: int):
    me = await bot.get_me()
    bot_username = me.username
    return f"https://t.me/{bot_username}?start={user_id}"

async def get_user(user_id: int):
    if not db_pool:
        return None
    result = db_pool.execute_one("SELECT user_id, username, referrer_id, referrals_count FROM users WHERE user_id = ?", (user_id,))
    return result

async def get_referrals(user_id: int):
    if not db_pool:
        return []
    result = db_pool.execute_query("SELECT user_id, username FROM users WHERE referrer_id = ?", (user_id,))
    return result

# === СИСТЕМА КАСТОМНЫХ ИМЕН ===

def set_custom_name(user_id: int, custom_name: str) -> bool:
    """Устанавливает кастомное имя для пользователя"""
    try:
        if not db_pool:
            return False
        
        # Проверяем длину имени (3-20 символов)
        if not custom_name or len(custom_name) < 3 or len(custom_name) > 20:
            return False
        
        # Очищаем имя от небезопасных символов
        import re
        safe_name = re.sub(r'[<>"]', '', custom_name.strip())
        if not safe_name:
            return False
        
        # Сохраняем или обновляем кастомное имя
        db_pool.execute_query('''
            INSERT OR REPLACE INTO custom_names (user_id, custom_name, set_date) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, safe_name))
        
        return True
    except Exception as e:
        print(f"Ошибка установки кастомного имени: {e}")
        return False

def get_custom_name(user_id: int) -> str | None:
    """Получает кастомное имя пользователя"""
    try:
        if not db_pool:
            return None
        
        result = db_pool.execute_one("SELECT custom_name FROM custom_names WHERE user_id = ?", (user_id,))
        return result[0] if result else None
    except Exception:
        return None

def get_display_name(user_id_or_user: Union[int, types.User], username: Optional[str] = None) -> str:
    """Получает отображаемое имя пользователя (кастомное или настоящее)"""
    import random
    
    # Определяем user_id в зависимости от типа входного параметра
    if isinstance(user_id_or_user, int):
        user_id = user_id_or_user
        user_obj = None
    elif hasattr(user_id_or_user, 'id'):
        user_id = user_id_or_user.id
        user_obj = user_id_or_user
    else:
        return "Неизвестный"
    
    try:
        # Сначала пытаемся получить кастомное имя
        custom_name = get_custom_name(user_id)
        if custom_name:
            # Проверяем длину кастомного имени (минимум 3 символа)
            if len(custom_name.strip()) < 3:
                # Генерируем стабильное случайное число на основе user_id
                random.seed(user_id)
                player_num = random.randint(1, 100)
                return f"Игрок {player_num:03d}"
            # Обрезаем до 20 символов если нужно
            return custom_name[:20] if len(custom_name) > 20 else custom_name
        
        # Если есть объект пользователя, используем его данные
        display_name = ""
        if user_obj:
            if user_obj.first_name:
                full_name = user_obj.first_name
                if user_obj.last_name:
                    full_name += f" {user_obj.last_name}"
                display_name = full_name
            elif user_obj.username:
                display_name = user_obj.username
        
        # Иначе пытаемся получить данные из базы
        if not display_name:
            user_data = db.get_user(user_id)
            if user_data:
                first_name = user_data.get('first_name', '')
                last_name = user_data.get('last_name', '')
                
                if first_name:
                    full_name = first_name
                    if last_name:
                        full_name += f" {last_name}"
                    display_name = full_name
                else:
                    db_username = user_data.get('username', '')
                    if db_username:
                        display_name = db_username
        
        # Если передан username как параметр
        if not display_name and username:
            display_name = username
        
        # Проверяем длину итогового имени (минимум 3 символа)
        if display_name and len(display_name.strip()) >= 3:
            # Обрезаем до 20 символов если нужно
            return display_name[:20] if len(display_name) > 20 else display_name
        
        # Если имя слишком короткое или отсутствует - генерируем "Игрок XXX"
        random.seed(user_id)
        player_num = random.randint(1, 100)
        return f"Игрок {player_num:03d}"
        
    except Exception:
        # В случае ошибки тоже генерируем стабильное имя
        random.seed(user_id)
        player_num = random.randint(1, 100)
        return f"Игрок {player_num:03d}"

def get_profile_privacy(user_id: int) -> bool:
    """Получает настройку приватности профиля пользователя (True = разрешить ссылки)"""
    try:
        # Используем основную базу данных MESSAGES_DB_FILE вместо реферальной
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        
        # Создаем таблицу если не существует
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profile_privacy (
                user_id INTEGER PRIMARY KEY,
                allow_profile_link INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute("SELECT allow_profile_link FROM profile_privacy WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return bool(result[0])
        
        # По умолчанию разрешаем ссылки на профиль
        return True
    except Exception as e:
        print(f"Ошибка получения настроек приватности: {e}")
        return True

def set_profile_privacy(user_id: int, allow_links: bool) -> bool:
    """Устанавливает настройку приватности профиля"""
    try:
        allow_value = 1 if allow_links else 0
        
        # Используем основную базу данных MESSAGES_DB_FILE
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        
        # Создаем таблицу если не существует
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profile_privacy (
                user_id INTEGER PRIMARY KEY,
                allow_profile_link INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            INSERT OR REPLACE INTO profile_privacy (user_id, allow_profile_link, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, allow_value))
        
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Ошибка установки приватности профиля: {e}")
        return False

def format_clickable_name(user_id_or_user: Union[int, types.User], display_name: Optional[str] = None) -> str:
    """Форматирует кликабельное имя пользователя для HTML с учетом настроек приватности"""
    # Определяем user_id в зависимости от типа входного параметра
    if isinstance(user_id_or_user, int):
        user_id = user_id_or_user
    elif hasattr(user_id_or_user, 'id'):
        user_id = user_id_or_user.id
    else:
        return "Неизвестный"
    
    try:
        if not display_name:
            display_name = get_display_name(user_id_or_user)
        
        # Обрезаем длинные имена до 15 символов
        if len(display_name) > 15:
            display_name = display_name[:15] + "..."
        
        # Проверяем настройки приватности профиля
        allow_profile_link = get_profile_privacy(user_id)
        
        if allow_profile_link:
            # Создаем кликабельную ссылку
            return f"<a href='tg://user?id={user_id}'>{html.escape(display_name)}</a>"
        else:
            # Возвращаем просто текст без ссылки
            return html.escape(display_name)
    except Exception:
        return f"Игрок №{abs(user_id) % 1000}"

def format_number_beautiful(number) -> str:
    """Форматирует число с пробелами как разделителями тысяч и ВСЕГДА показывает .00"""
    if isinstance(number, str):
        try:
            number = float(number)
        except ValueError:
            return str(number)
    
    # ВСЕГДА форматируем с 2 знаками после запятой для денежных сумм
    formatted = f"{float(number):.2f}"
    # Разделяем на целую и дробную части
    if "." in formatted:
        integer_part, decimal_part = formatted.split(".")
        # Форматируем целую часть с пробелами
        integer_formatted = f"{int(integer_part):,}".replace(",", " ")
        return f"{integer_formatted}.{decimal_part}"
    else:
        return f"{int(float(formatted)):,}".replace(",", " ") + ".00"

def create_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню"""
    # Проверяем наличие наград за уровни
    try:
        xp_data = get_user_xp_data(user_id)
        pending_rewards = xp_data.get('pending_level_rewards', 0)
    except:
        pending_rewards = 0
    
    # Первая строка - АРЕНА и опционально кнопка призов
    first_row = [InlineKeyboardButton(text="🎮 АРЕНА", callback_data=f"play_games:{user_id}")]
    if pending_rewards > 0:
        first_row.append(InlineKeyboardButton(
            text=f"🎁 Забрать приз ({pending_rewards} шт)", 
            callback_data=f"arena_claim_level_reward:{user_id}"
        ))
    
    return InlineKeyboardMarkup(inline_keyboard=[
        first_row,
        [
            InlineKeyboardButton(text="🌾 Ферма", callback_data=f"menu_ferma:{user_id}"),
            InlineKeyboardButton(text="👤 Профиль", callback_data=f"menu_profile:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🏛 Аукцион", callback_data=f"menu_auction:{user_id}"),
            InlineKeyboardButton(text="🛍 Магазин", callback_data=f"menu_shop:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🎒 Инвентарь", callback_data=f"menu_inventory:{user_id}"),
            InlineKeyboardButton(text="🏆 Топ", callback_data=f"menu_tops:{user_id}")
        ]
    ])

def prepare_main_menu_image():
    """Подготавливает изображение статистики для главного меню"""
    count = get_today_games_count()
    base_path = "C:/BotKruz/ChatBotKruz/photo/nulls.png"
    out_path = "C:/BotKruz/ChatBotKruz/photo/stat_temp.png"
    make_stat_image(count, base_path, out_path)
    return out_path

async def show_main_menu(target, user_id: int):
    """
    Универсальная функция показа главного меню
    target может быть Message или CallbackQuery
    """
    out_path = prepare_main_menu_image()
    menu_kb = create_main_menu_keyboard(user_id)
    caption = "🎮 Главное меню игры"
    
    # Определяем тип target и отправляем меню
    if hasattr(target, 'answer_photo'):  # Message
        try:
            await target.answer_photo(
                photo=FSInputFile(out_path), 
                caption=caption, 
                reply_markup=menu_kb
            )
        except Exception:
            await target.answer(caption, reply_markup=menu_kb)
    elif hasattr(target, 'message'):  # CallbackQuery
        try:
            await target.message.edit_media(
                media=InputMediaPhoto(media=FSInputFile(out_path), caption=caption),
                reply_markup=menu_kb
            )
        except Exception:
            try:
                await target.message.edit_caption(caption=caption, reply_markup=menu_kb)
            except Exception:
                await target.answer("Меню открыто")

def create_back_button(callback_data: str, text: str = "🏠 Главное меню"):
    """Создает кнопку возврата"""
    return [[InlineKeyboardButton(text=text, callback_data=callback_data)]]

def create_user_specific_button(text: str, callback_prefix: str, user_id: int) -> InlineKeyboardButton:
    """Создает кнопку с привязкой к пользователю"""
    return InlineKeyboardButton(text=text, callback_data=f"{callback_prefix}:{user_id}")

def create_back_to_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой возврата в главное меню с учетом приватности"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"open_game_menu:{user_id}")]
    ])

async def safe_edit_media_or_text(message, text: str = "", media=None, reply_markup=None):
    """Безопасно редактирует медиа или текст сообщения"""
    try:
        if media:
            await message.edit_media(media=media, reply_markup=reply_markup)
        else:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except Exception:
        return False

def ensure_user_from_callback(callback):
    """Регистрирует пользователя из callback"""
    user_id = callback.from_user.id
    username = getattr(callback.from_user, 'username', None)
    safe_ensure_user(user_id, username)
    return user_id, username

def ensure_user_from_message(message):
    """Регистрирует пользователя из message"""
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None)
    safe_ensure_user(user_id, username)
    return user_id, username

# Inline режим: предлагаем готовые команды, чтобы пользователь не ждал
@dp.inline_query()
async def inline_voice_hint(inline_query: InlineQuery):
    query = inline_query.query.strip().lower()
    allowed = {"гс", "текст", "текстом", "gs", "text"}
    if query and query not in allowed:
        await inline_query.answer([], cache_time=0)
        return

    me = await bot.get_me()
    base_command = query if query in allowed else "гс"

    results = []

    # Вариант 1: распознать прямо в этом чате (без ЛС)
    results.append(
        InlineQueryResultArticle(
            id="voice_local",
            title="🎙️ Распознать здесь",
            description="Ответить на голосовое словом 'гс'",
            input_message_content=InputTextMessageContent(message_text=base_command)
        )
    )

    # Вариант 2: переслать голосовое боту и получить текст в ЛС
    if me.username:
        results.append(
            InlineQueryResultArticle(
                id="voice_dm",
                title="📩 Отправить боту (ЛС)",
                description="Бот пришлет текст в личные сообщения",
                input_message_content=InputTextMessageContent(
                    message_text=f"@{me.username} {base_command}"
                )
            )
        )

    await inline_query.answer(results, cache_time=0)

def parse_command_with_value(text: str, commands: list) -> tuple:
    """Парсит команды типа +dan 100, -don 50"""
    for prefix in commands:
        if text.startswith(prefix):
            try:
                value = int(text[len(prefix):].strip())
                operation = "add" if prefix.startswith("+") else "remove"
                return operation, value
            except ValueError:
                break
    return None, None

def safe_split_callback_data(callback_data: str, separator: str = ":") -> list:
    """Безопасно разбивает callback_data"""
    if not callback_data:
        return []
    return callback_data.split(separator)


# Обробник голосових повідомлень в ЛС (для транскрипції)
@dp.message(lambda m: m.chat.type == "private" and m.voice)
async def handle_voice_in_private(message: types.Message):
    """Транскрибує голосове повідомлення в особистих повідомленнях"""
    processing_msg = await message.reply("🎙️ Розпізнаю голосове повідомлення...")
    
    try:
        from plugins.api_soft_ai import transcribe_voice_message
        
        voice_file_id = message.voice.file_id
        transcript = await transcribe_voice_message(bot, voice_file_id)
        
        if transcript:
            result_text = f"🎙️ <b>Розпізнаний текст:</b>\n\n{transcript}"
            await processing_msg.edit_text(result_text, parse_mode="HTML")
        else:
            await processing_msg.edit_text("❌ Не вдалося розпізнати голосове повідомлення. Спробуйте пізніше.")
    
    except Exception as e:
        print(f"❌ Помилка транскрипції: {e}")
        import traceback
        traceback.print_exc()
        try:
            await processing_msg.edit_text("❌ Сталася помилка при розпізнаванні. Спробуйте пізніше.")
        except Exception:
            pass


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    """Команда /menu - открывает главное игровое меню"""
    user_id = message.from_user.id
    await show_main_menu(message, user_id)


@dp.message(CommandStart())
async def cmd_start(message: types.Message, command=None):
    user = message.from_user
    user_id = user.id # type: ignore
    username = user.username or "NoUsername"
    args = []
    if command and hasattr(command, "args") and command.args:
        args = command.args.split()
    # Fallback: если обработчик вызван через alias Command("start"), парсим параметр из message.text
    if not args and getattr(message, 'text', None):
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            # parts[1] может содержать весь параметр deep-link
            args = parts[1].split()
    
    # Перевіряємо чи це запит на транскрипцію голосового
    if args and args[0] == "voice_transcribe":
        await message.answer(
            "🎙️ <b>Розпізнавання голосових повідомлень</b>\n\n"
            "📝 Відправте мені голосове повідомлення, і я розпізнаю його в текст.\n\n"
            "✨ Підтримуються мови: русский, українська, English",
            parse_mode="HTML"
        )
        return
    
    # Добавляем пользователя и проверяем новый ли он
    is_new_user = await add_user(user_id, username)

    ref_set = False
    if args:
        try:
            referrer_id = int(args[0])
            # Проверяем, есть ли уже реферер у пользователя
            existing_ref_check = await get_user(user_id)
            has_referrer = existing_ref_check and existing_ref_check[2] is not None
            
            if await set_referrer(user_id, referrer_id):
                ref_set = True
                await asyncio.sleep(2)
                
                # Начисляем награды
                db.add_dan(user_id, 350)
                db.add_dan(referrer_id, 350)
                
                # Разные сообщения для новых и существующих пользователей
                if has_referrer:
                    # Этого не должно произойти, но на всякий случай
                    await bot.send_message(user_id, "ℹ️ У вас уже был реферер!")
                else:
                    # Пользователь без реферера (новый или старый - неважно)
                    await bot.send_message(user_id, "🎉 Реферал засчитан!\n\n💰 Вам начисляно 350 Дань 🪙\n\n✨ Добро пожаловать в игру!")
                    
                # Уведомляем реферера
                try:
                    await bot.send_message(referrer_id, f"🎉 У вас новый реферал: @{username} (ID: {user_id})!\n\n💰 Вам начисляно 350 Дань 🪙")
                except Exception:
                    pass  # Если не удалось уведомить реферера
                    
            else:
                # Не удалось установить реферера
                if has_referrer:
                    # У пользователя уже есть реферер
                    await bot.send_message(user_id, "ℹ️ У вас уже есть реферер! Добро пожаловать обратно в бот! 🎮")
                else:
                    # По какой-то другой причине не удалось (например, сам себя)
                    await bot.send_message(user_id, "❌ Не удалось установить реферера.\n\n💡 Возможные причины:\n• Вы перешли по своей ссылке\n• Техническая ошибка")
                    
        except ValueError:
            # Неверный формат referrer_id
            await bot.send_message(user_id, "❌ Неверная реферальная ссылка!")
        except Exception as e:
            # Любая другая ошибка
            print(f"Ошибка в обработке реферала: {e}")
            pass
    start_text = (
        "👋 Привет! Я — КРУЗ ЧАТ БОТ \n\n"
        "⚡ Тут ты найдёшь игры, движ и способы прокачать свой чат. Один? С друзьями? С семьёй? — всегда будет весело!\n\n"
        "✔️ И да, тут можно зарабатывать даже БЕСПЛАТНО 😏\n\n"
        "❓ Запутался или есть вопросы?  /help"
        "ЭТО БЕТА ВЕРСИЯ, ВАШ БАЛАНС ПОСЛЕ ВЫХОДА БУДЕТ СБРОШЕН."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+ Добавить в чат 💬", url="https://t.me/KruzChatBot?startgroup=true")
        ],
        [
            InlineKeyboardButton(text="⭐ наш чат ", url="https://t.me/+fQwufGJ09FVmYjc6"),
            InlineKeyboardButton(text="🎮 Играть", callback_data=f"open_game_menu:{user_id}")
        ]
    ])

    # --- Путь к фото ---
    photo_path = "c:/BotKruz/ChatBotKruz/photo/startphoto.jpg"
    try:
        await message.answer_photo(FSInputFile(photo_path), caption=start_text, reply_markup=keyboard)
    except Exception as e:
        await message.answer(start_text, reply_markup=keyboard)
    
    # Приветственное сообщение для новых пользователей
    if is_new_user and not ref_set:
        await asyncio.sleep(1)
        await message.answer(
            "🎁 Добро пожаловать!\n\n"
            "💰 Вам начислено 500 дань на старт!\n\n"
            "🎮 Играйте, развивайтесь и зарабатывайте!"
        )

# --- Callback для кнопки "ИГРАТЬ" ---
@dp.callback_query(lambda c: c.data.startswith("open_game_menu:"))
async def open_game_menu_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец меню
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    current_user_id = callback.from_user.id if callback.from_user else None
    username = callback.from_user.username if callback.from_user else "unknown"
    print(f"DEBUG: open_game_menu - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
    
    if not current_user_id or owner_user_id != current_user_id:
        print(f"DEBUG: BLOCKING ACCESS - owner: {owner_user_id}, current: {current_user_id}")
        await callback.answer("❌ Это не ваше меню!", show_alert=True)
        return
    
    await callback.answer()
    await show_main_menu(callback, owner_user_id)

# Обработчик для кнопки "Назад в меню" без параметров
@dp.callback_query(lambda c: c.data == "open_game_menu")
async def open_game_menu_simple_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    await callback.answer()
    await show_main_menu(callback, user_id)

# --- Callback для кнопки "ИГРАТЬ" - поиск игры в арене ---
@dp.callback_query(lambda c: c.data.startswith("play_games:"))
async def play_games_callback(callback: types.CallbackQuery):
    """Обработчик кнопки ИГРАТЬ - меню арены"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец меню
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    current_user_id = callback.from_user.id if callback.from_user else None
    
    if not current_user_id or owner_user_id != current_user_id:
        await callback.answer("❌ Это не ваше меню!", show_alert=True)
        return
    
    user_id = callback.from_user.id
    username = getattr(callback.from_user, 'username', None) or f"ID:{user_id}"
    safe_ensure_user(user_id, username)
    
    # Получаем рейтинг игрока
    rating_data = arena.get_arena_rating(user_id)
    
    # Определяем лигу
    rating = rating_data['rating']
    if rating < 1000:
        league = "🥉 Новичок"
    elif rating < 1500:
        league = "🥈 Боец"
    elif rating < 2000:
        league = "🥇 Воин"
    elif rating < 2500:
        league = "💎 Мастер"
    else:
        league = "👑 Легенда"

    text = f"🏟️ <b>АРЕНА KRUZCHAT</b> 🏟️\n\n"
    text += f"⚔️ <b>Тактические PvP бои!</b>\n"
    text += f"Сражайтесь в пошаговых боях, используя атаку, защиту и лечение. Каждое решение влияет на исход битвы!\n\n"
    text += f"🏆 <b>Ваш профиль:</b>\n"
    text += f"📊 Рейтинг: <b>{rating} PTS</b> ({league})\n"
    text += f"🏆 Побед: <b>{rating_data['wins']}</b>\n"
    text += f"💔 Поражений: <b>{rating_data['losses']}</b>\n"
    try:
        level = rating_data.get('level', 1)
        xp = rating_data.get('xp', 0)
        text += f"🎚️ Уровень: <b>{level}</b>\n"
        text += f"📘 Опыт: <b>{xp}/5000</b>\n"
    except Exception:
        pass
    
    if rating_data['win_streak'] > 0:
        text += f"🔥 Серия побед: <b>{rating_data['win_streak']}</b>\n"
    
    text += f"\n🎯 <b>Как играть:</b>\n"
    text += f"• Каждый ход выбирайте действие\n"
    text += f"• ⚔️ <b>Атака</b>: наносит урон (15-25)\n"
    text += f"• 🛡️ <b>Защита</b>: дает броню и шанс уклонения\n"
    text += f"• 💚 <b>Лечение</b>: восстанавливает HP (5-10%)\n"
    text += f"• 💥 <b>Комбо</b>: 3 одинаковых действия = спецэффект!\n\n"
    text += f"⏱️ Время боя: 10 минут\n"
    text += f"❤️ HP: 100 | Критические удары: 15%"
    
    keyboard = []
    
    # Проверяем, не в игре ли уже
    in_game = any(game.fighter1.user_id == user_id or game.fighter2.user_id == user_id 
                  for game in arena.active_arenas.values() if game.is_active)
    
    if in_game:
        keyboard.append([InlineKeyboardButton(text="⚔️ Вернуться к бою", callback_data="arena_return_to_game")])
        keyboard.append([InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot"),
            InlineKeyboardButton(text="🔍 Найти бой", callback_data="arena_find_match")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton(text="🎁 Забрать приз (скоро)", callback_data="arena_claim_level_reward")],
        [InlineKeyboardButton(text="💎 Рейтинг-таблица", callback_data="arena_leaderboard")],
        [InlineKeyboardButton(text="📋 Статистика", callback_data="arena_my_stats"), InlineKeyboardButton(text="⚔️ Справка", callback_data="arena_help")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"open_game_menu:{user_id}")]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer("🏟️ Добро пожаловать в арену!")

# Обработчик кнопки "Играть с ботом"
@dp.callback_query(lambda c: c.data == "arena_play_with_bot")
async def arena_play_with_bot_callback(callback: types.CallbackQuery):
    """Немедленно начать игру с ботом"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    username = getattr(callback.from_user, 'username', None) or f"ID:{user_id}"
    
    # Удаляем из очереди если есть
    arena.remove_from_arena_queue(user_id)
    
    # Создаем бота-противника
    import random
    bot_names = ["БотВоин", "КиберБоец", "Арена-Бот", "СталБот", "МехВоин"]
    bot_name = random.choice(bot_names)
    
    # Создаем игру с ботом
    player_data = {'user_id': user_id, 'username': username}
    bot_data = {
        'user_id': -abs(user_id),  # Отрицательный ID для бота
        'username': bot_name
    }
    
    game_id = arena.create_arena_game(player_data, bot_data, 0)
    game = arena.get_arena_game(game_id)
    
    # ВАЖНО: Сохраняем информацию о чате для результата
    if callback.message and callback.message.chat:
        game.source_chat_id = callback.message.chat.id
        game.source_message_id = callback.message.message_id
    
    # Уведомляем в чате что бой с ботом начался
    await safe_edit_text_or_caption(
        callback.message, 
        f"🤖 <b>БОЙ С БОТОМ НАЧАЛСЯ!</b>\n\n👤 {username} VS 🤖 {bot_name}\n\n🔄 Бой проходит в личных сообщениях\n📢 Результат будет показан здесь", 
        reply_markup=None, 
        parse_mode="HTML"
    )
    
    # Отправляем интерфейс игры в ЛС игроку
    try:
        text = f"🤖 <b>БОЙ С БОТОМ!</b>\n\n"
        text += f"🎯 Противник: {bot_name}\n\n"
        text += game.get_arena_display(user_id)
        
        keyboard = game.get_keyboard(user_id)
        
        msg = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        game.message_ids[user_id] = msg.message_id
        
        # Запускаем ИИ бота
        import asyncio
        asyncio.create_task(arena.bot_arena_ai(game_id, bot_data['user_id']))
        
    except Exception as e:
        print(f"Ошибка создания игры с ботом: {e}")
        await callback.answer("❌ Ошибка создания игры", show_alert=True)
        return
    
    # Обновляем интерфейс в меню
    text = f"🤖 <b>БОЙ С БОТОМ НАЧАЛСЯ!</b>\n\n"
    text += f"⚔️ Противник: {bot_name}\n"
    text += f"📱 Бой проходит в личных сообщениях\n\n"
    text += "💡 Перейдите в ЛС с ботом для игры!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"open_game_menu:{user_id}")]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer("🤖 Бой с ботом начался!")

# --- Callback для кнопки "Топы игроков" ---
@dp.callback_query(lambda c: c.data == "menu_tops" or c.data.startswith("menu_tops:"))
async def menu_tops(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, есть ли параметр user_id в callback_data
    if ":" in callback.data:
        try:
            _, owner_user_id = callback.data.split(":")
            owner_user_id = int(owner_user_id)
        except (ValueError, IndexError):
            await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
            return
        
        current_user_id = callback.from_user.id if callback.from_user else None
        username = callback.from_user.username if callback.from_user else "unknown"
        print(f"DEBUG: menu_tops - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
        
        if not current_user_id or owner_user_id != current_user_id:
            await callback.answer("❌ Это не ваше место!", show_alert=True)
            return
        
        user_id = owner_user_id  # Используем ID владельца меню
    else:
        user_id = callback.from_user.id  # Для публичных кнопок используем ID текущего пользователя
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ мира", callback_data=f"top_world:{user_id}")],
        [
            InlineKeyboardButton(text="⏰ Топ игроков", callback_data=f"top_chat:{user_id}"),
            InlineKeyboardButton(text="👥 Топ рефералов", callback_data=f"top_ref:{user_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"open_game_menu:{user_id}")]
    ])
    await safe_edit_text_or_caption(callback.message, "Выберите топ:", reply_markup=kb)

# --- Callback для кнопки "Топ мира" ---
@dp.callback_query(lambda c: c.data.startswith("top_world:"))
async def top_world_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    current_user_id = callback.from_user.id if callback.from_user else None
    if not current_user_id or owner_user_id != current_user_id:
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
    # Топ по дань (game_bot.db)
    import sqlite3
    from database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username, dan, games_played FROM users WHERE games_played > 0 ORDER BY dan DESC LIMIT 20")
    top = cur.fetchall()
    user_id = callback.from_user.id
    cur.execute("SELECT username, dan FROM users WHERE user_id = ?", (user_id,))
    me = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM users WHERE dan > (SELECT dan FROM users WHERE user_id = ?) ", (user_id,))
    my_place = cur.fetchone()[0] + 1 if me else None
    conn.close()

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_tops:{owner_user_id}")]
    ])

    if not top:
        await safe_edit_text_or_caption(callback.message, "Нет данных для топа мира.", reply_markup=back_kb)
        return

    places = ["🥇", "🥈", "🥉"] + ["⭐️"]*7 + ["⚡️"]*10
    text = "🏆 ТОП Дань 🪙 в мире \n______________________________\n"
    def format_balance(val):
        try:
            return f"{float(val):,.2f}".replace(",", " ")
        except Exception:
            return str(val)

    # Получаем данные пользователей с их user_id для новой системы имен
    conn2 = sqlite3.connect(DB_PATH)
    cur2 = conn2.cursor()
    
    for i, (username, dan, games_played) in enumerate(top, 1):
        # skip users with no games just in case
        try:
            if int(games_played) <= 0:
                continue
        except Exception:
            pass
        place = places[i-1] if i <= len(places) else f"{i}."

        # Получаем user_id по username для использования новой системы имен
        cur2.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        user_data = cur2.fetchone()
        if user_data:
            display_name = get_display_name(user_data[0], username)
            clickable_name = format_clickable_name(user_data[0], display_name)
        else:
            display_name = username if username and len(username) >= 2 else "Игрок"
            clickable_name = display_name

        text += f"{place} {clickable_name} — {format_balance(dan)}\n"
    
    conn2.close()
    text += "_________________________\n"
    if my_place and my_place > 20:
        my_display_name = get_display_name(user_id, me[0] if me else None)
        text += f"\nВаше место: {my_place} ({my_display_name}) — {format_balance(me[1])}"
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=back_kb, parse_mode="HTML")

# --- Callback для кнопки "Топ чата" ---
@dp.callback_query(lambda c: c.data.startswith("top_chat:"))
async def top_chat_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    current_user_id = callback.from_user.id if callback.from_user else None
    if not current_user_id or owner_user_id != current_user_id:
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
    # Топ по количеству сыгранных игр (game_bot.db)
    import sqlite3
    from database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username, games_played FROM users WHERE games_played > 0 ORDER BY games_played DESC LIMIT 20")
    top = cur.fetchall()
    user_id = callback.from_user.id
    cur.execute("SELECT username, games_played FROM users WHERE user_id = ?", (user_id,))
    me = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM users WHERE games_played > (SELECT games_played FROM users WHERE user_id = ?) ", (user_id,))
    my_place = cur.fetchone()[0] + 1 if me else None
    conn.close()

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_tops:{owner_user_id}")]
    ])

    if not top:
        await safe_edit_text_or_caption(callback.message, "Нет данных для топа чата.", reply_markup=back_kb)
        return

    places = ["🥇", "🥈", "🥉"] + ["⭐️"]*7 + ["⚡️"]*10
    text = "🏆 ТОП по играм 🎲\n______________________________\n"
    def format_games(val):
        try:
            return f"{int(val):,}".replace(",", " ")
        except Exception:
            return str(val)

    # Получаем данные пользователей с их user_id для новой системы имен
    conn2 = sqlite3.connect(DB_PATH)
    cur2 = conn2.cursor()

    for i, (username, games) in enumerate(top, 1):
        # games should be positive thanks to the WHERE clause, but double-check and skip zeros
        try:
            if int(games) <= 0:
                continue
        except Exception:
            pass

        place = places[i-1] if i <= len(places) else f"{i}."

        # Получаем user_id по username для использования новой системы имен
        cur2.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        user_data = cur2.fetchone()
        if user_data:
            display_name = get_display_name(user_data[0], username)
            if len(display_name) > 12:
                display_name = display_name[:12] + "..."
            clickable_name = format_clickable_name(user_data[0], display_name)
        else:
            display_name = username if username and len(username) >= 2 else "Игрок"
            if len(display_name) > 12:
                display_name = display_name[:12] + "..."
            clickable_name = display_name

        text += f"{place} {clickable_name} — {format_games(games)}\n"

    conn2.close()
    text += "_________________________\n"
    if my_place and my_place > 20:
        my_display_name = get_display_name(user_id, me[0] if me else None)
        # Обрезаем до 12 символов
        if len(my_display_name) > 12:
            my_display_name = my_display_name[:12] + "..."
        text += f"\nВаше место: {my_place} ({my_display_name}) — {format_games(me[1])}"
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=back_kb, parse_mode="HTML")

# --- Callback для кнопки "ферма" (menu_ferma) ---
@dp.callback_query(lambda c: c.data == "menu_ferma")
async def menu_ferma_callback(callback: types.CallbackQuery):
    # Guard: ensure callback.message and callback.from_user are present
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    user_id = callback.from_user.id
    from ferma import get_farm, get_farm_leaderboard_position, collect_dan
    
    # ✅ АВТОМАТИЧЕСКИ СОБИРАЕМ ДАНЬ НА СКЛАД ПРИ ОТКРЫТИИ МЕНЮ
    safe_ensure_user(user_id, getattr(callback.from_user, 'username', None))
    
    # Автоматически собираем накопившуюся дань на склад
    from ferma import collect_dan
    collect_dan(user_id)
    
    # Получаем обновленные данные фермы после автосбора
    farm = get_farm(user_id)
    place = get_farm_leaderboard_position(user_id)
    user_row = db.get_user(user_id)
    if not user_row:
        bal = 0.0
    else:
        bal = user_row.get("dan", 0)
        try:
            bal = float(bal)
        except Exception:
            bal = 0.0
    bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
    bal = format_number_beautiful(bal)
    
    # Данные склада (после автоматического сбора)
    stored_dan = farm['stored_dan'] if 'stored_dan' in farm else 0
    stored_dan = float(stored_dan)
    stored_dan = 0.00 if abs(stored_dan) < 0.005 else round(stored_dan, 2)
    stored_dan_text = f"{stored_dan:.2f}"
    
    # Просто показываем сколько на складе (без промежуточных расчетов)
    farm_status = f"🌱 Дань на складе фермы: {stored_dan_text}"
    
    hour = datetime.datetime.now().hour
    greeting = "Доброе утро, фермер!" if 6 <= hour < 18 else "Доброй ночи, фермер!"
    photo_path = "C:/BotKruz/ChatBotKruz/photo/fermaday.png" if 6 <= hour < 18 else "C:/BotKruz/ChatBotKruz/photo/fermanight.png"
    # Доход и иконки животных
    from ferma import get_user_farm_animals, is_animal_active, ANIMALS_CONFIG
    animals = get_user_farm_animals(user_id)
    animals_income = 0
    count_by_type = {}
    for slot_number, animal_data in animals.items():
        a_type = animal_data['type']
        count_by_type[a_type] = count_by_type.get(a_type, 0) + 1
        if is_animal_active(animal_data):
            cfg = ANIMALS_CONFIG.get(a_type, {})
            animals_income += cfg.get('income_per_hour', 0)
    # Иконки по количеству размещенных животных
    icon_map = { 'cow': '🐮', 'chicken': '🐔' }
    icons_str = ''.join(icon_map.get(t, '') * n for t, n in count_by_type.items())
    income_text = (
        f"🌾 Доход в час: {farm['income_per_hour']} (+{animals_income} {icons_str})"
        if icons_str else
        f"🌾 Доход в час: {farm['income_per_hour']} (+0)"
    )

    
    # Проверяем активен ли бесконечный склад
    infinite_storage = db.get_user_effect(user_id, "infinite_storage")
    if infinite_storage:
        import time
        remaining_time = infinite_storage['expires_at'] - int(time.time())
        if remaining_time > 0:
            days = remaining_time // 86400
            hours = (remaining_time % 86400) // 3600
            minutes = (remaining_time % 3600) // 60
            storage_info = f"📮 Бесконечный склад активен: {days}д {hours}ч {minutes}м"
        else:
            storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"

    else:
        storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"
    
    reply = (
        f"👨‍🌾 🌾 {greeting}\n\n"
        f"🏡 Уровень фермы: {farm['level']}\n"
    f"{income_text}\n"
        f"{storage_info}\n"
        f"📊 Место в топе по доходу: {place}\n\n"
        f"{farm_status}\n"
        f"🪙 Дань на балансе: {bal}"
    )
    
    # Получаем стоимость следующего улучшения
    from ferma import get_next_upgrade_cost
    next_cost = get_next_upgrade_cost(user_id)
    
    if next_cost is not None:
        # Форматируем стоимость красиво
        cost_formatted = format_number_beautiful(next_cost)
        upgrade_text = f"📈 Улучшить ({cost_formatted})"
    else:
        upgrade_text = "📈 Макс. уровень"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=upgrade_text, callback_data="upgrade_ferma"),
            InlineKeyboardButton(text="🐄 Животные", callback_data="farm_animals")
        ],
        [InlineKeyboardButton(text="📥 Собрать дань", callback_data="collect_ferma")],
        [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
    ])
    try:
        photo = FSInputFile(photo_path)
        await callback.message.edit_media(media=InputMediaPhoto(media=photo, caption=reply), reply_markup=kb)
    except Exception as e:
        await callback.message.edit_text(reply, reply_markup=kb)

# Обработчик для приватных кнопок фермы с проверкой владельца
@dp.callback_query(lambda c: c.data.startswith("menu_ferma:"))
async def menu_ferma_private_callback(callback: types.CallbackQuery):
    """Обработчик приватных кнопок фермы с проверкой владельца"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец меню
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
    
    # Вызываем основной обработчик фермы
    await menu_ferma_callback(callback)

# Inventory and config are loaded above via dynamic loader (inv_inventory / inv_config)
# Use the names exposed earlier: get_user_inventory, build_inventory_markup, show_item_card, use_item,

async def open_chest_level1(message, user_id, item_id):
    from plugins.games.case_system import start_case_opening, get_case_photo_path
    # Предмет удален в use_item() перед вызовом этой функции
    
    # Отслеживаем открытие сундука для заданий
    try:
        _tasks.record_case_open(user_id)
    except Exception as e:
        print(f"❌ Ошибка записи открытия кейса для {user_id}: {e}")
    
    # Начинаем сессию открытия кейса
    case_type = "chest_level1"
    photo_path = get_case_photo_path(case_type)
    
    session = start_case_opening(user_id, case_type, message.message_id)
    
    try:
        media = InputMediaPhoto(
            media=FSInputFile(photo_path),
            caption=session.get_status_text()
        )
        await message.edit_media(media=media, reply_markup=session.get_keyboard())
    except Exception:
        # Fallback без фото
        await message.edit_text(
            session.get_status_text(),
            reply_markup=session.get_keyboard()
        )

async def open_chest_level2(message, user_id, item_id):
    from plugins.games.case_system import start_case_opening, get_case_photo_path
    # Предмет удален в use_item() перед вызовом этой функции
    
    # Отслеживаем открытие сундука для заданий
    try:
        _tasks.record_case_open(user_id)
    except Exception as e:
        print(f"❌ Ошибка записи открытия кейса для {user_id}: {e}")
    
    # Начинаем сессию открытия кейса
    case_type = "chest_level2"
    photo_path = get_case_photo_path(case_type)
    
    session = start_case_opening(user_id, case_type, message.message_id)
    
    try:
        media = InputMediaPhoto(
            media=FSInputFile(photo_path),
            caption=session.get_status_text()
        )
        await message.edit_media(media=media, reply_markup=session.get_keyboard())
    except Exception:
        # Fallback: отправляем новое сообщение вместо редактирования
        await message.answer_photo(
            photo=FSInputFile(photo_path),
            caption=session.get_status_text(),
            reply_markup=session.get_keyboard()
        )

async def open_chest_level3(message, user_id, item_id):
    from plugins.games.case_system import start_case_opening, get_case_photo_path
    # Предмет удален в use_item() перед вызовом этой функции
    
    # Отслеживаем открытие сундука для заданий
    try:
        _tasks.record_case_open(user_id)
    except Exception as e:
        print(f"❌ Ошибка записи открытия кейса для {user_id}: {e}")
    
    # Начинаем сессию открытия кейса
    case_type = "chest_level3"
    photo_path = get_case_photo_path(case_type)
    
    session = start_case_opening(user_id, case_type, message.message_id)
    
    try:
        media = InputMediaPhoto(
            media=FSInputFile(photo_path),
            caption=session.get_status_text()
        )
        await message.edit_media(media=media, reply_markup=session.get_keyboard())
    except Exception:
        # Fallback без фото
        await message.edit_text(
            session.get_status_text(),
            reply_markup=session.get_keyboard()
        )

async def notify_admin_about_gift(user, user_id):
    """Отправляет уведомление администратору о том, что пользователь открыл подарок"""
    try:
        # Получаем информацию о пользователе
        first_name = user.first_name or "Не указано"
        last_name = user.last_name or ""
        username = user.username or "Не указан"
        full_name = f"{first_name} {last_name}".strip()
        
        # Формируем текст уведомления
        notification_text = f"""🎁 ОТКРЫТ ПОДАРОК В TELEGRAM! 🎁

👤 Пользователь: {full_name}
🆔 ID: `{user_id}`
📱 Username: @{username}
📞 Телефон: 🔒 Скрыт (запросите у пользователя)
⭐ Подарок: 15 звезд в Telegram

💬 Свяжитесь с пользователем для выдачи подарка!

ℹ️ Чтобы скопировать ID, нажмите на него в сообщении выше."""

        # Создаем кнопки для связи с пользователем
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Написать пользователю", 
                url=f"tg://user?id={user_id}"
            )],
            [InlineKeyboardButton(
                text="✅ Отметить как обработано", 
                callback_data=f"mark_gift_processed:{user_id}"
            )]
        ])
        
        # Отправляем уведомление администратору
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=notification_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        print(f"✅ Уведомление администратору отправлено: пользователь {user_id} открыл подарок")
        
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления администратору: {e}")

# Callback обработчик для кнопки администратора
@dp.callback_query(F.data.startswith("mark_gift_processed:"))
async def handle_gift_processed(callback: types.CallbackQuery):
    """Обрабатывает нажатие кнопки 'Отметить как обработано'"""
    try:
        # Проверяем, что это администратор
        if callback.from_user.id != ADMIN_ID:
            await callback.answer("❌ У вас нет прав для этого действия", show_alert=True)
            return
        
        # Извлекаем user_id из callback_data
        _, user_id = callback.data.split(":")
        user_id = int(user_id)
        
        # Изменяем сообщение, отмечая как обработанное
        processed_text = f"✅ ПОДАРОК ОБРАБОТАН ✅\n\n{callback.message.text}\n\n⏰ Обработано: {time.strftime('%d.%m.%Y %H:%M')}"
        
        # Убираем кнопки
        await callback.message.edit_text(
            processed_text,
            parse_mode="HTML"
        )
        
        await callback.answer("✅ Подарок отмечен как обработанный")
        
    except Exception as e:
        print(f"❌ Ошибка в handle_gift_processed: {e}")
        await callback.answer("❌ Произошла ошибка")

async def send_telegram_gift(message, user_id, item_id):
    # Предмет уже удален в use_item(), не нужно удалять повторно
    
    # Отправляем уведомление пользователю
    await message.answer("🎁⭐ Подарок в Telegram на 15 звезд был отправлен!\nПроверьте ваши уведомления в Telegram.")
    
    # Уведомляем администратора
    await notify_admin_about_gift(message.from_user, user_id)

async def activate_infinite_storage(message, user_id, item_id):
    import random
    days = random.randint(7, 14)
    hours = days * 24
    
    # Сохраняем эффект в базе данных
    db.add_user_effect(user_id, "infinite_storage", f"duration_days:{days}", hours)
    
    await message.answer(f"🏠✨ Бесконечный склад активирован на {days} дней!\n📦 Теперь ваш склад не имеет ограничений.")

async def place_animal_on_farm_handler(message, user_id, item_id):
    """Размещает животное из инвентаря на ферму"""
    from ferma import place_animal_on_farm
    
    result = place_animal_on_farm(user_id, item_id)
    
    if result['status'] == 'ok':
        await message.answer(result['msg'])
    else:
        await message.answer(f"❌ {result['msg']}")

ITEM_USE_HANDLERS = {
    "open_chest_level1": open_chest_level1,
    "open_chest_level2": open_chest_level2,
    "open_chest_level3": open_chest_level3,
    "send_telegram_gift": send_telegram_gift,
    "activate_infinite_storage": activate_infinite_storage,
    "place_animal_on_farm": place_animal_on_farm_handler
}


# --- /inv command ---
@dp.message(Command("inv"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    items, total, max_page = get_user_inventory(user_id, page=1, force_sync=True)  # Принудительная синхронизация при первом открытии
    # Подготовим данные для рендера: (item_id, count, name)
    grid_items = []
    item_images = {}
    for item_id, count in items:
        if item_id == "empty":
            name = "Пусто"
            icon_path = NULL_ITEM["photo_square"]
            base_id = None
        else:
            # Поддержка индивидуальных животных с форматом ID вида 08@123
            if "@" in item_id:
                base_id, owned_id = item_id.split("@", 1)
            else:
                base_id, owned_id = item_id, None
            # Безопасно получаем конфиг по базовому ID
            cfg = ITEMS_CONFIG.get(base_id)
            if not cfg:
                # Если по какой-то причине нет конфига — пропускаем слот
                name = "Неизвестно"
                icon_path = NULL_ITEM["photo_square"]
            else:
                name = cfg["name"] if not owned_id else f"{cfg['name']}"
                icon_path = cfg["photo_square"]
        grid_items.append((item_id, count, name))
        item_images[item_id] = icon_path
    
    # Используем кешированное изображение
    photo_path = get_cached_image(grid_items, item_images)
    text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
    kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
    await message.answer_photo(FSInputFile(photo_path), caption=text, reply_markup=kb)

# --- Inventory page navigation ---
@dp.callback_query(lambda c: c.data.startswith("inv_page"))
async def callback_inv_page(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    current_user_id = callback.from_user.id
    username = callback.from_user.username or "unknown"
    
    # Проверяем формат кнопки: inv_page:page или inv_page:page:owner_user_id
    parts = callback.data.split(":")
    if len(parts) >= 3:
        # Новый формат с owner_user_id
        _, page, owner_user_id = parts[:3]
        owner_user_id = int(owner_user_id)
        print(f"DEBUG: inv_page - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
        if owner_user_id != current_user_id:
            print(f"DEBUG: BLOCKING INV_PAGE ACCESS - owner: {owner_user_id}, current: {current_user_id}")
            await callback.answer("❌ Это не ваше место!", show_alert=True)
            return
    else:
        # Старый формат без owner_user_id
        _, page = parts
        owner_user_id = current_user_id
        print(f"DEBUG: inv_page - old format, user: @{username}")
    
    page = max(1, int(page))
    user_id = callback.from_user.id
    items, total, max_page = get_user_inventory(user_id, page, force_sync=False)  # Без синхронизации при навигации
    
    # Дополнительная проверка: не позволяем переходить за последнюю страницу
    page = min(page, max_page)
    # Подготовим данные для рендера: (item_id, count, name)
    grid_items = []
    item_images = {}
    for item_id, count in items:
        if item_id == "empty":
            name = "Пусто"
            icon_path = NULL_ITEM["photo_square"]
        else:
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
    
    # Используем кешированное изображение
    photo_path = get_cached_image(grid_items, item_images)
    text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
    kb = build_inventory_markup(page=page, max_page=max_page, owner_user_id=owner_user_id)
    media = InputMediaPhoto(media=FSInputFile(photo_path), caption=text)
    
    user_id = callback.from_user.id
    if not can_edit_media(user_id):
        await callback.answer("⏳ Подождите немного", show_alert=False)
        return
    
    try:
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        await callback.answer("Ошибка обновления инвентаря", show_alert=True)

# --- Open item card ---
@dp.callback_query(lambda c: c.data.startswith("inv_item"))
async def callback_inv_item(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Безопасное разделение данных callback
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата данных")
        return
    
    _, num, page = parts[0], parts[1], parts[2]
    num, page = int(num), int(page)
    user_id = callback.from_user.id
    items, _, _ = get_user_inventory(user_id, page)
    item_id, count = items[num-1]
    if item_id == "empty":
        await callback.answer("Пустая ячейка")
        return
    # Поддержка индивидуальных животных (формат base@owned_id)
    if "@" in item_id:
        base_id, owned_id = item_id.split("@", 1)
    else:
        base_id, owned_id = item_id, None

    item_cfg = ITEMS_CONFIG.get(base_id)
    path = item_cfg["photo_square"] if item_cfg else NULL_ITEM["photo_square"]

    # Если это индивидуальное животное — показываем его детали
    if owned_id:
        from ferma import list_owned_animals
        try:
            animals = list_owned_animals(callback.from_user.id)
            owned = next((a for a in animals if str(a['id']) == str(owned_id)), None)
        except Exception:
            owned = None
        if owned:
            import time
            last_fed = int(owned.get('last_fed_time', 0) or 0)
            hours_ago = int((time.time() - last_fed) // 3600) if last_fed > 0 else None
            fed_text = "ещё не кормлено" if last_fed == 0 else (f"кормлено {hours_ago} ч назад" if hours_ago is not None else "кормление неизвестно")
        else:
            fed_text = "—"
        name_text = item_cfg['name'] if item_cfg else 'Животное'
        caption = (
            f"<b>{name_text}</b>\n"
            f"ID: {owned_id}\n"
            f"Память кормления: {fed_text}\n"
            f"Можно разместить на ферме."
        )
        # Для индивидуального животного показываем кнопки: Продать и Разместить
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Продать", callback_data=f"sell:{item_id}:{page}"),
             InlineKeyboardButton(text="✨ Разместить на ферме", callback_data=f"use:{item_id}:{page}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_page:{page}")]
        ])
    else:
        # Обычный предмет
        caption = f"<b>{item_cfg['name']}</b>\nЦена: {item_cfg.get('price', '?')} Дань\nУ вас: {count} шт."
        if 'desc' in item_cfg:
            caption = f"<b>{item_cfg['name']}</b>\n{item_cfg['desc']}\nЦена: {item_cfg.get('price', '?')} Дань\nУ вас: {count} шт."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Продавать", callback_data=f"sell:{item_id}:{page}"),
             InlineKeyboardButton(text="✨ Использовать", callback_data=f"use:{item_id}:{page}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_page:{page}")]
        ])

    media = InputMediaPhoto(media=FSInputFile(path), caption=caption, parse_mode="HTML")
    
    if not can_edit_media(user_id):
        await callback.answer("⏳ Подождите немного", show_alert=False)
        return
    
    try:
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        await callback.answer("Ошибка показа предмета", show_alert=True)

# --- Callback для кнопки "Топ рефералов" ---
@dp.callback_query(lambda c: c.data.startswith("top_ref:"))
async def top_ref_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    current_user_id = callback.from_user.id if callback.from_user else None
    if not current_user_id or owner_user_id != current_user_id:
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return

    # Используем безопасное подключение к базе данных с совместимостью для Windows 8
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        print(f"🔍 Подключение к базе: {DATABASE_FILE}")
        
        # Проверяем существование таблицы users
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        table_exists = cursor.fetchone()
        if not table_exists:
            print("❌ Таблица users не существует!")
            await callback.answer("База данных не инициализирована", show_alert=True)
            conn.close()
            return
        
        # Проверяем количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        print(f"📊 Всего пользователей в базе: {total_users}")
        
        # Windows 8 совместимый запрос топа
        cursor.execute("""
            SELECT 
                CASE WHEN username IS NULL OR username = '' THEN 'Player' ELSE username END as display_name,
                CASE WHEN referrals_count IS NULL THEN 0 ELSE referrals_count END as ref_count
            FROM users 
            ORDER BY 
                CASE WHEN referrals_count IS NULL THEN 0 ELSE referrals_count END DESC,
                username ASC
            LIMIT 20
        """)
        top = cursor.fetchall()
        
        print(f"🏆 Найдено в топе: {len(top)} пользователей")
        
        # Получаем данные текущего пользователя
        user_id = callback.from_user.id
        cursor.execute("SELECT username, referrals_count FROM users WHERE user_id = ?", (user_id,))
        me = cursor.fetchone()
        
        # Подсчитываем место пользователя
        user_refs = 0
        if me and me[1] is not None:
            user_refs = me[1]
            
        cursor.execute("SELECT COUNT(*) FROM users WHERE referrals_count > ?", (user_refs,))
        my_place_result = cursor.fetchone()
        my_place = my_place_result[0] + 1 if my_place_result else None
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка при получении топа рефералов: {e}")
        import traceback
        traceback.print_exc()
        await callback.answer("❌ Ошибка загрузки топа", show_alert=True)
        return

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_tops:{owner_user_id}")]
    ])

    if not top:
        text = "🏆 ТОП Рефоводов 🫂\n______________________________\n\nПока никто не попал в топ."
        await safe_edit_text_or_caption(callback.message, text, reply_markup=back_kb)
        return

    places = ["🥇", "🥈", "🥉"] + ["⭐️"]*7 + ["⚡️"]*10
    text = "🏆 ТОП Рефоводов 🫂\n______________________________\n"
    
    # Получаем данные пользователей с их user_id для новой системы имен
    # NOTE: referral DB (DATABASE_FILE) may not contain games_played — use main DB_PATH for user stats
    from database import DB_PATH
    conn2 = sqlite3.connect(DB_PATH)
    cursor2 = conn2.cursor()

    for i, (username, count) in enumerate(top, 1):
        # Получаем user_id и games_played по username из основной БД пользователей
        cursor2.execute("SELECT user_id, games_played FROM users WHERE username = ?", (username,))
        user_data = cursor2.fetchone()
        if not user_data:
            continue
        user_id_for_name, games_played = user_data[0], user_data[1]
        try:
            if int(games_played) <= 0:
                continue
        except Exception:
            pass

        place = places[i-1] if i <= len(places) else "⚡️"
        count = count or 0  # На случай если count = None
        display_name = get_display_name(user_id_for_name, username)
        if len(display_name) > 12:
            display_name = display_name[:12] + "..."
        clickable_name = format_clickable_name(user_id_for_name, display_name)
        text += f"{i}.    {place}    {clickable_name}    {count}    чел.\n"
    
    conn2.close()
    
    text += "_________________________\n"
    
    if my_place and my_place > 20 and me:
        my_display_name = get_display_name(user_id, me[0] if me else None)
        # Обрезаем до 12 символов
        if len(my_display_name) > 12:
            my_display_name = my_display_name[:12] + "..."
        ref_count = me[1] if me and me[1] else 0
        text += f"{my_place}. 🏅    {my_display_name}    {ref_count}     чел.\n"
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=back_kb, parse_mode="HTML")
    
# --- Callback для кнопки "Профиль" ---
@dp.callback_query(lambda c: c.data == "menu_profile")
async def menu_profile_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    user_id = callback.from_user.id
    # Получаем профиль из основной базы game_bot.db
    from database import get_user as main_get_user, ensure_user
    user = main_get_user(user_id)
    if not user:
        # Если пользователя нет, создаём его
        safe_ensure_user_from_obj(callback.from_user)
        user = main_get_user(user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
    # Получаем отображаемое имя пользователя (кастомное или настоящее)
    username = user.get("username", "")
    display_name = get_display_name(user_id, username)
    
    # Обрезаем до 12 символов если нужно
    if len(display_name) > 12:
        display_name = display_name[:12] + "..."
    # Статус
    status = "Игрок"
    # Верификация
    verification_status = get_verification_status(user_id)
    # Сыграно игр
    try:
        games_played = user["games_played"]
    except Exception:
        games_played = 0
    # Место в топе по балансу
    from database import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE dan > ?", (user["dan"],))
    top_place = cur.fetchone()[0] + 1
    conn.close()
    # Выиграно/проиграно
    try:
        win = user.get("dan_win", 0)
    except Exception:
        win = 0
    try:
        lose = user.get("dan_lose", 0)
    except Exception:
        lose = 0
    # Дата регистрации
    import datetime
    try:
        reg_date = user.get("reg_date")
        if not reg_date or reg_date == "?":
            # Если нет даты регистрации, записываем сейчас
            reg_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            from database import DB_PATH
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE users SET reg_date = ? WHERE user_id = ?", (reg_date, user_id))
            conn.commit()
            conn.close()
        if len(str(reg_date)) > 16:
            reg_date = str(reg_date)[:16]
    except Exception:
        reg_date = "?"
    # Баланс
    try:
        dan = float(user["dan"])
    except Exception:
        dan = 0.0
    dan = f"{dan:.2f}"
    # Донат валюта
    try:
        donate = int(user["kruz"])
    except Exception:
        donate = 0
    profile_text = (
        f"👤 Ваш профиль\n"
        f" ______________________\n"
        f"├ 🎭 Имя: {display_name}\n"
        f"├ ⚡️ Статус: {status}\n"
        f"├ 🔐 Верификация: {verification_status}\n"
        f"├ 🎮 Сыграно игр: {games_played}\n"
        f"├ 🏆 Место в топе: {top_place} (бал)\n"
        f"├ 🟢 Выиграно: {win} дань\n"
        f"├ 📉 Проиграно: {lose} дань\n"
        f"📅 Дата регистрации: {reg_date}\n"
        f"___________________________\n"
        f"🪙 Дань: {format_number_beautiful(dan)}\n"
        f"⭐ Stars: {format_number_beautiful(donate)}\n"
    )
    
    # Добавляем информацию об уровне и опыте
    try:
        xp_data = get_user_xp_data(user_id)
        level = xp_data.get('level', 1)
        xp = xp_data.get('xp', 0)
        pending_rewards = xp_data.get('pending_level_rewards', 0)
        profile_text += f"___________________________\n"
        profile_text += f"⭐ Уровень: {level}\n"
        profile_text += f"📘 Опыт: {xp}/5000\n"
        if pending_rewards > 0:
            profile_text += f"🎁 Наград: {pending_rewards}\n"
    except Exception as e:
        print(f"⚠️ Ошибка получения данных опыта для профиля: {e}")
    
    # Добавляем информацию об арене
    try:
        rating_data = arena.get_arena_rating(user_id)
        profile_text += f"___________________________\n"
        profile_text += f"🏟️ Арена:\n"
        profile_text += f"└ 📊 Рейтинг: {rating_data.get('rating', 200)} PTS"
    except Exception as e:
        print(f"⚠️ Ошибка получения данных арены для профиля: {e}")
    
    # Получаем настройку приватности для отображения статуса
    privacy_setting = get_profile_privacy(user_id)
    privacy_status = "🔗 Открытый" if privacy_setting else "🔒 Приватный"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔒 Приватность: {privacy_status}", callback_data=f"privacy_toggle:{user_id}")],
        [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
    ])
    await safe_edit_text_or_caption(callback.message, profile_text, reply_markup=kb)

# Обработчик для приватных кнопок профиля с проверкой владельца
@dp.callback_query(lambda c: c.data.startswith("menu_profile:"))
async def menu_profile_private_callback(callback: types.CallbackQuery):
    """Обработчик приватных кнопок профиля с проверкой владельца"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец меню
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
    
    # Вызываем основной обработчик профиля
    await menu_profile_callback(callback)


# --- Обработчик кнопки "Инвентарь" ---
@dp.callback_query(lambda c: c.data.startswith("menu_inventory"))
async def menu_inventory_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    current_user_id = callback.from_user.id
    username = callback.from_user.username or "unknown"
    
    # Проверяем, что кнопку нажал владелец меню
    owner_user_id = current_user_id  # По умолчанию владелец = текущий пользователь
    if callback.data and ":" in callback.data:
        try:
            _, owner_user_id = callback.data.split(":")
            owner_user_id = int(owner_user_id)
            print(f"DEBUG: menu_inventory - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
            if owner_user_id != callback.from_user.id:
                print(f"DEBUG: BLOCKING INVENTORY ACCESS - owner: {owner_user_id}, current: {current_user_id}")
                await callback.answer("❌ Это не ваше меню!", show_alert=True)
                return
        except (ValueError, IndexError):
            print(f"DEBUG: menu_inventory - old button format, user: @{username}")
            pass  # Для старых кнопок без user_id
    user_id = callback.from_user.id
    # При первом открытии синхронизируем и выполняем миграцию животных
    items, total, max_page = get_user_inventory(user_id, page=1, force_sync=True)
    # Подготовим данные для рендера: (item_id, count, name)
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
                # Если нет конфигурации — рендерим как пусто
                name = "Неизвестно"
                icon_path = NULL_ITEM["photo_square"]
            else:
                name = cfg["name"] if not owned_id else f"{cfg['name']}"
                icon_path = cfg["photo_square"]

        grid_items.append((item_id, count, name))
        item_images[item_id] = icon_path
    
    # Используем кешированное изображение
    photo_path = get_cached_image(grid_items, item_images)
    text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
    kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=owner_user_id)
    try:
        media = types.InputMediaPhoto(media=FSInputFile(photo_path), caption=text)
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        await callback.answer("Не удалось открыть инвентарь", show_alert=True)


# --- SELL ITEM FSM ---
# State, StatesGroup уже импортированы выше
class SellItemStates(StatesGroup):
    waiting_for_price = State()
    waiting_for_amount = State()

# --- AUCTION FSM ---
class AuctionStates(StatesGroup):
    waiting_for_quantity = State()
    waiting_for_currency = State()
    waiting_for_price = State()
    confirm_listing = State()

@dp.callback_query(lambda c: c.data.startswith("sell:"))
async def callback_sell_item(callback: types.CallbackQuery, state: FSMContext):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Безопасное разделение данных callback
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата данных")
        return
    
    _, item_id, page = parts[0], parts[1], parts[2]
    if item_id == "empty":
        await callback.answer("Нельзя продать пустую ячейку")
        return
    
    user_id = callback.from_user.id

    # Спец-ветка: индивидуальное животное (формат base@owned_id) — продаём через АУКЦИОН
    if "@" in item_id:
        base_id, owned_id = item_id.split("@", 1)
        cfg = ITEMS_CONFIG.get(base_id)
        if not cfg:
            await callback.answer("❌ Животное не найдено", show_alert=True)
            return
        # Проверим, что такая особь есть у пользователя (и не на ферме)
        try:
            from ferma import get_owned_animal
            owned = get_owned_animal(user_id, int(owned_id))
        except Exception:
            owned = None
        if not owned:
            await callback.answer("❌ Эта особь не найдена", show_alert=True)
            return

        # Начинаем процесс аукциона: количество всегда 1, валюта дань
        chat_id = callback.message.chat.id if callback.message and callback.message.chat else None
        message_id = callback.message.message_id if callback.message else None
        item_name = cfg.get('name', 'Животное')
        await state.update_data(
            item_id=item_id,  # храним base@owned_id, база разберёт
            item_name=item_name,
            max_count=1,
            quantity=1,
            page=page,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            currency="dan"
        )

        # Сразу просим цену
        text = (
            f"💰 <b>Укажите цену</b>\n\n"
            f"🎯 Предмет: <b>{item_name}</b> (индивидуальное животное)\n"
            f"📦 Количество: <b>1 шт.</b>\n"
            f"💱 Валюта: <b>💰 Дань</b> (фиксировано)\n\n"
            f"⚠️ <b>Минимальная цена: 1000 дань</b> за штуку\n"
            f"💬 Введите цену за 1 штуку (минимум 1 000):"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
        ])
        await callback.answer()
        await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
        await state.set_state(AuctionStates.waiting_for_price)
        return

    # Обычная ветка: переходим к продаже на аукцион
    # Проверяем, есть ли предмет в инвентаре (используем существующую функцию)
    items, _, _ = get_user_inventory(user_id, int(page))

    # Найти количество для этого item_id
    quantity = 0
    for iid, cnt in items:
        if iid == item_id:
            quantity = cnt
            break
    if quantity <= 0:
        await callback.answer("❌ У вас нет этого предмета", show_alert=True)
        return

    # Получаем информацию о предмете
    item = ITEMS_CONFIG.get(item_id)
    if not item:
        await callback.answer("❌ Предмет не найден", show_alert=True)
        return
    item_name = item.get('name', item_id)
    
    # Начинаем процесс продажи на аукцион
    chat_id = callback.message.chat.id if callback.message and callback.message.chat else None
    message_id = callback.message.message_id if callback.message else None
    
    await state.update_data(
        item_id=item_id, 
        item_name=item_name, 
        max_count=quantity,
        page=page,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id  # Добавляем ID пользователя для проверки владельца
    )
    
    # Показываем выбор количества для аукциона кнопками
    text = f"📦 <b>Выбор количества</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📊 Доступно: <b>{quantity} шт.</b>\n\n"
    text += f"❓ Сколько штук выставить на продажу?"
    
    # Создаем кнопки быстрого выбора количества
    kb_buttons = []
    quick_amounts = [1, 5, 10]
    amount_row = []
    
    for amount in quick_amounts:
        if amount <= quantity:  # Показываем только доступные количества
            amount_row.append(InlineKeyboardButton(
                text=str(amount), 
                callback_data=f"auction_qty:{amount}"
            ))
    
    if amount_row:
        kb_buttons.append(amount_row)
    
    # Всегда добавляем кнопку "Все" для выставления всего количества
    kb_buttons.append([InlineKeyboardButton(
        text=f"Все ({quantity})", 
        callback_data=f"auction_qty:{quantity}"
    )])
    
    kb_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"menu_inventory:{user_id}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    
    await callback.answer()
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(AuctionStates.waiting_for_quantity)

# --- FSM: Выставить на аукцион ---
@dp.callback_query(lambda c: c.data.startswith("old_auction:"))
async def callback_old_auction_item(callback: types.CallbackQuery, state: FSMContext):
    """УСТАРЕВШИЙ обработчик - оставлен для совместимости"""
    # Перенаправляем на новый обработчик
    if not getattr(callback, 'data', None):
        return
    # Заменяем old_auction: на auction_start:  
    new_data = callback.data.replace("old_auction:", "auction_start:")
    callback.data = new_data
    # Вызываем новый обработчик
    return await callback_auction_start(callback, state)

"""Старые обработчики SellItemStates отключены (устаревшая логика выставления)."""
# (Логика перенесена в AuctionStates)

# --- Назад из продажи ---
@dp.callback_query(lambda c: c.data.startswith("inv_item:"))
async def callback_back_to_item(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    current_user_id = callback.from_user.id
    username = callback.from_user.username or "unknown"
    
    # Проверяем формат кнопки: inv_item:num:page или inv_item:num:page:owner_user_id
    parts = callback.data.split(":")
    if len(parts) >= 4:
        # Новый формат с owner_user_id
        _, num, page, owner_user_id = parts[:4]
        owner_user_id = int(owner_user_id)
        print(f"DEBUG: inv_item - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
        if owner_user_id != current_user_id:
            print(f"DEBUG: BLOCKING INV_ITEM ACCESS - owner: {owner_user_id}, current: {current_user_id}")
            await callback.answer("❌ Это не ваше место!", show_alert=True)
            return
    else:
        # Старый формат без owner_user_id
        _, num, page = parts
        owner_user_id = current_user_id
        print(f"DEBUG: inv_item - old format, user: @{username}")
    
    num, page = int(num), int(page)
    user_id = callback.from_user.id
    items, _, _ = get_user_inventory(user_id, page)
    item_id, count = items[num-1]
    if item_id == "empty":
        await callback.answer("Пустая ячейка")
        return
    item = ITEMS_CONFIG[item_id]
    path = item["photo_square"]
    caption = f"<b>{item['name']}</b>\nЦена: {item.get('price', '?')} Дань\nУ вас: {count} шт."
    if 'desc' in item:
        caption = f"<b>{item['name']}</b>\n{item['desc']}\nЦена: {item.get('price', '?')} Дань\nУ вас: {count} шт."
    
    # Обновляем кнопки с передачей owner_user_id
    back_callback = f"inv_page:{page}:{owner_user_id}" if len(parts) >= 4 else f"inv_page:{page}"
    sell_callback = f"sell:{item_id}:{page}:{owner_user_id}" if len(parts) >= 4 else f"sell:{item_id}:{page}"
    use_callback = f"use:{item_id}:{page}:{owner_user_id}" if len(parts) >= 4 else f"use:{item_id}:{page}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Продавать", callback_data=sell_callback),
         InlineKeyboardButton(text="✨ Использовать", callback_data=use_callback)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
    ])
    media = InputMediaPhoto(media=FSInputFile(path), caption=caption, parse_mode="HTML")
    
    if not can_edit_media(user_id):
        await callback.answer("⏳ Подождите немного", show_alert=False)
        return
    
    try:
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        await callback.answer("Ошибка показа предмета", show_alert=True)

# --- Use item ---
@dp.callback_query(lambda c: c.data.startswith("use:"))
async def callback_use_item(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Безопасное разделение данных callback
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата данных")
        return
    
    _, item_id, page = parts[0], parts[1], parts[2]
    if item_id == "empty":
        await callback.answer("Нельзя использовать пустую ячейку")
        return
    
    # Логика использования предмета без создания новых сообщений
    user_id = callback.from_user.id
    # Поддержка индивидуальных животных: item_id вида 08@123
    if "@" in item_id:
        base_id, owned_id = item_id.split("@", 1)
        # Проверяем, что это животное и его можно разместить
        item_cfg = ITEMS_CONFIG.get(base_id)
        if not item_cfg or not item_cfg.get("usable"):
            await callback.answer("❌ Этот предмет нельзя использовать.", show_alert=True)
            return
        # Размещаем конкретное животное по его owned_id
        try:
            from ferma import place_specific_owned_animal_on_farm
            result = place_specific_owned_animal_on_farm(user_id, int(owned_id))
        except Exception as e:
            await callback.answer("❌ Ошибка размещения животного", show_alert=True)
            return
        if result.get('status') == 'ok':
            await callback.answer("✅ Размещено на ферме")
            # Обновлять инвентарь здесь не будем — пользователь увидит изменения при следующем открытии
        else:
            await callback.answer(f"❌ {result.get('msg','Ошибка')}", show_alert=True)
        return

    # Обычный предмет из агрегированного инвентаря
    item = ITEMS_CONFIG.get(item_id)
    if not item or not item.get("usable"):
        await callback.answer("❌ Этот предмет нельзя использовать.", show_alert=True)
        return

    inv = db.get_inventory(user_id)
    user_item = next(((i, c) for i, c in inv if i == item_id), None)
    
    if not user_item or user_item[1] <= 0:
        await callback.answer("❌ У вас нет этого предмета.", show_alert=True)
        return

    # Обрабатываем команды предмета
    command = item.get("use_command")
    if command:
        try:
            from main import ITEM_USE_HANDLERS
            handler = ITEM_USE_HANDLERS.get(command)
            if handler:
                # Сначала удаляем предмет из инвентаря
                db.remove_item(user_id, item_id, 1)
                
                # Затем вызываем обработчик
                await handler(callback.message, user_id, item_id)
                
                # Для кейсов не показываем сообщения об использовании
                if command.startswith("open_chest"):
                    return
                else:
                    await callback.answer(f"✅ Вы использовали {item['name']}")
                    return
        except ImportError:
            pass  # Если ITEM_USE_HANDLERS не определен

    # Обычное использование предмета (без команды)
    # Для кейсов (сундуков) не показываем сообщение
    if "Сундук" in item.get('name', '') or "📦" in item.get('name', ''):
        db.remove_item(user_id, item_id, 1)
        await callback.answer("📦 Сундук использован")
        return
    
    db.remove_item(user_id, item_id, 1)
    await callback.answer(f"✅ Вы использовали {item['name']}")

# --- AUCTION SYSTEM ---
@dp.callback_query(lambda c: c.data == "menu_auction" or c.data.startswith("menu_auction:"))
async def menu_auction_callback(callback: types.CallbackQuery):
    """Главное меню аукциона с красивым визуальным интерфейсом"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец меню (для приватных кнопок)
    if ":" in callback.data:
        try:
            _, owner_user_id = callback.data.split(":")
            owner_user_id = int(owner_user_id)
            current_user_id = callback.from_user.id
            if owner_user_id != current_user_id:
                await callback.answer("❌ Это не ваше меню!", show_alert=True)
                return
        except (ValueError, IndexError):
            await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
            return
    
    user_id = callback.from_user.id
    
    try:
        # Получаем данные аукциона (уже отсортированы по created_at DESC - новые первые)
        auction_data = get_auction_display_data(page=1, per_page=9)
        items = auction_data["items"]
        
        if not items:
            # Показываем пустой аукцион
            text = "🏛️ <b>АУКЦИОН</b> 🏛️\n\n❌ Активных лотов нет\n\n💡 Выставьте свои предметы на продажу!"
            kb_buttons = [
                [InlineKeyboardButton(text="📤 Мои лоты", callback_data="auction_my_lots")],
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"open_game_menu:{user_id}")]
            ]
            kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
            await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
            return
        
        # Генерируем/берём из кеша изображение с лотами (в отдельном потоке)
        auction_image_path = await asyncio.to_thread(render_auction_grid_cached, items)
        
        # Создаем подпись для изображения
        caption = format_auction_caption(auction_data, current_page=1)
        
        # Создаем кнопки навигации
        kb_buttons = []
        
        # Кнопки для просмотра лотов (1-9)
        lot_buttons = []
        for i in range(min(9, len(items))):
            lot_num = i + 1
            lot_buttons.append(InlineKeyboardButton(text=f"{lot_num}", callback_data=f"auction_view:{lot_num}"))
            if len(lot_buttons) == 3:  # По 3 кнопки в ряд
                kb_buttons.append(lot_buttons)
                lot_buttons = []
        if lot_buttons:  # Добавляем оставшиеся кнопки
            kb_buttons.append(lot_buttons)
        
        # Навигация по страницам (если есть несколько страниц)
        total_pages = auction_data["total_pages"]
        if total_pages > 1:
            nav_row = []
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data="auction_page:1"))
            nav_row.append(InlineKeyboardButton(text=f"1/{total_pages}", callback_data="auction_info"))
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data="auction_page:2"))
            kb_buttons.append(nav_row)
        
        # Основные кнопки
        kb_buttons.extend([
            [InlineKeyboardButton(text="📤 Мои лоты", callback_data="auction_my_lots")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"open_game_menu:{user_id}")]
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        # Отправляем изображение с подписью
        try:
            from aiogram.types import InputMediaPhoto, FSInputFile
            user_id = callback.from_user.id
            if not can_edit_media(user_id):
                await callback.answer("⏳ Подождите немного", show_alert=False)
                return
                
            await callback.message.edit_media(
                media=InputMediaPhoto(media=FSInputFile(auction_image_path), caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            # Fallback если не получается отредактировать
            await callback.message.answer_photo(
                FSInputFile(auction_image_path), 
                caption=caption, 
                reply_markup=kb,
                parse_mode="HTML"
            )
        
        # Файл кешируется и переиспользуется — не удаляем
            
        try:
            await callback.answer()
        except Exception:
            pass
            
    except Exception as e:
        # Fallback к старому текстовому интерфейсу при ошибке
        print(f"Ошибка в auction render: {e}")
        
        from database import get_auction_items, cleanup_expired_auctions
        cleanup_expired_auctions()
        auction_data = get_auction_items(page=1, per_page=5)
        items = auction_data["items"]
        total_pages = auction_data["total_pages"]
        
        if not items:
            text = "🏛️ <b>АУКЦИОН</b> 🏛️\n\n❌ Активных лотов нет\n\n💡 Выставьте свои предметы на продажу!"
        else:
            text = f"🏛️ <b>АУКЦИОН</b> 🏛️\n\nСтраница 1/{total_pages}\n\n"
            for i, (auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status) in enumerate(items, 1):
                item_name = ITEMS_CONFIG.get(item_id, {}).get('name', item_id)
                total_price = quantity * price_per_item
                import time
                remaining_time = expires_at - int(time.time())
                hours_left = remaining_time // 3600
                text += f"{i}. <b>{item_name}</b> x{quantity}\n"
                text += f"   💰 {price_per_item} дань/шт (всего: {total_price})\n"
                text += f"   ⏰ Осталось: {hours_left}ч\n\n"
        
        kb_buttons = [
            [InlineKeyboardButton(text="📤 Мои лоты", callback_data="auction_my_lots")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"open_game_menu:{user_id}")]
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")



async def safe_edit_by_id(chat_id, message_id, text, reply_markup=None, parse_mode=None):
    """Безопасное редактирование сообщения по ID.

    Поведение:
    - Сначала пытаемся обновить подпись (большинство наших сообщений — медиа).
    - Если подписи нет — пробуем отредактировать как текст.
    - Если ответ Telegram: "message is not modified" — молча игнорируем (это не ошибка).
    - Новое сообщение отправляем ТОЛЬКО если исходное нельзя редактировать или оно удалено.
    """
    def _need_fallback_send(err_msg: str) -> bool:
        err = (err_msg or "").lower()
        # Перечень ситуаций, когда нужно отправлять новое сообщение
        return any(
            key in err for key in [
                "message to edit not found",      # исходное удалено
                "message can't be edited",        # истекло время редактирования
                "message is too old",             # слишком старое
                "chat not found",                 # чат недоступен
            ]
        )

    # 1) Пытаемся как подпись
    try:
        return await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as caption_error:
        msg = str(caption_error)
        # Если текст не изменился — просто выходим без спама
        if "message is not modified" in msg.lower():
            return None
        # Если у сообщения нет подписи — пробуем как текст
        if "no caption" in msg.lower() or "there is no caption" in msg.lower():
            try:
                return await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception as text_error:
                msg2 = str(text_error).lower()
                if "message is not modified" in msg2:
                    return None
                if _need_fallback_send(msg2):
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                # Иные ошибки редактирования — не спамим дубликатами
                return None
        # Если подпись редактировать нельзя и это критично — отправим новое
        if _need_fallback_send(msg):
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        # Остальные ошибки игнорируем без отправки нового сообщения
        return None

async def safe_edit_text_or_caption(message, text, reply_markup=None, parse_mode=None):
    """Безопасно редактирует сообщение (текст/подпись) без лишних дублей.

    Логика:
    - Если это медиа (photo/video) — редактируем подпись, иначе текст.
    - На "message is not modified" просто возвращаемся (ничего не делаем).
    - При ошибке "there is no text in the message to edit" пробуем подпись и наоборот.
    - Новое сообщение НЕ отправляем, за исключением случаев, когда исходное редактировать нельзя
      (удалено/слишком старое) — тогда отправляем ответ в чат.
    """
    def _need_fallback_send(err_msg: str) -> bool:
        err = (err_msg or "").lower()
        return any(
            key in err for key in [
                "message to edit not found",
                "message can't be edited",
                "message is too old",
                "chat not found",
            ]
        )

    is_media = bool(getattr(message, 'photo', None) or getattr(message, 'video', None))
    try:
        if is_media:
            return await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return None
        # Попробуем альтернативный тип редактирования
        try:
            if is_media:
                return await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                return await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            msg2 = str(e2).lower()
            if "message is not modified" in msg2:
                return None
            if _need_fallback_send(msg2):
                try:
                    return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
                except Exception:
                    return None
            return None


 

@dp.callback_query(lambda c: c.data.startswith("auction_view:"))
async def auction_view_callback(callback: types.CallbackQuery):
    """Просмотр конкретного лота"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, lot_number = callback.data.split(":")
    lot_number = int(lot_number)
    
    from database import get_auction_items
    
    # Получаем лоты
    auction_data = get_auction_items(page=1, per_page=10)
    items = auction_data["items"]
    
    if lot_number > len(items):
        await callback.answer("Лот не найден", show_alert=True)
        return
    
    auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status = items[lot_number - 1]
    
    # Получаем информацию о предмете из уже загруженной конфигурации
    
    item_config = ITEMS_CONFIG.get(item_id, {})
    item_name = item_config.get('name', item_id)
    item_desc = item_config.get('desc', 'Описание отсутствует')
    
    total_price = quantity * price_per_item
    
    # Время до окончания
    import time
    remaining_time = expires_at - int(time.time())
    hours_left = remaining_time // 3600
    minutes_left = (remaining_time % 3600) // 60
    
    # Получаем имя продавца с использованием новой системы имен
    seller = db.get_user(seller_id)
    seller_username = seller.get('username', '') if seller else ''
    seller_display_name = get_display_name(seller_id, seller_username)
    # Обрезаем до 12 символов если нужно
    if len(seller_display_name) > 12:
        seller_display_name = seller_display_name[:12] + "..."
    seller_clickable_name = format_clickable_name(seller_id, seller_display_name)
    
    text = f"🏛️ <b>ЛОТ #{auction_id}</b>\n\n"
    text += f"📦 <b>{item_name}</b> x{quantity}\n"
    text += f"📝 {item_desc}\n\n"
    text += f"💰 Цена: {price_per_item} дань/шт\n"
    text += f"💎 Общая стоимость: {total_price} дань\n"
    text += f"👤 Продавец: {seller_clickable_name}\n"
    text += f"⏰ Времени осталось: {hours_left}ч {minutes_left}м"
    
    user_id = callback.from_user.id
    
    # Кнопки
    kb_buttons = []
    
    if seller_id != user_id:
        # Можно купить, если не свой лот
        if quantity > 1:
            # Если количество больше 1, показываем варианты
            buy_row = []
            buy_row.append(InlineKeyboardButton(text="🛒 1 шт", callback_data=f"auction_buy_qty:{auction_id}:1"))
            if quantity >= 5:
                buy_row.append(InlineKeyboardButton(text="🛒 5 шт", callback_data=f"auction_buy_qty:{auction_id}:5"))
            buy_row.append(InlineKeyboardButton(text="🛒 Все", callback_data=f"auction_buy:{auction_id}"))
            kb_buttons.append(buy_row)
            
            # Кнопка для ввода своего количества
            kb_buttons.append([
                InlineKeyboardButton(text="✏️ Указать количество", callback_data=f"auction_custom_qty:{auction_id}")
            ])
        else:
            # Если только 1 предмет
            kb_buttons.append([
                InlineKeyboardButton(text="💳 Купить", callback_data=f"auction_buy:{auction_id}")
            ])
    else:
        # Свой лот - можно снять
        kb_buttons.append([
            InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"auction_remove:{auction_id}")
        ])
    
    kb_buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_auction:{callback.from_user.id}")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    
    # Показываем с изображением предмета, если есть
    try:
        photo_path = item_config.get('photo_square')
        if photo_path:
            from aiogram.types import FSInputFile, InputMediaPhoto
            media = InputMediaPhoto(media=FSInputFile(photo_path), caption=text, parse_mode="HTML")
            
            if not can_edit_media(user_id):
                await callback.answer("⏳ Подождите немного", show_alert=False)
                return
                
            await callback.message.edit_media(media=media, reply_markup=kb)
        else:
            await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("auction_buy:"))
async def auction_buy_callback(callback: types.CallbackQuery):
    """Покупка лота с аукциона"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, auction_id = callback.data.split(":")
    auction_id = int(auction_id)
    user_id = callback.from_user.id
    
    from database import buy_auction_item
    
    # Выполняем покупку с увеличенным таймаутом для животных (2.5 секунды)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(buy_auction_item, user_id, auction_id),
            timeout=2.5
        )
    except asyncio.TimeoutError:
        # Отвечаем напрямую, не через callback.answer (может быть просрочен)
        try:
            await callback.message.reply("⏱️ Операция заняла слишком много времени. Попробуйте позже.")
        except Exception:
            pass
        return
    
    if "error" in result:
        try:
            await callback.answer(result["error"], show_alert=True)
        except Exception:
            # Если callback просрочен, отправляем обычным сообщением
            await callback.message.reply(f"❌ {result['error']}")
        return
    
    # Успешная покупка - используем уже загруженную конфигурацию ITEMS_CONFIG из начала файла
    item_name = ITEMS_CONFIG.get(result["item_id"], {}).get('name', result["item_id"])
    
    try:
        await callback.answer(f"✅ Куплено: {item_name} x{result['quantity']} за {result['total_price']} дань!")
    except Exception:
        # Если callback просрочен, отправляем обычным сообщением
        await callback.message.reply(f"✅ Куплено: {item_name} x{result['quantity']} за {result['total_price']} дань!")
    
    # Уведомляем продавца
    try:
        seller_user = db.get_user(result["seller_id"])
        seller_name = seller_user.get('username', 'Неизвестный') if seller_user else 'Неизвестный'
        await bot.send_message(
            result["seller_id"],
            f"💰 Ваш лот продан!\n\n"
            f"📦 {item_name} x{result['quantity']}\n"
            f"💎 Получено: {result['total_price']} дань"
        )
    except Exception:
        pass  # Если не удалось отправить уведомление, игнорируем
    
    # Возвращаемся в аукцион
    await menu_auction_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("auction_buy_qty:"))
async def auction_buy_qty_callback(callback: types.CallbackQuery):
    """Покупка определенного количества предметов с аукциона"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    _, auction_id_str, qty_str = parts
    auction_id = int(auction_id_str)
    buy_quantity = int(qty_str)
    user_id = callback.from_user.id
    
    from database import buy_auction_item_partial
    
    try:
        # Покупаем указанное количество предметов с таймаутом 999 мс
        result = await asyncio.wait_for(
            asyncio.to_thread(buy_auction_item_partial, user_id, auction_id, buy_quantity),
            timeout=0.999
        )
    except asyncio.TimeoutError:
        await callback.answer("⏱️ Операция заняла слишком много времени. Попробуйте позже.", show_alert=True)
        return
    except Exception as e:
        await callback.answer(f"❌ Ошибка покупки: {e}", show_alert=True)
        return
        
    try:
        
        if "error" in result:
            await callback.answer(result["error"], show_alert=True)
            return
        
        # Успешная покупка
        item_name = ITEMS_CONFIG.get(result["item_id"], {}).get('name', result["item_id"])
        actual_quantity = result.get('quantity', buy_quantity)
        
        await callback.answer(f"✅ Куплено: {item_name} x{actual_quantity} за {result['total_price']} дань!")
        
        # Уведомляем продавца
        try:
            seller_id = int(result["seller_id"]) if isinstance(result["seller_id"], str) else result["seller_id"]
            seller_display_name = get_display_name(seller_id)
            
            await bot.send_message(
                result["seller_id"],
                f"💰 Ваш лот продан!\n\n"
                f"📦 {item_name} x{actual_quantity}\n"
                f"💎 Получено: {result['total_price']} дань"
            )
        except Exception:
            pass
    
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        return
    
    # Возвращаемся в аукцион
    await menu_auction_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("auction_custom_qty:"))
async def auction_custom_qty_callback(callback: types.CallbackQuery):
    """Запрос пользовательского количества для покупки"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, auction_id = callback.data.split(":")
    
    # Сохраняем auction_id в контексте пользователя для последующего использования
    user_id = callback.from_user.id
    
    await callback.answer(
        "✏️ Ответьте на это сообщение и напишите нужное количество предметов для покупки",
        show_alert=True
    )
    
    # Отправляем сообщение для ответа
    reply_msg = await callback.message.reply(
        f"🛒 Укажите количество предметов для покупки с лота #{auction_id}:\n\n"
        f"💡 Ответьте на это сообщение числом"
    )
    
    # Сохраняем связь сообщения с лотом (простое решение)
    if not hasattr(auction_custom_qty_callback, 'pending_purchases'):
        auction_custom_qty_callback.pending_purchases = {}
    
    auction_custom_qty_callback.pending_purchases[reply_msg.message_id] = {
        'auction_id': int(auction_id),
        'user_id': user_id
    }

# Обработчик ответов на сообщения для указания количества в аукционе
@dp.message(lambda m: m.reply_to_message and m.text and m.text.strip().isdigit())
async def handle_auction_quantity_reply(message: types.Message):
    """Обработчик ввода количества для покупки с аукциона"""
    if not message.from_user or not message.reply_to_message:
        return
    
    # Проверяем, есть ли ожидающая покупка для этого сообщения
    if not hasattr(auction_custom_qty_callback, 'pending_purchases'):
        return
    
    reply_to_id = message.reply_to_message.message_id
    if reply_to_id not in auction_custom_qty_callback.pending_purchases:
        return
    
    purchase_data = auction_custom_qty_callback.pending_purchases[reply_to_id]
    
    # Проверяем, что отвечает правильный пользователь
    if message.from_user.id != purchase_data['user_id']:
        return
    
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.reply("❌ Количество должно быть больше 0!")
            return
        
        auction_id = purchase_data['auction_id']
        user_id = message.from_user.id
        
        # Удаляем из ожидающих покупок
        del auction_custom_qty_callback.pending_purchases[reply_to_id]
        
        from database import buy_auction_item
        
        # Сначала проверяем информацию о лоте
        try:
            import sqlite3
            conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
            cur = conn.cursor()
            
            cur.execute("""
                SELECT quantity, price_per_item, status
                FROM auction_items WHERE id = ?
            """, (auction_id,))
            
            auction_info = cur.fetchone()
            conn.close()
            
            if not auction_info:
                await message.reply("❌ Лот не найден")
                return
                
            available_quantity, price_per_item, status = auction_info
            
            if status != 'active':
                await message.reply("❌ Лот уже продан или неактивен")
                return
            
            # Проверяем, что запрошенное количество не больше доступного
            if available_quantity < quantity:
                await message.reply(f"❌ В лоте только {available_quantity} предметов!")
                return
            
            # Покупаем весь лот (пока нет поддержки частичной покупки) с таймаутом
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(buy_auction_item, user_id, auction_id),
                    timeout=0.999
                )
            except asyncio.TimeoutError:
                await message.reply("⏱️ Операция заняла слишком много времени. Попробуйте позже.")
                return
            
            if "error" in result:
                await message.reply(f"❌ {result['error']}")
                return
            
            # Успешная покупка
            item_name = ITEMS_CONFIG.get(result["item_id"], {}).get('name', result["item_id"])
            actual_quantity = result.get('quantity', quantity)
            
            await message.reply(f"✅ Куплено: {item_name} x{actual_quantity} за {result['total_price']} дань!")
            
            # Уведомляем продавца
            try:
                seller_id = int(result["seller_id"]) if isinstance(result["seller_id"], str) else result["seller_id"]
                seller_display_name = get_display_name(seller_id)
                
                await bot.send_message(
                    result["seller_id"],
                    f"💰 Ваш лот продан!\n\n"
                    f"📦 {item_name} x{actual_quantity}\n"
                    f"💎 Получено: {result['total_price']} дань"
                )
            except Exception:
                pass
        
        except Exception as db_error:
            await message.reply(f"❌ Ошибка проверки лота: {db_error}")
            return
        
    except ValueError:
        await message.reply("❌ Введите корректное число!")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
        # Удаляем из ожидающих покупок в случае ошибки
        if reply_to_id in auction_custom_qty_callback.pending_purchases:
            del auction_custom_qty_callback.pending_purchases[reply_to_id]

@dp.callback_query(lambda c: c.data.startswith("auction_remove:"))
async def auction_remove_callback(callback: types.CallbackQuery):
    """Снятие лота с аукциона"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, auction_id = callback.data.split(":")
    auction_id = int(auction_id)
    user_id = callback.from_user.id
    
    from database import remove_auction_item
    
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(remove_auction_item, user_id, auction_id),
            timeout=0.999
        )
    except asyncio.TimeoutError:
        await callback.answer("⏱️ Операция заняла слишком много времени. Попробуйте позже.", show_alert=True)
        return
    
    if "error" in result:
        await callback.answer(result["error"], show_alert=True)
        return
    
    # Успешное снятие
    # Используем уже загруженную конфигурацию ITEMS_CONFIG из начала файла
    item_name = ITEMS_CONFIG.get(result["item_id"], {}).get('name', result["item_id"])
    
    await callback.answer(f"✅ Лот снят: {item_name} x{result['quantity']} возвращено в инвентарь")
    
    # Возвращаемся в аукцион
    await menu_auction_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("my_lot_remove:"))
async def my_lot_remove_confirm_callback(callback: types.CallbackQuery):
    """Подтверждение снятия лота из 'Мои лоты'"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, auction_id = callback.data.split(":")
    auction_id = int(auction_id)
    user_id = callback.from_user.id
    
    # Получаем информацию о лоте для подтверждения
    from database import get_auction_items
    auction_data = get_auction_items(page=1, per_page=100, seller_id=user_id)
    
    # Находим нужный лот
    target_lot = None
    for lot in auction_data["items"]:
        if lot[0] == auction_id:  # lot[0] = auction_id
            target_lot = lot
            break
    
    if not target_lot:
        await callback.answer("❌ Лот не найден", show_alert=True)
        return
    
    auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status = target_lot
    item_name = ITEMS_CONFIG.get(item_id, {}).get('name', item_id)
    total_price = quantity * price_per_item
    
    text = f"❌ <b>СНЯТИЕ ЛОТА</b>\n\n"
    text += f"📦 <b>{item_name}</b> x{quantity}\n"
    text += f"💰 Цена: {price_per_item} дань/шт\n"
    text += f"💎 Общая стоимость: {total_price} дань\n\n"
    text += "⚠️ Вы действительно хотите снять лот с продажи?\n"
    text += "Предметы вернутся в инвентарь."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, снять", callback_data=f"auction_remove:{auction_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="auction_my_lots")
        ]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "auction_my_lots")
async def auction_my_lots_callback(callback: types.CallbackQuery):
    """Мои лоты на аукционе"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    
    from database import get_auction_items
    
    # Получаем лоты пользователя
    auction_data = get_auction_items(page=1, per_page=10, seller_id=user_id)
    items = auction_data["items"]
    
    if not items:
        text = "📤 <b>МОИ ЛОТЫ</b>\n\n❌ У вас нет активных лотов"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_auction:{user_id}")]
        ])
    else:
        text = f"📤 <b>МОИ ЛОТЫ</b> ({len(items)})\n\n"
        
        # Импортируем конфигурацию
        # Используем уже загруженную конфигурацию ITEMS_CONFIG из начала файла
        text += f"💡 Нажмите на номер лота чтобы снять его с продажи\n\n"
        
        for i, (auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status) in enumerate(items, 1):
            item_name = ITEMS_CONFIG.get(item_id, {}).get('name', item_id)
            total_price = quantity * price_per_item
            
            # Время до окончания
            import time
            remaining_time = expires_at - int(time.time())
            hours_left = remaining_time // 3600
            
            text += f"{i}. <b>{item_name}</b> x{quantity}\n"
            text += f"   💰 {total_price} дань\n"
            text += f"   ⏰ {hours_left}ч\n"
            text += f"   🆔 #{auction_id}\n\n"
        
        # Кнопки с цифрами лотов
        kb_buttons = []
        
        # Кнопки для снятия лотов (1-9)
        lot_buttons = []
        for i in range(min(9, len(items))):
            lot_num = i + 1
            auction_id = items[i][0]  # Получаем auction_id из данных
            lot_buttons.append(InlineKeyboardButton(text=f"{lot_num}", callback_data=f"my_lot_remove:{auction_id}"))
            if len(lot_buttons) == 3:  # По 3 кнопки в ряд
                kb_buttons.append(lot_buttons)
                lot_buttons = []
        if lot_buttons:  # Добавляем оставшиеся кнопки
            kb_buttons.append(lot_buttons)
        
        kb_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_auction:{user_id}")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")

# Новый обработчик для выставления на аукцион из инвентаря
@dp.callback_query(lambda c: c.data.startswith("auction_start:"))
async def callback_auction_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало выставления на аукцион - шаг 1: выбор количества"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    _, item_id, page = callback.data.split(":")
    user_id = callback.from_user.id
    
    # Получаем количество предметов
    items, _, _ = get_user_inventory(user_id, int(page))
    count = 0
    for iid, cnt in items:
        if iid == item_id:
            count = cnt
            break
    
    if count == 0:
        await callback.answer("У вас нет этого предмета", show_alert=True)
        return
    
    # Получаем информацию о предмете
    # Используем уже загруженную конфигурацию ITEMS_CONFIG из начала файла
    
    item_config = ITEMS_CONFIG.get(item_id, {})
    item_name = item_config.get('name', item_id)
    
    # Сохраняем данные в состоянии
    message_id = callback.message.message_id if callback.message else None
    await state.update_data(
        item_id=item_id, 
        page=page, 
        max_count=count, 
        item_name=item_name,
        message_id=message_id  # Сохраняем ID сообщения
    )
    
    # Создаем кнопки для быстрого выбора количества
    kb_buttons = []
    
    # Кнопки быстрого выбора количества
    quick_amounts = []
    if count >= 1:
        quick_amounts.append(1)
    if count >= 5:
        quick_amounts.append(5)
    if count >= 10:
        quick_amounts.append(10)
    if count >= count and count not in quick_amounts:
        quick_amounts.append(count)  # Все доступное количество
    
    # Создаем ряды кнопок
    if quick_amounts:
        row = []
        for amount in quick_amounts:
            row.append(InlineKeyboardButton(text=f"{amount} шт.", callback_data=f"auction_qty:{amount}"))
            if len(row) == 3:  # Максимум 3 кнопки в ряду
                kb_buttons.append(row)
                row = []
        if row:  # Добавляем оставшиеся кнопки
            kb_buttons.append(row)
    
    # Кнопка "Другое количество" и "Назад"
    kb_buttons.append([
        InlineKeyboardButton(text="✍️ Другое количество", callback_data="auction_qty:custom")
    ])
    kb_buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_item:{items.index((item_id, count))+1}:{page}")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    
    text = f"🏪 <b>Выставление на аукцион</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📊 У вас: <b>{count} шт.</b>\n\n"
    text += f"❓ Сколько штук хотите продать?"
    
    await callback.answer()
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(AuctionStates.waiting_for_quantity)

@dp.callback_query(lambda c: c.data.startswith("auction_qty:"))
async def callback_auction_quantity(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора количества для аукциона"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец аукциона
    data = await state.get_data()
    owner_user_id = data.get("user_id")
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваш аукцион!", show_alert=True)
        return
    
    _, qty_str = callback.data.split(":")
    max_count = data.get("max_count", 1)
    item_name = data.get("item_name", "Предмет")
    
    if qty_str == "custom":
        # Пользователь выбрал "Другое количество"
        text = f"✍️ <b>Укажите количество</b>\n\n"
        text += f"🎯 Предмет: <b>{item_name}</b>\n"
        text += f"📊 Доступно: <b>{max_count} шт.</b>\n\n"
        text += f"💬 Введите количество (от 1 до {max_count}):"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
        ])
        
        # Редактируем исходное сообщение используя сохраненные данные
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")
        
        if chat_id and message_id:
            try:
                await safe_edit_by_id(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка редактирования сообщения пользовательского количества: {e}")
        
        await state.set_state(AuctionStates.waiting_for_quantity)
        return
    
    try:
        quantity = int(qty_str)
        if quantity < 1 or quantity > max_count:
            await callback.answer(f"Неверное количество! Доступно: {max_count}", show_alert=True)
            return
    except ValueError:
        await callback.answer("Ошибка в количестве", show_alert=True)
        return
    
    # Сохраняем количество и сразу переходим к вводу цены (только дань)
    await state.update_data(quantity=quantity, currency="dan")
    
    # Показываем ввод цены (без выбора валюты)
    text = f"💰 <b>Укажите цену</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📦 Количество: <b>{quantity} шт.</b>\n"
    text += f"💱 Валюта: <b>💰 Дань</b> (фиксировано)\n\n"
    text += f"⚠️ <b>Минимальная цена: 1000 дань</b> за штуку\n"
    text += f"💬 Введите цену за 1 штуку (минимум 1 000):"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
    ])
    
    await callback.answer()
    
    # Редактируем исходное сообщение используя сохраненные данные
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    
    if chat_id and message_id:
        try:
            await safe_edit_by_id(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка редактирования сообщения цены: {e}")
    
    await state.set_state(AuctionStates.waiting_for_price)  # Сразу переходим к ожиданию цены

@dp.message(AuctionStates.waiting_for_quantity)
async def auction_process_custom_quantity(message: types.Message, state: FSMContext):
    """Простой ввод количества без reply."""
    data = await state.get_data()
    
    # Проверяем, что сообщение от владельца аукциона
    owner_user_id = data.get("user_id")
    if not owner_user_id or owner_user_id != message.from_user.id:
        # Это не владелец состояния - игнорируем
        return
    
    message_id = data.get("message_id")
    chat_id = data.get("chat_id", message.chat.id)
    item_name = data.get("item_name", "Предмет")
    max_count = data.get("max_count", 1)

    # Парсим число
    try:
        quantity = int(message.text.strip())
        if quantity < 1 or quantity > max_count:
            raise ValueError("bad range")
    except Exception:
        await message.delete()
        if message_id:
            err = (f"❌ <b>Ошибка ввода!</b>\n\n🎯 Предмет: <b>{item_name}</b>\n📊 Доступно: <b>{max_count} шт.</b>\n\n"
                   f"⚠️ Введите число от 1 до {max_count}.\nВведите количество:" )
            try:
                await safe_edit_by_id(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=err,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
                    ]),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return

    # OK
    await state.update_data(quantity=quantity, currency="dan")
    await message.delete()

    text = (f"💰 <b>Укажите цену</b>\n\n"
            f"🎯 Предмет: <b>{item_name}</b>\n"
            f"📦 Количество: <b>{quantity} шт.</b>\n"
            f"💱 Валюта: <b>💰 Дань</b> (фиксировано)\n\n"
            f"⚠️ <b>Минимальная цена: 1000 дань</b> за штуку\n"
            f"✏️ Введите цену за 1 штуку числом (минимум 1000):")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
    ])
    if message_id:
        try:
            await safe_edit_by_id(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    await state.set_state(AuctionStates.waiting_for_price)

# УСТАРЕЛ: Обработчик выбора валюты больше не используется (всегда дань)
@dp.callback_query(lambda c: c.data.startswith("old_auction_currency:"))
async def callback_old_auction_currency(callback: types.CallbackQuery, state: FSMContext):
    """УСТАРЕВШИЙ обработчик выбора валюты - теперь всегда только дань"""
    await callback.answer("Выбор валюты убран - используется только дань", show_alert=True)

@dp.message(AuctionStates.waiting_for_price)
async def auction_process_price(message: types.Message, state: FSMContext):
    """Обработка цены: принимает числовой ввод в состоянии ожидания цены."""
    data = await state.get_data()
    
    # Проверяем, что сообщение от владельца аукциона
    owner_user_id = data.get("user_id")
    if not owner_user_id or owner_user_id != message.from_user.id:
        # Это не владелец состояния - игнорируем
        return
    
    item_name = data.get("item_name", "Предмет")
    quantity = data.get("quantity", 1)
    message_id = data.get("message_id")
    chat_id = data.get("chat_id", message.chat.id)
    currency_unit = "дань"

    # Проверяем, что содержит ТОЛЬКО цифры (никаких букв, символов)
    if not message.text or not message.text.strip().isdigit():
        return

    # Парсим цену
    try:
        price = int(message.text.strip())
        if price < 1000:
            raise ValueError
    except Exception:
        # Некорректно: удаляем ответ пользователя и подсвечиваем форму
        try:
            await message.delete()
        except Exception:
            pass
        if message_id:
            err = (f"❌ <b>Ошибка цены!</b>\n\n🎯 Предмет: <b>{item_name}</b>\n"
                   f"📦 Количество: <b>{quantity} шт.</b>\n"
                   f"⚠️ Минимальная цена: <b>1000 {currency_unit}</b> за штуку.\n"
                   f"✏️ Ответьте числом (мин. 1000):")
            try:
                await safe_edit_by_id(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=err,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")],
                        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
                    ]),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return

    # OK
    await state.update_data(price=price)
    await message.delete()

    item_id = data.get("item_id")
    # Поддержка животных с форматом base@owned_id в состоянии FSM
    if item_id and "@" in item_id:
        base_id = item_id.split("@", 1)[0]
    else:
        base_id = item_id
    item_emoji = ITEMS_CONFIG.get(base_id, {}).get("emoji", "🎁")
    total_cost = quantity * price

    import time
    from datetime import datetime
    expires_timestamp = int(time.time()) + (14 * 24 * 3600)
    expires_str = datetime.fromtimestamp(expires_timestamp).strftime("%d.%m.%Y %H:%M")

    text = (f"✅ <b>Подтверждение выставления</b>\n\n"
            f"🎯 Предмет: {item_emoji} <b>{item_name}</b>\n"
            f"📦 Количество: <b>{quantity} шт.</b>\n"
            f"💰 Цена за штуку: <b>{price:,} {currency_unit}</b>\n"
            f"💵 Общая стоимость: <b>{total_cost:,} {currency_unit}</b>\n"
            f"⏰ Время: до <b>{expires_str}</b>\n\n"
            f"❓ Подтвердить выставление на аукцион?")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="auction_confirm")],
        [InlineKeyboardButton(text="⬅️ Изменить", callback_data="auction_back_to_price")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
    ])
    if message_id:
        try:
            await safe_edit_by_id(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    await state.set_state(AuctionStates.confirm_listing)

# Кнопки "Назад"
@dp.callback_query(lambda c: c.data == "auction_back_to_qty")
async def callback_auction_back_to_qty(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору количества"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец аукциона
    data = await state.get_data()
    owner_user_id = data.get("user_id")
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваш аукцион!", show_alert=True)
        return
    
    item_name = data.get("item_name", "Предмет")
    max_count = data.get("max_count", 1)
    
    text = f"📦 <b>Выбор количества</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📊 Доступно: <b>{max_count} шт.</b>\n\n"
    text += f"❓ Сколько штук выставить на продажу?"
    
    # Создаем кнопки для быстрого выбора количества
    buttons = []
    quick_amounts = []
    
    if max_count >= 1:
        quick_amounts.append(1)
    if max_count >= 5:
        quick_amounts.append(5)
    if max_count >= 10:
        quick_amounts.append(10)
    if max_count >= 50:
        quick_amounts.append(50)
    
    # Если у нас максимум предметов не входит в быстрые кнопки, добавляем его
    if max_count not in quick_amounts and max_count <= 100:
        quick_amounts.append(max_count)
    
    # Создаем строки кнопок по 2-3 кнопки в ряд
    for i in range(0, len(quick_amounts), 3):
        row = [InlineKeyboardButton(text=f"{amt}", callback_data=f"auction_qty:{amt}") 
               for amt in quick_amounts[i:i+3]]
        buttons.append(row)
    
    # Добавляем кнопку "Другое количество" если нужно
    if max_count > 100 or (max_count > 1 and max_count not in quick_amounts):
        buttons.append([InlineKeyboardButton(text="✏️ Другое количество", callback_data="auction_qty:custom")])
    
    # Кнопка отмены
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.answer()
    
    # Редактируем исходное сообщение используя сохраненные данные
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    
    if chat_id and message_id:
        try:
            await safe_edit_by_id(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка редактирования сообщения возврата к количеству: {e}")
    
    await state.set_state(AuctionStates.waiting_for_quantity)

@dp.callback_query(lambda c: c.data == "auction_back_to_currency")
async def callback_auction_back_to_currency(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору валюты"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    data = await state.get_data()
    item_name = data.get("item_name", "Предмет")
    quantity = data.get("quantity", 1)
    
    # Показываем меню выбора валюты
    text = f"💱 <b>Выбор валюты</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📦 Количество: <b>{quantity} шт.</b>\n\n"
    text += f"❓ В какой валюте устанавливать цену?"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Дань", callback_data="auction_currency:dan"),
            InlineKeyboardButton(text="💎 Золото", callback_data="auction_currency:kruz")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")]
    ])
    
    await callback.answer()
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb)
    await state.set_state(AuctionStates.waiting_for_currency)

@dp.callback_query(lambda c: c.data == "auction_back_to_price")
async def callback_auction_back_to_price(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к вводу цены"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец аукциона
    data = await state.get_data()
    owner_user_id = data.get("user_id")
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваш аукцион!", show_alert=True)
        return
    
    item_name = data.get("item_name", "Предмет")
    quantity = data.get("quantity", 1)
    
    # Показываем ввод цены
    text = f"💰 <b>Укажите цену</b>\n\n"
    text += f"🎯 Предмет: <b>{item_name}</b>\n"
    text += f"📦 Количество: <b>{quantity} шт.</b>\n\n"
    text += f"⚠️ <b>Минимальная цена: 1000 дань</b> за штуку\n"
    text += f"💬 Введите цену за 1 штуку (минимум 1 000):"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="auction_back_to_qty")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="auction_cancel")]
    ])
    
    await callback.answer()
    
    # Редактируем исходное сообщение используя сохраненные данные
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    
    if chat_id and message_id:
        try:
            await safe_edit_by_id(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка редактирования сообщения возврата к цене: {e}")
    
    await state.set_state(AuctionStates.waiting_for_price)

@dp.callback_query(lambda c: c.data == "auction_confirm")
async def callback_auction_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выставления на аукцион"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец аукциона
    data = await state.get_data()
    owner_user_id = data.get("user_id")
    if owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваш аукцион!", show_alert=True)
        return
    
    user_id = callback.from_user.id
    item_id = data.get("item_id")
    quantity = data.get("quantity", 1)
    price = data.get("price", 1)
    currency = data.get("currency", "dan")
    
    # Пока поддерживаем только дань, в будущем добавим золото
    if currency != "dan":
        await callback.answer("❌ Пока поддерживается только дань", show_alert=True)
        return
    
    # Выставляем на аукцион с фиксированным временем 14 дней с таймаутом
    from database import add_auction_item
    
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(add_auction_item, user_id, item_id, quantity, price, 14 * 24),
            timeout=0.999
        )
    except asyncio.TimeoutError:
        await callback.answer("⏱️ Операция заняла слишком много времени. Попробуйте позже.", show_alert=True)
        await state.clear()
        return
    
    if "error" in result:
        await callback.answer(f"❌ {result['error']}", show_alert=True)
        await state.clear()
        return
    
    # Успешно выставлено
    # Используем уже загруженную конфигурацию ITEMS_CONFIG из начала файла
    # Поддержка pseudo-ID в состоянии FSM
    base_id = item_id.split("@", 1)[0] if item_id and "@" in item_id else item_id
    item_name = ITEMS_CONFIG.get(base_id, {}).get('name', base_id)
    item_emoji = ITEMS_CONFIG.get(base_id, {}).get("emoji", "🎁")
    # Форматирование валюты
    currency_name = "Дань 🪙" if currency == "dan" else "⭐ Stars"
    total_cost = quantity * price
    
    # Вычисляем время окончания аукциона
    import time
    from datetime import datetime, timedelta
    
    expires_timestamp = int(time.time()) + (14 * 24 * 3600)  # 14 дней в секундах
    expires_date = datetime.fromtimestamp(expires_timestamp)
    expires_str = expires_date.strftime("%d.%m.%Y %H:%M")
    
    # Красивое форматирование чисел
    def fmt(n: int):
        return f"{n:,}".replace(",", " ")

    text = (
        "✅ <b>Лот выставлен на аукцион!</b>\n"
        "____________________________\n"
        f"🎯 Предмет: {item_emoji} <b>{item_name}</b>\n"
        f"📦 Количество: <b>{fmt(quantity)} шт.</b>\n"
        f"💰 Цена за штуку: <b>{fmt(price)} {currency_name}</b>\n"
        f"💵 Общая стоимость: <b>{fmt(total_cost)} {currency_name}</b>\n"
        f"⏰ До окончания: <b>{expires_str}</b> (14 дней)\n"
        f"🆔 Лот ID: <b>#{result['auction_id']}</b>\n"
        "____________________________\n"
        "📤 Лот теперь доступен в разделе 'Мои лоты'"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Мои лоты", callback_data="auction_my_lots")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data=f"menu_inventory:{user_id}")]
    ])
    
    await callback.answer("✅ Лот выставлен!")
    await safe_edit_text_or_caption(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await state.clear()

@dp.callback_query(lambda c: c.data == "auction_cancel")
async def callback_auction_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена выставления на аукцион"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Проверяем, что кнопку нажал владелец аукциона
    data = await state.get_data()
    owner_user_id = data.get("user_id")
    if owner_user_id and owner_user_id != callback.from_user.id:
        await callback.answer("❌ Это не ваш аукцион!", show_alert=True)
        return
    
    await callback.answer("❌ Выставление отменено")
    await state.clear()
    
    # Возвращаемся в инвентарь с обновлённой картинкой
    user_id = callback.from_user.id
    items, total, max_page = get_user_inventory(user_id, page=1, force_sync=True)
    
    # Рендерим картинку инвентаря с поддержкой животных
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
    
    # Используем кешированное изображение
    photo_path = get_cached_image(grid_items, item_images)
    text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
    kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
    
    try:
        media = InputMediaPhoto(media=FSInputFile(photo_path), caption=text)
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        await callback.message.edit_text(text, reply_markup=kb)

# --- СИСТЕМА КЕЙСОВ ---
@dp.callback_query(lambda c: c.data.startswith("open_slot:"))
async def callback_open_slot(callback: types.CallbackQuery):
    """Обработчик открытия слота в кейсе"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
        
    try:
        _, case_type, slot_index = callback.data.split(":")
        slot_index = int(slot_index)
        user_id = callback.from_user.id
        message_id = callback.message.message_id
        
        from plugins.games.case_system import get_case_session, give_reward_to_user, get_case_photo_path
        
        session = get_case_session(user_id, message_id)
        if not session:
            await callback.answer("Сессия истекла", show_alert=True)
            return
            
        # Открываем слот
        reward = session.open_slot(slot_index)
        if "error" in reward:
            await callback.answer(reward["error"], show_alert=True)
            return
            
        # Выдаем награду игроку
        give_reward_to_user(user_id, reward)
        
        # Обновляем сообщение
        try:
            photo_path = get_case_photo_path(case_type)
            media = InputMediaPhoto(
                media=FSInputFile(photo_path),
                caption=session.get_status_text()
            )
            
            if can_edit_media(user_id):
                await callback.message.edit_media(media=media, reply_markup=session.get_keyboard())
            else:
                # Кулдаун на media — обновим хотя бы подпись/клавиатуру
                await safe_edit_text_or_caption(callback.message, session.get_status_text(), reply_markup=session.get_keyboard())
        except Exception:
            # Fallback без фото
            await safe_edit_text_or_caption(
                callback.message,
                session.get_status_text(),
                reply_markup=session.get_keyboard()
            )
            
        # Уведомление о награде
        if reward["type"] == "empty":
            await callback.answer("💫 Пусто...")
        elif reward["type"] == "money":
            await callback.answer(f"💰 Получено {reward['amount']} Дань!")
        elif reward["type"] == "random_chest":
            await callback.answer(f"🧳 Получен случайный сундук!")
        elif reward["type"] == "wheat":
            await callback.answer(f"🌾 Получена пшеница!")
        elif reward["type"] == "corn":
            await callback.answer(f"🌽 Получена кукуруза!")
            
    except Exception as e:
        await callback.answer("Ошибка открытия слота", show_alert=True)

@dp.callback_query(lambda c: c.data == "close_case")
async def callback_close_case(callback: types.CallbackQuery):
    """Закрывает сессию кейса и возвращает к инвентарю"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
        
    user_id = callback.from_user.id
    message_id = callback.message.message_id
    
    from plugins.games.case_system import close_case_session
    
    # Закрываем сессию
    close_case_session(user_id, message_id)
    
    await callback.answer("✅ Открытие кейса завершено!")
    
    try:
        # Принудительно показываем инвентарь
        items, total, max_page = get_user_inventory(user_id, page=1)
        
        # Подготовим данные для рендера
        grid_items = []
        item_images = {}
        for item_id, count in items:
            if item_id == "empty":
                name = "Пусто"
                icon_path = NULL_ITEM["photo_square"]
                grid_items.append((item_id, count, name))
                item_images[item_id] = icon_path
            elif item_id in ITEMS_CONFIG:
                # Показываем только предметы которые есть в конфигурации
                name = ITEMS_CONFIG[item_id]["name"]
                icon_path = ITEMS_CONFIG[item_id]["photo_square"]
                grid_items.append((item_id, count, name))
                item_images[item_id] = icon_path
            else:
                # Пропускаем предметы без конфигурации
                print(f"⚠️ Предмет {item_id} пропущен в callback_close_case - отсутствует в ITEMS_CONFIG")
                continue
        
        # Используем кешированное изображение
        photo_path = get_cached_image(grid_items, item_images)
        text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
        kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
        
        media = types.InputMediaPhoto(media=FSInputFile(photo_path), caption=text)
        
        user_id = callback.from_user.id
        if not can_edit_media(user_id):
            await callback.answer("⏳ Подождите немного", show_alert=False)
            return
            
        await callback.message.edit_media(media=media, reply_markup=kb)
    except Exception as e:
        print(f"Ошибка при возврате к инвентарю: {e}")
        # Fallback - просто удаляем клавиатуру
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

# --- Обработчик кнопки "Назад" из инвентаря ---
@dp.callback_query(lambda c: c.data == "back_to_main_menu")
async def back_to_main_menu_callback(callback: types.CallbackQuery):
    if not callback.message or not callback.from_user:
        return
    
    user_id = callback.from_user.id
    
    try:
        # Сначала отвечаем на callback, чтобы убрать "часики"
        await callback.answer()
    except Exception:
        # Если callback устарел, игнорируем
        pass
    
    # Используем новые утилиты для создания главного меню
    out_path = prepare_main_menu_image()
    menu_kb = create_main_menu_keyboard(user_id)
    
    try:
        media = types.InputMediaPhoto(media=FSInputFile(out_path), caption="🎮 Главное меню игры")
        await callback.message.edit_media(media=media, reply_markup=menu_kb)
    except Exception as e:
        # Если не удалось изменить сообщение, попробуем отправить новое
        try:
            if callback.message and callback.message.chat:
                await callback.message.delete()
                await bot.send_photo(chat_id=callback.message.chat.id, photo=FSInputFile(out_path), caption="🎮 Главное меню игры", reply_markup=menu_kb)
        except Exception:
            # В крайнем случае просто логируем ошибку
            print(f"Ошибка возврата в главное меню: {e}")

# --- МАГАЗИН ---
from inv_py.shop import (
    build_shop_main_menu, get_all_shop_items, get_item_by_slot,
    render_category_image,
    purchase_item, can_afford_item, init_shop, SHOP_ITEMS,
    get_category_items, build_shop_category_menu, SHOP_CATEGORIES
)

 


# removed debug dump/check commands

@dp.callback_query(lambda c: getattr(c, 'data', None) and c.data.startswith("menu_shop"))
async def menu_shop_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    """Главное меню магазина"""
    # краткий лог начала обработки (помогает отловить случаи, когда callback устарел)
    try:
        uid = callback.from_user.id if getattr(callback, 'from_user', None) else None
    except Exception:
        uid = None
    # (debug logging removed)
    user_id = callback.from_user.id

    # Если в callback.data передан owner id (menu_shop:OWNER), проверяем владельца
    try:
        parts = (callback.data or "").split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            owner_user_id = int(parts[1])
            if owner_user_id != user_id:
                try:
                    await callback.answer("❌ Это не ваше место!", show_alert=True)
                except Exception:
                    pass
                return
    except Exception:
        pass
    
    # Получаем баланс пользователя
    user_row = db.get_user(user_id)
    dan_balance = 0.0
    kruz_balance = 0
    if user_row:
        try:
            dan_balance = float(user_row.get("dan", 0))
        except Exception:
            dan_balance = 0.0
        try:
            kruz_balance = int(user_row.get("kruz", 0))
        except Exception:
            kruz_balance = 0
    
    dan_balance = 0.00 if abs(dan_balance) < 0.005 else round(dan_balance, 2)
    
    # Основная логика: предпочитаем графическое представление (image-grid). Если что-то ломается — откатываемся к тексту.
    try:
        await callback.answer()
    except Exception:
        pass

    # Получаем данные для первой страницы
    items, total, max_page = get_all_shop_items(page=1)
    keyboard = build_shop_main_menu(page=1, max_page=max_page)

    try:
        from inv_py.shop import render_shop_grid
        shop_image_path = render_shop_grid(page=1, font_path="C:/Windows/Fonts/arial.ttf")

        caption = (
            f"🛍️ <b>Магазин</b>\n\n"
            f"💰 Ваш баланс:\n🪙 Дань: {format_number_beautiful(dan_balance)}\n"
            f"⭐ Stars: {format_number_beautiful(kruz_balance)}\n\n"
            f"Всего товаров: {total}\nСтраница 1 из {max_page}"
        )

        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=FSInputFile(shop_image_path), caption=caption, parse_mode="HTML"),
                reply_markup=keyboard
            )
        except Exception:
            # Если редактирование не получилось — отправляем новое фото и удаляем старое
            try:
                if getattr(callback, 'message', None) and getattr(callback.message, 'chat', None):
                    chat_id = callback.message.chat.id
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                    await bot.send_photo(chat_id=chat_id, photo=FSInputFile(shop_image_path), caption=caption, reply_markup=keyboard, parse_mode="HTML")
                else:
                    # Отправляем лично
                    await bot.send_photo(chat_id=callback.from_user.id, photo=FSInputFile(shop_image_path), caption=caption, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                try:
                    await callback.answer("Магазин временно недоступен", show_alert=True)
                except Exception:
                    pass
        finally:
            try:
                if shop_image_path and os.path.exists(shop_image_path):
                    os.remove(shop_image_path)
            except Exception:
                pass
    except Exception:
        # Фолбек: текстовое представление
        caption_lines = [f"🛍️ <b>Магазин</b>", "", f"💰 Ваш баланс:", f"🪙 Дань: {format_number_beautiful(dan_balance)}", f"⭐ Stars: {format_number_beautiful(kruz_balance)}", ""]
        try:
            for idx, entry in enumerate(items, start=1):
                iid = entry[0]
                if iid and iid != 'empty':
                    name = ITEMS_CONFIG.get(iid, {}).get('name', iid)
                    caption_lines.append(f"[{idx}] {name}")
                else:
                    caption_lines.append(f"[{idx}] —")
        except Exception:
            pass

        caption = "\n".join(caption_lines)
        try:
            success = await safe_edit_text_or_caption(callback.message, caption, reply_markup=keyboard, parse_mode="HTML")
            if not success:
                await callback.message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            try:
                await bot.send_message(callback.from_user.id, caption, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                try:
                    await callback.answer("Не удалось открыть магазин", show_alert=True)
                except Exception:
                    pass

# Обработчик для приватных кнопок магазина с проверкой владельца
@dp.callback_query(lambda c: c.data.startswith("menu_shop:"))
async def menu_shop_private_callback(callback: types.CallbackQuery):
    """Обработчик приватных кнопок магазина с проверкой владельца"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    current_user_id = callback.from_user.id
    username = callback.from_user.username or "unknown"
    
    # Проверяем, что кнопку нажал владелец меню
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
        print(f"DEBUG: menu_shop - user: @{username}, owner_id: {owner_user_id}, current_id: {current_user_id}")
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных кнопки", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        print(f"DEBUG: BLOCKING SHOP ACCESS - owner: {owner_user_id}, current: {current_user_id}")
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
        await callback.answer("❌ Это не ваше место!", show_alert=True)
        return
    
    # Вызываем основной обработчик магазина
    await menu_shop_callback(callback)

@dp.callback_query(lambda c: c.data == "shop_main")
async def shop_main_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    """Возврат к главному меню магазина"""
    await menu_shop_callback(callback)

# Новый обработчик для навигации по страницам магазина
@dp.callback_query(lambda c: c.data.startswith("shop_page:"))
async def shop_page_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    try:
        # Импортируем новую функцию рендера магазина
        from inv_py.shop import render_shop_grid
        
        _, page = callback.data.split(":")
        page = int(page)

        # Получаем данные для страницы
        items, total, max_page = get_all_shop_items(page=page)

        # Используем новую функцию рендера, которая показывает сток и серым цветом товары с 0 шт
        shop_image_path = render_shop_grid(page=page)
        
        # Кнопки используют функцию build_shop_main_menu
        keyboard = build_shop_main_menu(page=page, max_page=max_page)
        
        # Получаем баланс пользователя для caption
        user_id = callback.from_user.id
        user_row = db.get_user(user_id)
        dan_balance = 0.0
        kruz_balance = 0
        if user_row:
            try:
                dan_balance = float(user_row.get("dan", 0))
            except Exception:
                dan_balance = 0.0
            try:
                kruz_balance = int(user_row.get("kruz", 0))
            except Exception:
                kruz_balance = 0
        
        dan_balance = 0.00 if abs(dan_balance) < 0.005 else round(dan_balance, 2)
        text = f"🛍️ <b>Магазин</b>\n\n💰 Ваш баланс:\n🪙 Дань: {format_number_beautiful(dan_balance)}\n⭐ Stars: {format_number_beautiful(kruz_balance)}\n\nВсего товаров: {total}\nСтраница {page} из {max_page}"
        
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=FSInputFile(shop_image_path), caption=text, parse_mode="HTML"),
                reply_markup=keyboard
            )
        except Exception as e:
            # Fallback - отправляем новое сообщение
            try:
                chat_id = callback.message.chat.id
                await callback.message.delete()
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(shop_image_path),
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        try:
            await callback.answer()
        except Exception:
            pass
            
    except Exception as e:
        # Логируем трейсбек в файл для диагностики
        # (exception logging removed)
        try:
            await callback.answer("Не удалось открыть магазин", show_alert=True)
        except Exception:
            pass
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main_menu")]
        ])
        try:
            await safe_edit_text_or_caption(callback.message, caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            try:
                await callback.answer("Не удалось открыть магазин", show_alert=True)
            except Exception:
                pass
    except ValueError:
        await callback.answer("Ошибка в данных категории", show_alert=True)
        return
    # This handler deals with shop pages (grid). Category-specific handling
    # is implemented in a different handler; ensure we don't fallthrough
    # to code that expects `category_id` to be defined.
    return

    items, total, max_page = get_category_items(category_id, page)
    
    if not items or all(item[0] == "empty" for item in items):
        await callback.answer("В этой категории пока нет товаров", show_alert=True)
        return
    
    # Создаем текст с информацией о категории
    from inv_py.shop import SHOP_CATEGORIES
    category_name = SHOP_CATEGORIES.get(category_id, {}).get("name", "Неизвестная категория")
    text = f"🛍️ {category_name}\n\nВсего товаров: {total}\nСтраница {page}/{max_page}"

    kb = build_shop_category_menu(category_id, page, max_page)

    # Попытаемся отрендерить изображение категории
    try:
        img_path = render_category_image(category_id, page, font_path="C:/Windows/Fonts/arial.ttf")
    except Exception as e:
        print(f"Ошибка рендера изображения категории: {e}")
        img_path = None

    try:
        if img_path and os.path.exists(img_path):
            # Попытка безопасно заменить media (если текущее сообщение — фото)
            try:
                media = types.InputMediaPhoto(media=FSInputFile(img_path), caption=text)
                await callback.message.edit_media(media=media, reply_markup=kb)
                try:
                    os.remove(img_path)
                except Exception:
                    pass
            except Exception:
                # Если не получилось отредактировать — отправляем новое фото и удаляем старое сообщение кнопками
                try:
                    await callback.message.answer_photo(FSInputFile(img_path), caption=text, reply_markup=kb)
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass
                except Exception:
                    await callback.answer("Не удалось загрузить категорию", show_alert=True)
        else:
            # Без изображения — используем безопасный текстовый редактор
            try:
                success = await safe_edit_text_or_caption(callback.message, text, reply_markup=kb)
                if not success:
                    await callback.message.edit_text(text, reply_markup=kb)
            except Exception:
                await callback.answer("Не удалось загрузить категорию", show_alert=True)
    except Exception:
        await callback.answer("Не удалось загрузить категорию", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("shop_item:"))
async def shop_item_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    """Показ конкретного товара по слоту"""
    try:
        _, slot_num, page = callback.data.split(":")
        slot_num = int(slot_num)
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка в данных товара", show_alert=True)
        return
    
    # Получаем предмет по слоту
    result = get_item_by_slot(slot_num, page)
    
    # Обрабатываем результат (может быть 2 или 3 элемента)
    if len(result) == 3:
        item_id, quantity, stock = result
    else:
        item_id, quantity = result[:2]
        stock = -1  # По умолчанию неограничен
    
    if item_id == "empty":
        await callback.answer("Этот слот пуст", show_alert=True)
        return

    # Получаем информацию о предмете
    from inv_py.config_inventory import ITEMS_CONFIG
    item_config = ITEMS_CONFIG.get(item_id, {})
    
    if not item_config:
        await callback.answer("Информация о товаре не найдена", show_alert=True)
        return

    # Получаем информацию из shop_config - используем полученный stock
    shop_info = SHOP_ITEMS.get(item_id, {})
    actual_stock = stock if stock != -1 else shop_info.get('stock', -1)  # Приоритет stock из get_item_by_slot
    price = shop_info.get('price', item_config.get('price', 0))
    currency = shop_info.get('currency', item_config.get('currency', 'dan'))
    
    # Создаем карточку товара
    name = item_config.get('name', f'Товар {item_id}')
    
    text = f"🛍️ <b>{name}</b>\n\n"
    
    # Цена и валюта
    currency_symbol = "🪙" if currency == "dan" else "⭐"
    text += f"💰 Цена: {price} {currency_symbol}\n"
    
    # Наличие товара
    if actual_stock == -1:
        text += f"📦 В наличии: ∞ (неограниченно)\n\n"
        is_available = True
    elif actual_stock > 0:
        text += f"📦 В наличии: {actual_stock} шт.\n\n"
        is_available = True
    else:
        text += f"❌ Товар закончился\n\n"
        is_available = False
    
    # Добавляем описание для разных типов товаров
    if 'reward_min' in item_config and 'reward_max' in item_config:
        text += f"💰 Содержимое: {item_config['reward_min']}-{item_config['reward_max']} Дань\n"
    
    if item_config.get('duration_days_min') and item_config.get('duration_days_max'):
        text += f"⏳ Длительность: {item_config['duration_days_min']}-{item_config['duration_days_max']} дней\n"
    
    # Проверяем систему покупки за звезды
    stars_cost = item_config.get('stars_cost')
    gold_setting = item_config.get('gold', 0)  # Если gold не указан, считаем как 0
    
    # Кнопки для покупки (показываем только если товар есть в наличии)
    kb = []
    if is_available:
        # Основная кнопка покупки за обычную валюту
        kb.append([InlineKeyboardButton(text=f"💰 Купить за {price} {currency_symbol}", callback_data=f"buy_item:{item_id}:{page}")])
        
        # Дополнительная кнопка покупки за звезды (если настройки позволяют)
        if stars_cost and gold_setting != -1:
            text += f"⭐ Также доступно за звезды: {stars_cost} звезд\n"
            kb.append([InlineKeyboardButton(text=f"⭐ Купить за {stars_cost} звезд", callback_data=f"buy_stars:{item_id}:{page}")])
    
    # Кнопка "Назад" всегда присутствует
    kb.append([InlineKeyboardButton(text="🔙 Назад к магазину", callback_data=f"shop_page:{page}")])
    
    # (hidden item marker removed)

    # Показываем изображение товара если есть
    displayed_message = getattr(callback, 'message', None)
    try:
        photo_path = item_config.get('photo_full') or item_config.get('photo_square')
        if photo_path and os.path.exists(photo_path):
            from aiogram.types import InputMediaPhoto
            photo = FSInputFile(photo_path)
            media = InputMediaPhoto(media=photo, caption=text, parse_mode="HTML")
            # Попробуем отредактировать текущее сообщение (обычный путь)
            try:
                await callback.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            except Exception:
                # Если не удалось отредактировать — отправляем новое сообщение и используем его
                try:
                    sent = await callback.message.answer_photo(FSInputFile(photo_path), caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
                    displayed_message = sent
                except Exception:
                    # Оставляем displayed_message как есть и продолжим
                    pass
        else:
            # Пытаемся отредактировать текст в текущем сообщении
            try:
                await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
            except Exception:
                # Если не получилось — отправим новое сообщение с текстом и используем его
                try:
                    sent = await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
                    displayed_message = sent
                except Exception:
                    pass
    except Exception as e:
        # Логируем ошибку отображения товара (ошибка важна)
        print(f"Ошибка при показе товара: {e}")
        # Fallback к тексту — пытаемся безопасно отредактировать, иначе отправить новое сообщение
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        except Exception:
            try:
                sent = await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
                displayed_message = sent
            except Exception:
                pass
    
    try:
        await callback.answer()
    except Exception:
        pass

    # (no mapping persisted for displayed messages)

@dp.callback_query(lambda c: c.data.startswith("buy_item:"))
async def buy_item_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    """Покупка товара"""
    try:
        _, item_id, page = callback.data.split(":")
        quantity = 1  # Покупаем по 1 штуке
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка в данных покупки", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем возможность покупки
    can_buy, reason = can_afford_item(user_id, item_id, quantity)
    if not can_buy:
        await callback.answer(f"❌ {reason}", show_alert=True)
        return
    
    # Совершаем покупку
    success, message = purchase_item(user_id, item_id, quantity)
    
    if success:
        # Получаем обновленный баланс
        user_row = db.get_user(user_id)
        dan_balance = 0.0
        kruz_balance = 0
        if user_row:
            try:
                dan_balance = float(user_row.get("dan", 0))
            except Exception:
                dan_balance = 0.0
            try:
                kruz_balance = int(user_row.get("kruz", 0))
            except Exception:
                kruz_balance = 0
        
        dan_balance = 0.00 if abs(dan_balance) < 0.005 else round(dan_balance, 2)
        
        # Добавляем информацию о балансе к сообщению о покупке
        balance_info = f"\n\n💰 Ваш баланс:\n🪙 Дань: {format_number_beautiful(dan_balance)}\n⭐ Stars: {format_number_beautiful(kruz_balance)}"
        full_message = message + balance_info
        
        await callback.answer(full_message, show_alert=True)
        # Регистрируем прогресс задачи "Торговец" (покупки в магазине)
        try:
            import tasks as _tasks
            _tasks.record_shop_purchase(user_id)
        except Exception:
            pass
        
        # Возвращаемся к главному меню магазина с обновленным балансом
        new_callback = types.CallbackQuery(
            id=callback.id,
            from_user=callback.from_user,
            message=callback.message,
            data="menu_shop",
            chat_instance=callback.chat_instance
        )
        await menu_shop_callback(new_callback)
    else:
        await callback.answer(f"❌ {message}", show_alert=True)

# Обработчик покупки за звезды
@dp.callback_query(lambda c: c.data.startswith("buy_stars:"))
async def buy_stars_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    """Покупка товара за звезды Telegram"""
    try:
        _, item_id, page = callback.data.split(":")
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка в данных покупки", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Получаем информацию о предмете
    from inv_py.config_inventory import ITEMS_CONFIG
    item_config = ITEMS_CONFIG.get(item_id, {})
    
    if not item_config:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    # Проверяем настройки звезд
    stars_cost = item_config.get('stars_cost')
    gold_setting = item_config.get('gold', 0)
    
    if not stars_cost or gold_setting == -1:
        await callback.answer("Покупка за звезды недоступна для этого товара", show_alert=True)
        return
    
    # Проверяем наличие товара
    shop_info = SHOP_ITEMS.get(item_id, {})
    stock = shop_info.get('stock', 999)
    
    if stock == 0:  # Только если точно закончился (stock = 0)
        await callback.answer("❌ Товар закончился", show_alert=True)
        return
    
    # Создаем счет для оплаты звездами
    from aiogram.types import LabeledPrice
    
    item_name = item_config.get('name', f'Товар {item_id}')
    
    # Создаем инвойс для Telegram Stars
    prices = [LabeledPrice(label=item_name, amount=stars_cost)]  # amount в звездах
    
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Покупка: {item_name}",
            description=f"Покупка {item_name} за {stars_cost} ⭐ Telegram Stars",
            payload=f"shop_stars:{item_id}:1",  # item_id:quantity
            provider_token="",  # Для Telegram Stars не нужен
            currency="XTR",  # Telegram Stars currency
            prices=prices,
            start_parameter=f"buy_{item_id}"
        )
        await callback.answer("💫 Счет на оплату отправлен!")
    except Exception as e:
        print(f"Ошибка создания инвойса: {e}")
        await callback.answer("❌ Не удалось создать счет для оплаты", show_alert=True)

# Обработчик предварительного запроса на оплату
@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: types.PreCheckoutQuery):
    """Проверяем возможность оплаты перед ее проведением"""
    try:
        payload = pre_checkout_query.invoice_payload
        
        # Проверяем оплату рекламы
        if payload.startswith("ad_payment:"):
            from ads import get_ad_by_num
            _, ad_num = payload.split(":")
            ad = get_ad_by_num(int(ad_num))
            
            if not ad:
                await pre_checkout_query.answer(ok=False, error_message="❌ Реклама не найдена")
                return
            
            if ad['status'] == 'active':
                await pre_checkout_query.answer(ok=False, error_message="✅ Реклама уже оплачена")
                return
            
            await pre_checkout_query.answer(ok=True)
            return
        
        # Проверяем пополнение Дани за звезды
        if payload.startswith("buy_dan_stars:"):
            await pre_checkout_query.answer(ok=True)
            return
        
        # Проверяем оплату товаров из магазина
        if not payload.startswith("shop_stars:"):
            await pre_checkout_query.answer(ok=False, error_message="Неверный тип платежа")
            return
        
        # Парсим payload: shop_stars:item_id:quantity
        _, item_id, quantity_str = payload.split(":")
        quantity = int(quantity_str)
        
        # Проверяем наличие товара
        shop_info = SHOP_ITEMS.get(item_id, {})
        stock = shop_info.get('stock', 999)
        
        if stock == 0:  # Только если точно закончился
            await pre_checkout_query.answer(ok=False, error_message="❌ Недостаточно товара в наличии")
            return
        
        # Проверяем конфигурацию товара
        from inv_py.config_inventory import ITEMS_CONFIG
        item_config = ITEMS_CONFIG.get(item_id, {})
        
        if not item_config or item_config.get('gold', 0) == -1:
            await pre_checkout_query.answer(ok=False, error_message="❌ Товар недоступен для покупки за звезды")
            return
        
        # Все проверки пройдены
        await pre_checkout_query.answer(ok=True)
        
    except Exception as e:
        print(f"Ошибка при проверке платежа: {e}")
        await pre_checkout_query.answer(ok=False, error_message="❌ Ошибка при обработке платежа")

# Обработчик успешного платежа
@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment_handler(message: types.Message):
    """Обрабатываем успешный платеж за звезды"""
    try:
        payment = message.successful_payment
        payload = payment.invoice_payload
        
        # Обработка оплаты рекламы
        if payload.startswith("ad_payment:"):
            from ads import get_ad_by_num, update_ad_status
            _, ad_num = payload.split(":")
            num = int(ad_num)
            ad = get_ad_by_num(num)
            
            if not ad:
                await message.answer("❌ Реклама не найдена. Обратитесь к администратору.")
                return
            
            # Активируем рекламу
            update_ad_status(num, 'active')
            
            type_emoji = "👁" if ad['type'] == "views" else "🫵"
            
            success_message = (
                f"✅ Оплата рекламы успешна!\n\n"
                f"**Реклама:** #{num}\n"
                f"**Канал:** @{ad['username']}\n"
                f"**Тип:** {type_emoji}\n"
                f"**Лимит:** {ad['limit_count']}\n"
                f"⭐ Оплачено: {payment.total_amount} звезд\n\n"
                f"🎉 Реклама активирована и начнет показываться пользователям!"
            )
            
            await message.answer(success_message, parse_mode="Markdown")
            
            # Уведомляем админа
            from ads import ADMIN_ID
            admin_notification = (
                f"💰 **Новая оплата рекламы!**\n\n"
                f"**Номер:** #{num}\n"
                f"**Канал:** @{ad['username']}\n"
                f"**Плательщик:** {message.from_user.first_name} (@{message.from_user.username or 'без username'})\n"
                f"**Сумма:** {payment.total_amount} ⭐\n"
                f"**Статус:** Активирована ✅"
            )
            
            try:
                await bot.send_message(ADMIN_ID, admin_notification, parse_mode="Markdown")
            except Exception:
                pass
            
            print(f"✅ Успешная оплата рекламы: пользователь {message.from_user.id} оплатил рекламу #{num}")
            return
        
        # Обработка пополнения Дани за звезды
        if payload.startswith("buy_dan_stars:"):
            _, stars_str, dan_str = payload.split(":")
            stars = int(stars_str)
            dan = int(dan_str)
            user_id = message.from_user.id
            
            # Начисляем дань
            db.add_dan(user_id, dan)
            
            success_message = (
                f"✅ Пополнение успешно!\n\n"
                f"💰 Начислено: {dan:,} Дань 🪙\n"
                f"⭐ Оплачено: {stars} Telegram Stars\n\n"
                f"Спасибо за поддержку!"
            )
            
            await message.answer(success_message)
            print(f"✅ Успешное пополнение: пользователь {user_id} купил {dan} дани за {stars} звезд")
            return
        
        # Обработка оплаты товаров из магазина
        if not payload.startswith("shop_stars:"):
            print(f"Неизвестный тип платежа: {payload}")
            return
        
        # Парсим payload: shop_stars:item_id:quantity
        _, item_id, quantity_str = payload.split(":")
        quantity = int(quantity_str)
        user_id = message.from_user.id
        
        # Проверяем еще раз наличие товара (на случай если товар закончился после создания инвойса)
        shop_info = SHOP_ITEMS.get(item_id, {})
        stock = shop_info.get('stock', 999)
        
        if stock == 0:  # Только если точно закончился
            # Возвращаем деньги автоматически (если это возможно)
            await message.answer("❌ К сожалению, товар закончился. Обратитесь к администрации для возврата средств.")
            return
        
    # Выдаем товар
        db.add_item(user_id, item_id, quantity)
        
        # Обновляем stock если он не бесконечный
        if shop_info.get('stock', -1) != -1:
            shop_info['stock'] = max(0, shop_info['stock'] - quantity)
        
        # Получаем информацию о товаре
        from inv_py.config_inventory import ITEMS_CONFIG
        item_config = ITEMS_CONFIG.get(item_id, {})
        item_name = item_config.get('name', f'Товар {item_id}')
        
        # Применяем эффекты товара если есть
        use_command = item_config.get('use_command')
        if use_command == 'activate_infinite_storage':
            import random
            days = random.randint(7, 14)
            hours = days * 24
            db.add_user_effect(user_id, "infinite_storage", f"duration_days:{days}", hours)
        
        success_message = (
            f"✅ Покупка за звезды успешна!\n\n"
            f"🛍️ Товар: {item_name}\n"
            f"📦 Количество: {quantity}\n"
            f"⭐ Оплачено: {payment.total_amount} звезд\n\n"
            f"Товар добавлен в ваш инвентарь!"
        )
        
        await message.answer(success_message)
        # Регистрируем прогресс задачи "Торговец" (покупки в магазине за звезды)
        try:
            import tasks as _tasks
            _tasks.record_shop_purchase(user_id)
        except Exception:
            pass
        
        print(f"✅ Успешная покупка за звезды: пользователь {user_id} купил {quantity}x {item_id}")
        
    except Exception as e:
        print(f"Ошибка при обработке успешного платежа: {e}")
        await message.answer("❌ Произошла ошибка при обработке покупки. Обратитесь к администратору.")


 

async def saper_message_handler_with_last_stake(message):
    """Wrapper для обработчика сапёра с сохранением последней ставки"""
    # Ленивая загрузка игровых модулей
    if not import_game_modules():
        await message.answer("❌ Игровые модули недоступны")
        return
        
    # Импортируем после загрузки
    from plugins.games.saper import saper_message_handler, start_saper_game, active_saper_games
    
    increment_games_count()
    # Call original handler and store last stake
    import re
    text = message.text.strip().lower() if message.text else ""
    if "сапер" in text:
        parts = text.split()
        if len(parts) >= 2:
            try:
                stake = int(parts[1])
                last_saper_stake[message.from_user.id] = stake
            except Exception:
                pass
    # Call the original handler
    from plugins.games.saper import saper_message_handler
    await saper_message_handler(message)

dp.message.register(saper_message_handler_with_last_stake, lambda m: m.text and m.text.lower().startswith("сапер"))

# Регистрируем callback обработчик сапера рано для надежности
try:
    from plugins.games.saper import saper_callback_handler
    dp.callback_query.register(saper_callback_handler, F.data.startswith("saper_"))
    print("✅ Saper callback handler зарегистрирован")
except Exception as e:
    print(f"❌ Ошибка регистрации saper callback: {e}")



# --- Новый обработчик для кнопки "Повторить" в сапёре ---
from plugins.games.saper import start_saper_game, active_saper_games
@dp.callback_query(lambda c: c.data == "saper_repeat")
async def saper_repeat_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    # Ранний ответ на callback для предотвращения timeout
    await callback.answer()
    
    increment_games_count()
    # Извлекаем game_id и ставку из callback.data (формат: "saper_repeat:game_id:stake")
    try:
        parts = callback.data.split(":") if callback.data else []
        if len(parts) >= 3:
            game_id = parts[1]
            stake = int(parts[2])
        elif len(parts) == 2:
            # Старый формат - пытаемся найти игру
            game_id = parts[1]
            game = active_saper_games.get(game_id)
            if game:
                stake = game.stake if game.stake >= 10 else 10
                # Проверяем владельца игры
                if callback.from_user.id != game.owner_id:
                    await callback.answer("Только владелец игры может повторить", show_alert=True)
                    return
                # Удаляем старую игру
                del active_saper_games[game_id]
            else:
                await callback.answer("Игра не найдена", show_alert=True)
                return
        else:
            await callback.answer("Ошибка в данных игры", show_alert=True)
            return
    except (IndexError, ValueError):
        await callback.answer("Ошибка в данных игры", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем минимальную ставку
    if stake < 10:
        stake = 10
    
    # Создаем новую игру с той же ставкой
    from plugins.games.saper import generate_unique_game_id, SimpleSaper
    import database as db
    
    user = db.get_user(user_id)
    if not user or user["dan"] < stake:
        await callback.answer(f"Недостаточно Дань! Ваш баланс: {user['dan'] if user else 0}", show_alert=True)
        return
    
    # Создаем новую игру с уникальным ID и той же ставкой
    new_game_id = generate_unique_game_id(user_id)
    db.withdraw_dan(user_id, stake)
    active_saper_games[new_game_id] = SimpleSaper(stake=stake, owner_id=user_id, game_id=new_game_id)
    # Засчитываем как игру дня (любая игра)
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass
    
    # Обновляем сообщение с новой игрой
    from main import safe_edit_text
    await safe_edit_text(
        callback.message,
        active_saper_games[new_game_id].status_text(),
        reply_markup=active_saper_games[new_game_id].keyboard()
    )
    await callback.answer(f"Новая игра запущена! Ставка: {stake} ДАНЬ")

# --- Текстовые команды для батла: "принять" и "отменить" ---
@dp.message(lambda m: m.text and m.text.strip().lower() == "принять")
async def battle_accept_message(message: types.Message):
    if not getattr(message, 'from_user', None) or not getattr(message, 'chat', None):
        return
    await battles.handle_accept_message(message)

@dp.message(lambda m: m.text and m.text.strip().lower() == "отменить")
async def battle_decline_message(message: types.Message):
    if not getattr(message, 'from_user', None) or not getattr(message, 'chat', None):
        return
    await battles.handle_decline_message(message)


# --- Холдер для callback repeat_clad (клад) ---
@dp.callback_query(lambda c: c.data and c.data.startswith("repeat_clad:"))
async def repeat_clad_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    # Гарантируем, что игровые модули загружены (для start_clad_game, get_keyboard)
    try:
        _ = start_clad_game  # type: ignore[name-defined]
    except Exception:
        import_game_modules()
    
    increment_games_count()
    user_id = callback.from_user.id
    
    # Получаем ставку из callback data
    try:
        bet = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        bet = last_clad_bet.get(user_id, 100)  # Используем последнюю ставку или 100 по умолчанию
    
    # Проверяем баланс пользователя
    import database as db
    user = db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    
    balance = user["dan"]
    if balance < bet:
        await callback.answer(f"Недостаточно средств! У вас {balance} ДАНЬ, нужно {bet} ДАНЬ.", show_alert=True)
        return
    
    # Списываем ставку
    if not db.withdraw_dan(user_id, bet):
        await callback.answer("Ошибка списания ставки.", show_alert=True)
        return
    
    # Обновляем баланс
    user = db.get_user(user_id)
    if user:
        try:
            bal = float(user["dan"])
            bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
            db.set_dan(user_id, bal)
        except Exception:
            pass
    
    # Сохраняем последнюю ставку
    last_clad_bet[user_id] = bet
    # Регистрируем прогресс заданий по игре Клад
    try:
        print(f"[DEBUG] record_clad_play called: user_id={user_id}, bet={bet}, source='Клад' (should NOT be called for 'бет')")
        tasks.record_clad_play(user_id, bet)
    except Exception as e:
        print(f"[ERROR] record_clad_play failed: {e}")
    
    # Стараемся ответить callback как можно раньше, чтобы избежать timeout
    try:
        await callback.answer()
    except Exception:
        pass

    try:
        game = start_clad_game(user_id, bet)
        username = format_clickable_name(callback.from_user) if callback.from_user else "Игрок"
        kb = get_keyboard(game)
        new_msg = f"💎 Клад! Игрок: {username}\nСтавка: {bet}\nВыберите клетку:"
        try:
            await callback.message.edit_text(new_msg, reply_markup=kb, parse_mode="HTML")  # type: ignore
        except Exception:
            # если не удалось отредактировать — просто отправим новое
            try:
                await callback.message.answer(new_msg, reply_markup=kb, parse_mode="HTML")  # type: ignore
            except Exception:
                pass
    except Exception:
        # Возврат ставки и финальное уведомление (если можно)
        db.add_dan(user_id, bet)
        try:
            await callback.answer("Ошибка запуска игры Клад.", show_alert=False)
        except Exception:
            pass

# Команда 'клад X' — запуск игры
import re
import database as db
@dp.message(lambda m: m.text and re.search(r"клад", m.text, re.IGNORECASE) and re.search(r"\d+", m.text))
async def cmd_clad_start(message: types.Message):
    increment_games_count()
    # Save last clad bet
    user_id = message.from_user.id
    user_id = message.from_user.id
    text = message.text.strip().lower()
    # Проверяем, что команда начинается с "клад" и далее число
    parts = text.split()
    if not parts or parts[0] != "клад" or len(parts) < 2:
        await message.reply("Формат: клад X (X — сумма)")
        return
    try:
        bet = int(parts[1])
        last_clad_bet[user_id] = bet
    except Exception:
        await message.reply("Ставка должна быть числом.")
        return
    if bet < 10:
        await message.reply("Минимальная ставка — 10 Дань.")
        return
    try:
        user = db.get_user(user_id)
    except Exception:
        await message.reply("Ошибка получения баланса.")
        return
    if not user or user["dan"] < bet:
        await message.reply(f"Недостаточно Дань! Ваш баланс: {user['dan'] if user else 0}")
        return
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await message.reply("Ошибка списания ставки.")
        return
    # Обновляем баланс
    user = db.get_user(user_id)
    if user:
        try:
            bal = float(user["dan"])
            bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
            db.set_dan(user_id, bal)
        except Exception:
            pass
    try:
        # Регистрируем прогресс заданий по игре Клад
        try:
            print(f"[DEBUG] record_clad_play called: user_id={user_id}, bet={bet}, source='Клад' (should NOT be called for 'бет')")
            tasks.record_clad_play(user_id, bet)
        except Exception as e:
            print(f"[ERROR] record_clad_play failed: {e}")
        game = start_clad_game(user_id, bet)
        username = format_clickable_name(message.from_user) if message.from_user else "Игрок"
        kb = get_keyboard(game)
        await message.reply(f"💎 Клад! Игрок: {username}\nСтавка: {bet}\nВыберите клетку:", reply_markup=kb, parse_mode="HTML")
    except Exception:
        await message.reply("Ошибка запуска игры Клад.")

# --- Регистрация обработчика повторить бет (будет зарегистрирован после загрузки battles) ---


# Callback для шагов и забора выигрыша
@dp.callback_query(lambda c: c.data and c.data.startswith("clad:"))
async def callback_clad_step(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    user_id = callback.from_user.id
    data = callback.data.split(":")
    if len(data) < 3:
        await callback.answer("Неверный формат данных!", show_alert=True)
        return
    
    game_id = data[1]
    action = data[2]
    
    # Проверяем, что игра существует
    game = active_clads.get(game_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    # Проверяем, что игрок — владелец игры
    if game['user_id'] != user_id:
        await callback.answer("Это не ваша игра! Только владелец может играть.", show_alert=True)
        return
    
    if action == "take":
        result = await take_clad_game(game_id)
        # Выдать выигрыш пользователю
        # Получаем сумму из текста результата
        import re
        match = re.search(r"Вы забрали ([\d.]+) Дань", result['msg'])
        if match:
            win_amount = float(match.group(1))
            db.add_dan(user_id, win_amount)
        # Формируем красивое сообщение с именем игрока
        if game:
            # Импортируем MULTS из clad модуля
            try:
                from plugins.games.clad import MULTS
            except ImportError:
                MULTS = [1.25, 1.65, 2.00, 3.60, 6.50, 25.0]  # fallback
            
            username = format_clickable_name(callback.from_user)
            last_level = max(0, game['level'] - 1)
            mult = MULTS[last_level] if last_level < len(MULTS) else MULTS[-1]
            bet = game['bet']
            win = bet * (float(mult) if isinstance(mult, (float, int)) else float(str(mult).replace('х','')))
            # Получаем баланс пользователя (если есть функция)
            try:
                from database import get_user
                bal = get_user(user_id)["dan"]
            except Exception:
                bal = "?"
            
            # Добавляем кнопку "Повторить игру" после забора выигрыша
            repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Повторить игру", callback_data=f"repeat_clad:{bet}")]
            ])
            
            safe_edit_text(callback.message,
                f"💎 Клад забран!\nИгрок: {username}\nСтавка была: {bet}\n"
                f"Достигнутый множитель: {mult}\n"
                f"Ваш баланс: {bal} (+{win:.2f} ДАНЬ)",
                reply_markup=repeat_kb,
                parse_mode="HTML"
            )
        else:
            safe_edit_reply_markup(callback.message, reply_markup=None)
        await callback.answer()
        return
    
    # Если не "take", то это индекс ячейки
    try:
        cell_idx = int(action)
    except ValueError:
        await callback.answer("Неверный формат действия!", show_alert=True)
        return
    
    result = await step_clad_game(game_id, cell_idx)
    if result['status'] == 'lose':
        # Ответить callback (игра закончена) — если уже просрочен, игнорируем
        try:
            await callback.answer(result['msg'], show_alert=True)
        except Exception:
            pass
        game = active_clads.get(game_id)
        if game:
            # Импорт нужных сущностей из clad
            try:
                from plugins.games.clad import MULTS, MINES_PER_ROW, generate_row
            except Exception:
                # Fallback значения если импорт не удался
                MULTS = [1.25, 1.65, 2.00, 3.60, 6.50, 25.0]
                MINES_PER_ROW = [1, 2, 3, 4, 4, 4]
            # Используем функцию format_clickable_name для кликабельного отображения имени
            username = format_clickable_name(callback.from_user)
            lost = game['bet']
            max_row = max(0, game['level'] - 1)
            # Собираем/догенерируем ряды для отображения
            display_rows = []
            total_levels = len(game.get('rows', []))
            for i in range(total_levels):
                row = game['rows'][i]
                if row is None:
                    # Генерируем для показа (не влияет на исход уже проигранной игры)
                    try:
                        from plugins.games.clad import generate_row, MINES_PER_ROW
                        row = generate_row(MINES_PER_ROW[i])
                        game['rows'][i] = row
                    except Exception:
                        row = [0,0,0,0,0]
                bombs_line = ''.join('💣' if c==1 else '💵' for c in row)
                mult = MULTS[i] if i < len(MULTS) else MULTS[-1]
                mult_text = f"x{mult}" if not isinstance(mult, str) else mult
                display_rows.append(f"{mult_text} {bombs_line}")
            field_text = '\n'.join(display_rows)
            
            # Добавляем кнопку "Повторить игру" после проигрыша
            repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Повторить игру", callback_data=f"repeat_clad:{lost}")]
            ])
            
            try:
                safe_edit_text(callback.message,
                    f"💥 Проигрыш! Ставка: {lost}\nИгрок: {username}\nДостигнут уровень: {max_row}\n\nПоле:\n{field_text}",
                    reply_markup=repeat_kb,
                    parse_mode="HTML")
            except Exception:
                try:
                    await callback.message.answer(
                        f"💥 Проигрыш! Ставка: {lost}\nИгрок: {username}\nДостигнут уровень: {max_row}",
                        reply_markup=repeat_kb,
                        parse_mode="HTML")
                except Exception:
                    pass
        else:
            safe_edit_reply_markup(callback.message, reply_markup=None)
        return
    elif result['status'] == 'win':
        await callback.answer(result['msg'], show_alert=True)
        # Добавляем кнопку "Повторить игру" после выигрыша с именем игрока
        game = active_clads.get(game_id)
        if game:
            username = format_clickable_name(callback.from_user)
            win_amount = game['bet'] * 25.0  # Финальный множитель
            last_bet = game['bet']
            
            repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Повторить игру", callback_data=f"repeat_clad:{last_bet}")]
            ])
            
            # Показываем красивое сообщение о победе с именем игрока
            try:
                safe_edit_text(callback.message,
                    f"🎉 Победа! Поздравляем!\nИгрок: {username}\nСтавка: {last_bet}\nВыигрыш: {win_amount:.0f} ДАНЬ\n\nВы прошли все уровни клада!",
                    reply_markup=repeat_kb,
                    parse_mode="HTML")
            except Exception:
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=repeat_kb)
        else:
            repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Повторить игру", callback_data=f"repeat_clad:100")]
            ])
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=repeat_kb)
    elif result['status'] == 'next':
        game = active_clads.get(game_id)
        if not game:
            await callback.answer("Игра не найдена!", show_alert=True)
            return
        kb = get_keyboard(game)
        # Import MULTS from clad module
        try:
            from plugins.games.clad import MULTS
        except ImportError:
            MULTS = [1.35, 1.75, 2.40, 3.60, 6.50, 25.0]  # fallback
        current_mult = MULTS[game['level']] if game['level'] < len(MULTS) else MULTS[-1]
        if isinstance(current_mult, (float, int)):
            mult_text = f"{current_mult}х"
        else:
            mult_text = str(current_mult)
        username = format_clickable_name(callback.from_user) if callback.from_user else "Игрок"
        status_text = f"💎 Клад! Игрок: {username}\nСтавка: {game['bet']} ДАНЬ\nУровень {game['level'] + 1}, множитель {mult_text}\n\nВыберите клетку:"
        safe_edit_text(callback.message, status_text, reply_markup=kb, parse_mode="HTML")
        await callback.answer(result['msg'])
import datetime
# --- Хранилище id сообщений для удаления ---
farm_message_ids = {}
import asyncio

# --- Функция автоудаления сообщений через 10 минут ---
async def schedule_delete_message(chat_id, message_id, text=None):
    # Сохраняем id сообщения для команды /del
    if chat_id not in farm_message_ids:
        farm_message_ids[chat_id] = []
    farm_message_ids[chat_id].append((message_id, text))
    # Не удаляем реферальные сообщения
    if text and ("реферал" in text.lower() or "реферальная" in text.lower()):
        return
    await asyncio.sleep(600)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# --- Обработка кнопки 'Улуч. Ферму' ---

@dp.callback_query(lambda c: c.data == "upgrade_ferma")
async def callback_upgrade_ferma(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    user_id = callback.from_user.id
    from ferma import upgrade_farm, get_farm, get_farm_leaderboard_position
    result = upgrade_farm(user_id)
    await callback.answer(result['msg'], show_alert=True)
    # Обновить сообщение с фермой, если апгрейд успешен
    if result['status'] == 'ok':
        farm = get_farm(user_id)
        place = get_farm_leaderboard_position(user_id)
        bal = float(db.get_user(user_id)["dan"])
        bal = format_number_beautiful(bal)
        # Гарантируем, что stored_dan определён
        stored_dan = farm['stored_dan'] if 'stored_dan' in farm else 0
        stored_dan = float(stored_dan)
        stored_dan = 0.00 if abs(stored_dan) < 0.005 else round(stored_dan, 2)
        stored_dan = f"{stored_dan:.2f}"

        # Вычисляем доход от животных
        from ferma import calculate_animals_income
        animals_income, _ = calculate_animals_income(user_id)
        total_income = farm['income_per_hour'] + animals_income
        income_text = f"💰 Доход в час: {total_income:.2f}"

        # Получаем стоимость следующего улучшения
        from ferma import get_next_upgrade_cost
        next_cost = get_next_upgrade_cost(user_id)

        if next_cost is not None:
            # Форматируем стоимость красиво
            cost_formatted = format_number_beautiful(next_cost)
            upgrade_text = f"📈 Улучшить ({cost_formatted})"
        else:
            upgrade_text = "📈 Макс. уровень"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=upgrade_text, callback_data="upgrade_ferma"),
                InlineKeyboardButton(text="🐄 Животные", callback_data="farm_animals")
            ],
            [InlineKeyboardButton(text="📥 Собрать дань", callback_data="collect_ferma")],
            [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
        ])
        hour = datetime.datetime.now().hour
        if 6 <= hour < 18:
            greeting = "Доброе утро, фермер!"
            photo_path = "C:/BotKruz/ChatBotKruz/photo/fermaday.png"
        else:
            greeting = "Доброй ночи, фермер!"
            photo_path = "C:/BotKruz/ChatBotKruz/photo/fermanight.png"

        # Проверяем активен ли бесконечный склад
        infinite_storage = db.get_user_effect(user_id, "infinite_storage")
        if infinite_storage:
            import time
            remaining_time = infinite_storage['expires_at'] - int(time.time())
            if remaining_time > 0:
                days = remaining_time // 86400
                hours = (remaining_time % 86400) // 3600
                minutes = (remaining_time % 3600) // 60
                storage_info = f"📮 Бесконечный склад активен: {days}д {hours}ч {minutes}м"
            else:
                storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"
        else:
            storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"

        reply = (
            f"👨‍🌾 🌾 {greeting}\n\n"
            f"🏡 Уровень фермы: {farm['level']}\n"
            f"{income_text}\n"
            f"{storage_info}\n"
            f"📊 Место в топе по доходу: {place}\n\n"
            f"🌱 Дань на складе фермы: {stored_dan}\n"
            f"🪙 Дань на балансе: {bal}"
        )

        # Редактируем существующее сообщение вместо удаления и создания нового
        try:
            photo = FSInputFile(photo_path)
            media = InputMediaPhoto(media=photo, caption=reply)
            await callback.message.edit_media(media=media, reply_markup=kb)
        except Exception:
            # Fallback: редактируем только текст, если с медиа проблемы
            try:
                await callback.message.edit_text(reply, reply_markup=kb)
            except Exception:
                # Последний fallback: удаляем и создаем заново
                await callback.message.delete()
                await bot.send_message(callback.message.chat.id, reply, reply_markup=kb)
    else:
        # Если апгрейд не удался, просто возвращаем ответ и ничего не обновляем
        return

# --- Обработчик меню животных на ферме ---

@dp.callback_query(lambda c: c.data == "farm_animals")
async def callback_farm_animals(callback: types.CallbackQuery):
    """Показывает меню управления животными на ферме"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    from ferma import get_farm, get_available_animal_slots, get_user_farm_animals, is_animal_active, ANIMALS_CONFIG
    
    farm = get_farm(user_id)
    max_slots = get_available_animal_slots(farm['level'])
    
    if max_slots == 0:
        await callback.answer("❌ У вас нет слотов для животных! Улучшите ферму до уровня 3.", show_alert=True)
        return
    
    # Получаем размещённых животных
    placed_animals = get_user_farm_animals(user_id)
    
    # Получаем животных из хранилища owned + из инвентаря (легаси)
    from ferma import get_unassigned_animals_counts
    owned_counts = get_unassigned_animals_counts(user_id)
    inv_list = db.get_inventory(user_id)  # [(item_id, count), ...]
    inventory = {item_id: count for item_id, count in inv_list}
    chicken_count = owned_counts.get('08', 0) + inventory.get('08', 0)
    cow_count = owned_counts.get('09', 0) + inventory.get('09', 0)
    
    # Формируем текст с информацией о слотах
    reply = "🐄 **Животные на ферме**\n\n"
    reply += f"📦 Доступно слотов: {max_slots}\n"
    reply += f"✅ Занято: {len(placed_animals)}\n\n"
    
    # Показываем каждый слот
    for slot in range(1, max_slots + 1):
        if slot in placed_animals:
            animal = placed_animals[slot]
            animal_type = animal['type']
            config = ANIMALS_CONFIG.get(animal_type, {})
            animal_name = config.get('name', 'Неизвестное животное')
            income = config.get('income_per_hour', 0)
            
            # Проверяем активность
            import time
            hours_since_fed = (time.time() - animal['last_fed_time']) / 3600
            hours_left = 12 - hours_since_fed
            
            if is_animal_active(animal):
                status = f"🟢 Активно ({int(hours_left)} ч до кормления)"
                income_text = f"{income} дань/час"
            else:
                status = "💤 Голодает (покорми меня!)"
                income_text = "0 дань/час"
            
            reply += f"**Слот #{slot}:** {animal_name}\n"
            reply += f"  └ Доход: {income_text}\n"
            reply += f"  └ Статус: {status}\n\n"
        else:
            reply += f"**Слот #{slot}:** Пусто\n\n"
    
    # Создаем кнопки
    kb_buttons = []
    
    # Кнопки для размещения животных из инвентаря
    if chicken_count > 0 and len(placed_animals) < max_slots:
        kb_buttons.append([
            InlineKeyboardButton(text=f"🐔 Использовать Курицу ({chicken_count} шт)", callback_data="place_animal:08")
        ])
    
    if cow_count > 0 and len(placed_animals) < max_slots:
        kb_buttons.append([
            InlineKeyboardButton(text=f"🐄 Использовать Корову ({cow_count} шт)", callback_data="place_animal:09")
        ])
    
    # Кнопки для каждого занятого слота
    for slot in range(1, max_slots + 1):
        if slot in placed_animals:
            animal = placed_animals[slot]
            animal_type = animal['type']
            config = ANIMALS_CONFIG.get(animal_type, {})
            
            # Кнопка кормления
            if is_animal_active(animal):
                feed_text = f"🍖 Покормить #{slot}"
            else:
                feed_text = f"🍖 Покормить #{slot} 💤"
            
            kb_buttons.append([
                InlineKeyboardButton(text=feed_text, callback_data=f"feed_animal:{slot}"),
                InlineKeyboardButton(text=f"📤 Убрать #{slot}", callback_data=f"remove_animal:{slot}")
            ])
    
    kb_buttons.append([InlineKeyboardButton(text="⬅️ К ферме", callback_data="menu_ferma")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    
    # Редактируем существующее сообщение
    try:
        await callback.message.edit_text(reply, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        # Если это было сообщение с медиа, удаляем и создаём новое
        try:
            await callback.message.delete()
            await bot.send_message(callback.message.chat.id, reply, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass

# --- Обработчик размещения животного из инвентаря ---

@dp.callback_query(lambda c: c.data.startswith("place_animal:"))
async def callback_place_animal(callback: types.CallbackQuery):
    """Размещает животное из инвентаря/owned_animals на ферму"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return
    
    animal_item_id = parts[1]  # "08" или "09"
    
    from ferma import place_animal_on_farm
    
    # Функция place_animal_on_farm сама проверит наличие в owned_animals и инвентаре
    result = place_animal_on_farm(user_id, animal_item_id)
    
    if result['status'] == 'ok':
        await callback.answer(f"✅ {result['msg']}", show_alert=True)
        # Обновляем меню
        await callback_farm_animals(callback)
    else:
        await callback.answer(f"❌ {result['msg']}", show_alert=True)

# --- Обработчик кормления животного ---

@dp.callback_query(lambda c: c.data.startswith("feed_animal:"))
async def callback_feed_animal(callback: types.CallbackQuery):
    """Кормит животное в указанном слоте"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return
    
    slot_number = int(parts[1])
    
    # Определяем доступные виды корма для животного в слоте и показываем количества
    from ferma import get_user_farm_animals, ANIMALS_CONFIG
    placed = get_user_farm_animals(user_id)
    if slot_number not in placed:
        await callback.answer("В этом слоте нет животного", show_alert=True)
        return
    a = placed[slot_number]
    allowed_foods = ANIMALS_CONFIG.get(a['type'], {}).get('food_items', ['06', '07'])
    # Считаем количество корма у пользователя
    inv_map = {i: c for i, c in db.get_inventory(user_id)}
    wheat_qty = inv_map.get('06', 0)
    corn_qty = inv_map.get('07', 0)
    
    row = []
    if '06' in allowed_foods:
        row.append(InlineKeyboardButton(text=f"🌾 Пшеница ({wheat_qty} шт)", callback_data=f"feed_with:06:{slot_number}"))
    if '07' in allowed_foods:
        row.append(InlineKeyboardButton(text=f"🌽 Кукуруза ({corn_qty} шт)", callback_data=f"feed_with:07:{slot_number}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="⬅️ Назад", callback_data="farm_animals")]])
    
    await callback.message.edit_text(
        f"Выберите чем покормить животное в слоте #{slot_number}:",
        reply_markup=kb
    )

# --- Обработчик выбора еды для кормления ---

@dp.callback_query(lambda c: c.data.startswith("feed_with:"))
async def callback_feed_with(callback: types.CallbackQuery):
    """Кормит животное выбранной едой"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return
    
    food_item_id = parts[1]  # 06 или 07
    slot_number = int(parts[2])
    
    from ferma import feed_animal
    result = feed_animal(user_id, slot_number, food_item_id)
    
    await callback.answer(result['msg'], show_alert=True)
    
    if result['status'] == 'ok':
        # Возвращаемся в меню животных
        await callback_farm_animals(callback)

# --- Обработчик снятия животного с фермы ---

@dp.callback_query(lambda c: c.data.startswith("remove_animal:"))
async def callback_remove_animal(callback: types.CallbackQuery):
    """Убирает животное с фермы обратно в инвентарь"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return
    
    slot_number = int(parts[1])
    
    from ferma import remove_animal_from_farm
    result = remove_animal_from_farm(user_id, slot_number)
    
    await callback.answer(result['msg'], show_alert=True)
    
    if result['status'] == 'ok':
        # Возвращаемся в меню животных
        await callback_farm_animals(callback)

# --- Обработчик склада удален - теперь склад улучшается вместе с фермой ---

# --- Команда /ref для получения реферальной ссылки и статистики ---
@dp.message(Command("ref"))
async def cmd_ref(message: types.Message):
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None) or "NoUsername"
    await add_user(user_id, username)
    link = await get_referral_link(user_id)
    referrals = await get_referrals(user_id)
    ref_count = len(referrals)

    # Короткий текст + ссылка в коде для удобного копирования
    text = (
        f"🔗 Ваша реферальная ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: {ref_count}\n"
        f"💰 Заработано: {ref_count * 350} дань"
    )

    # Кнопки: открыть ссылку (верх) и "Посмотреть список" (низ)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📋 Посмотреть список", callback_data="ref_list:1"))

    await message.reply(text, parse_mode="HTML", reply_markup=kb.as_markup())

# Текстовый алиас: "реф"/"ref"
@dp.message(lambda m: m.text and m.text.lower().strip() in ["реф", "ref"])
async def cmd_ref_alias(message: types.Message):
    await cmd_ref(message)

# Показываем краткую сводку /ref по кнопке "ref_back"
@dp.callback_query(lambda c: c.data == "ref_back")
async def ref_back_summary(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await safe_callback_answer(callback)
        return
    link = await get_referral_link(user_id)
    referrals = await get_referrals(user_id)
    ref_count = len(referrals)
    text = (
        f"🔗 Ваша реферальная ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: {ref_count}\n"
        f"💰 Заработано: {ref_count * 350} дань"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📋 Посмотреть список", callback_data="ref_list:1"))
    await safe_edit_message(callback, text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await safe_callback_answer(callback)

# Пагинация списка рефералов: 50 на страницу
@dp.callback_query(lambda c: c.data and c.data.startswith("ref_list:"))
async def ref_list_paginated(callback: types.CallbackQuery):
    try:
        parts = callback.data.split(":")
        page = int(parts[1]) if len(parts) > 1 else 1
    except Exception:
        page = 1

    user_id = callback.from_user.id
    referrals = await get_referrals(user_id)
    total = len(referrals)
    per_page = 50
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = min(start + per_page, total)

    # Текстовый список до 50 элементов с кастомными именами
    lines = [f"👥 Рефералы: {total} | Страница {page}/{pages}"]
    idx = start + 1
    for uid, uname in referrals[start:end]:
        try:
            display = get_display_name(uid, uname)
        except Exception:
            display = uname or f"ID:{uid}"
        lines.append(f"{idx}. {display} (ID: {uid})")
        idx += 1
    text = "\n".join(lines)

    # Навигация: < page > и Назад
    kb = InlineKeyboardBuilder()
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"ref_list:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"ref_list:{page+1}"))
    if nav_row:
        kb.row(*nav_row)
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="ref_back"))

    await safe_edit_message(callback, text, reply_markup=kb.as_markup())
    await safe_callback_answer(callback)

# === КОМАНДЫ РАЗДЕЛОВ МЕНЮ ===

@dp.message(lambda message: message.text and message.text.lower().strip() == "ферма")
async def cmd_ferma(message: types.Message):
    """Открывает меню фермы (доступно в чате и в лс)"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    # Ensure user exists
    safe_ensure_user_from_obj(message.from_user)

    try:
        # Reuse the same logic as menu_ferma_callback but send a message instead of editing media
        from ferma import get_farm, get_farm_leaderboard_position, collect_dan, get_next_upgrade_cost

        # Автосбор дань на склад
        collect_dan(user_id)

        farm = get_farm(user_id)
        place = get_farm_leaderboard_position(user_id)
        user_row = db.get_user(user_id)
        bal = user_row.get("dan", 0) if user_row else 0
        try:
            bal = float(bal)
        except Exception:
            bal = 0.0
        bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
        bal = format_number_beautiful(bal)

        stored_dan = farm.get('stored_dan', 0)
        try:
            stored_dan = float(stored_dan)
        except Exception:
            stored_dan = 0.0
        stored_dan = 0.00 if abs(stored_dan) < 0.005 else round(stored_dan, 2)
        stored_dan_text = f"{stored_dan:.2f}"
        # Полностью синхронизируем подпись со вкладкой из меню
        farm_status = f"🌱 Дань на складе фермы: {stored_dan_text}"

        hour = datetime.datetime.now().hour
        greeting = "Доброе утро, фермер!" if 6 <= hour < 18 else "Доброй ночи, фермер!"
        photo_path = "C:/BotKruz/ChatBotKruz/photo/fermaday.png" if 6 <= hour < 18 else "C:/BotKruz/ChatBotKruz/photo/fermanight.png"

        # Проверяем активен ли бесконечный склад
        infinite_storage = db.get_user_effect(user_id, "infinite_storage")
        if infinite_storage:
            import time
            remaining_time = infinite_storage['expires_at'] - int(time.time())
            if remaining_time > 0:
                days = remaining_time // 86400
                hours = (remaining_time % 86400) // 3600
                minutes = (remaining_time % 3600) // 60
                storage_info = f"📮 Бесконечный склад активен: {days}д {hours}ч {minutes}м"
            else:
                storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"
        else:
            storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"

        # Доход и иконки животных
        from ferma import get_user_farm_animals, is_animal_active, ANIMALS_CONFIG
        animals = get_user_farm_animals(user_id)
        animals_income = 0
        counts = {}
        for _, a in animals.items():
            a_type = a['type']
            counts[a_type] = counts.get(a_type, 0) + 1
            if is_animal_active(a):
                cfg = ANIMALS_CONFIG.get(a_type, {})
                animals_income += cfg.get('income_per_hour', 0)
        icons_map = { 'cow': '🐮', 'chicken': '🐔' }
        icons = ''.join(icons_map.get(t, '') * n for t, n in counts.items())
        income_text = (
            f"🌾 Доход в час: {farm['income_per_hour']} (+{animals_income} {icons})"
            if icons else f"🌾 Доход в час: {farm['income_per_hour']} (+0)"
        )

        reply = (
            f"👨‍🌾 🌾 {greeting}\n\n"
            f"🏡 Уровень фермы: {farm['level']}\n"
            f"{income_text}\n"
            f"{storage_info}\n"
            f"📊 Место в топе по доходу: {place}\n\n"
            f"{farm_status}\n"
            f"🪙 Дань на балансе: {bal}"
        )

        # Стоимость апгрейда
        next_cost = get_next_upgrade_cost(user_id)
        if next_cost is not None:
            upgrade_text = f"📈 Улучшить ({format_number_beautiful(next_cost)})"
        else:
            upgrade_text = "📈 Макс. уровень"

        # Приводим клавиатуру к тому же виду, что и при нажатии "Ферма" в меню
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=upgrade_text, callback_data="upgrade_ferma"),
                InlineKeyboardButton(text="🐄 Животные", callback_data="farm_animals")
            ],
            [InlineKeyboardButton(text="📥 Собрать дань", callback_data="collect_ferma")],
            [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
        ])

        try:
            photo = FSInputFile(photo_path)
            await message.answer_photo(photo, caption=reply, reply_markup=kb)
        except Exception:
            await message.answer(reply, reply_markup=kb)

    except Exception as e:
        # Фолбек: показать сообщение без фото
        await message.reply(f"🌾 Ферма\n\nВременно недоступна.", reply_markup=create_back_to_menu_keyboard(user_id))

@dp.message(Command("ferma"))
async def cmd_ferma_command(message: types.Message):
    """Alias for English /ferma command — behaves the same as Russian 'ферма' and works in chats."""
    await cmd_ferma(message)

@dp.message(lambda message: message.text and message.text.lower().strip() in ["магаз", "магазин", "шоп"])
async def cmd_shop(message: types.Message):
    """Команда /магаз - открывает магазин"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)
    
    try:
        # Получаем баланс пользователя
        user_row = db.get_user(user_id)
        dan_balance = 0.0
        kruz_balance = 0
        if user_row:
            try:
                dan_balance = float(user_row.get("dan", 0))
            except Exception:
                dan_balance = 0.0
            try:
                kruz_balance = int(user_row.get("kruz", 0))
            except Exception:
                kruz_balance = 0
        dan_balance = 0.00 if abs(dan_balance) < 0.005 else round(dan_balance, 2)

        # Получаем данные для первой страницы
        items, total, max_page = get_all_shop_items(page=1)
        keyboard = build_shop_main_menu(page=1, max_page=max_page)

        # Пробуем отправить графическую сетку
        try:
            from inv_py.shop import render_shop_grid
            shop_image_path = render_shop_grid(page=1, font_path="C:/Windows/Fonts/arial.ttf")
            caption = (
                f"🛍️ <b>Магазин</b>\n\n"
                f"💰 Ваш баланс:\n🪙 Дань: {format_number_beautiful(dan_balance)}\n"
                f"⭐ Stars: {format_number_beautiful(kruz_balance)}\n\n"
                f"Всего товаров: {total}\nСтраница 1 из {max_page}"
            )
            await message.answer_photo(photo=FSInputFile(shop_image_path), caption=caption, reply_markup=keyboard, parse_mode="HTML")
            try:
                if shop_image_path and os.path.exists(shop_image_path):
                    os.remove(shop_image_path)
            except Exception:
                pass
        except Exception:
            # Фолбек: текстовое представление
            caption_lines = [
                f"🛍️ <b>Магазин</b>",
                "",
                f"💰 Ваш баланс:",
                f"🪙 Дань: {format_number_beautiful(dan_balance)}",
                f"⭐ Stars: {format_number_beautiful(kruz_balance)}",
                "",
            ]
            try:
                for idx, entry in enumerate(items, start=1):
                    iid = entry[0]
                    if iid and iid != 'empty':
                        name = ITEMS_CONFIG.get(iid, {}).get('name', iid)
                        caption_lines.append(f"[{idx}] {name}")
                    else:
                        caption_lines.append(f"[{idx}] —")
            except Exception:
                pass
            caption = "\n".join(caption_lines)
            await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"🛍️ Магазин\n\nВременно недоступен.", 
                           reply_markup=create_back_to_menu_keyboard(user_id))

@dp.message(lambda message: message.text and message.text.lower().strip() in ["аук", "аукцион"])
async def cmd_auction(message: types.Message):
    """Команда /аук - открывает аукцион"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)
    
    text = f"🏛️ <b>АУКЦИОН</b>\n\n" \
           f"💰 Место где можно купить и продать редкие предметы\n" \
           f"🔥 Торгуйтесь с другими игроками\n" \
           f"⏰ Следите за временем окончания лотов\n\n" \
           f"💡 Используйте кнопки ниже для навигации"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Создать лот", callback_data=f"auction_create:{user_id}")],
        [InlineKeyboardButton(text="👀 Активные лоты", callback_data=f"auction_list:{user_id}")],
        [InlineKeyboardButton(text="📊 Мои лоты", callback_data=f"auction_my:{user_id}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"open_game_menu:{user_id}")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(lambda message: message.text and message.text.lower().strip().strip("!.,?") in [
    "инвентарь", "инв", "инв.", "инвент", "сумка", "рюкзак"
])
async def cmd_inventory(message: types.Message):
    """Текстовые команды на русском для открытия инвентаря (как /inv)"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)

    try:
        # Полноценное открытие инвентаря как по /inv: с миграцией животных и рендером сетки
        items, total, max_page = get_user_inventory(user_id, page=1, force_sync=True)

        grid_items = []
        item_images = {}
        for item_id, count in items:
            if item_id == "empty":
                name = "Пусто"
                icon_path = NULL_ITEM["photo_square"]
                base_id = None
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

        photo_path = get_cached_image(grid_items, item_images)
        text = f"🎒 Ваш инвентарь\nВсего предметов: {total}"
        kb = build_inventory_markup(page=1, max_page=max_page, owner_user_id=user_id)
        await message.answer_photo(FSInputFile(photo_path), caption=text, reply_markup=kb)
    except Exception as e:
        await message.reply(
            f"🎒 Инвентарь\n\nВременно недоступен.",
            reply_markup=create_back_to_menu_keyboard(user_id)
        )

@dp.message(lambda message: message.text and message.text.lower().strip() in ["топ", "рейтинг", "топы"])
async def cmd_tops(message: types.Message):
    """Команда /топ - открывает топы игроков"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)
    
    text = "Игры Круз'а\nВыберите топ:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ мира", callback_data=f"top_world:{user_id}")],
        [
            InlineKeyboardButton(text="⏰ Топ игроков", callback_data=f"top_chat:{user_id}"),
            InlineKeyboardButton(text="👥 Топ реферелов", callback_data=f"top_ref:{user_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"open_game_menu:{user_id}")]
    ])
    await message.answer(text, reply_markup=keyboard)

async def safe_edit_media_or_text(message, photo_path, reply, kb):
    """
    Безопасно редактирует сообщение с фото или текстом, с обработкой ошибок Telegram.
    """
    from aiogram.types import InputMediaPhoto
    try:
        photo = FSInputFile(photo_path)
        await message.edit_media(media=InputMediaPhoto(media=photo, caption=reply), reply_markup=kb)
    except Exception as e:
        try:
            await message.edit_text(reply, reply_markup=kb)
        except Exception as e2:
            # Если ошибка "message is not modified" или "there is no text in the message to edit" — игнорируем
            err_text = str(e2)
            if "message is not modified" in err_text or "there is no text in the message to edit" in err_text:
                pass
            else:
                logging.error(f"safe_edit_media_or_text error: {e2}")


# Админ-команды: +dan/-dan, +don/-don в ответ на сообщение — выдать/отобрать дань у пользователя
@dp.message(lambda m: m.reply_to_message and m.text and (m.text.strip().startswith("+dan") or m.text.strip().startswith("-dan") or m.text.strip().startswith("+дань") or m.text.strip().startswith("-дань")))
async def admin_dan(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Нет доступа.")
        return
    
    text = message.text.strip()
    try:
        operation, val = parse_command_with_value(text, ["+dan", "+дань", "-dan", "-дань"])
        if operation is None:
            raise ValueError("Invalid format")
    except Exception:
        await message.reply("Формат: +dan N или -dan N (или +дань/-дань)")
        return
        
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Нужно ответить на сообщение пользователя.")
        return
        
    target = message.reply_to_message.from_user
    username = getattr(target, 'username', None)
    safe_ensure_user(target.id, username)
    display_name = getattr(target, 'full_name', None) or (f"@{username}" if username else str(getattr(target, 'id', 'unknown')))
    
    if operation == "add":
        db.add_dan(target.id, val)
        user_row = db.get_user(target.id) or {}
        dan_bal = user_row.get('dan', 0)
        await message.reply(f"Пользователю {display_name} выдано {val} дань. Баланс: {dan_bal:.2f}")
    else:
        if db.withdraw_dan(target.id, val):
            user_row = db.get_user(target.id) or {}
            dan_bal = user_row.get('dan', 0)
            await message.reply(f"У пользователя {display_name} изъято {val} дань. Баланс: {dan_bal:.2f}")
        else:
            await message.reply("Недостаточно дань для изъятия у пользователя.")

ferma_public_cooldowns = dict()

@dp.message(Command("ferma"))
async def cmd_ferma_en(message: types.Message):
    import time
    if not getattr(message, 'chat', None):
        return
    if message.chat.type != "private":
        await bot.send_message(message.chat.id, "Команда доступна только в личных сообщениях бота \n \n Тыкаю сЮды ➡️ @KruzChatBot")
        return
    now = datetime.datetime.now()
    hour = now.hour
    greeting = "Доброе утро, фермер!" if 6 <= hour < 18 else "Доброй ночи, фермер!"
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)
    from ferma import collect_dan
    collect_dan(user_id)  # Автоматически начисляем накопленную дань
    farm = get_farm(user_id)
    place = get_farm_leaderboard_position(user_id)
    bal = db.get_user(user_id)["dan"]
    bal = float(bal)
    bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
    bal = format_number_beautiful(bal)
    # Гарантируем, что stored_dan определён
    stored_dan = farm['stored_dan'] if 'stored_dan' in farm else 0
    stored_dan = float(stored_dan)
    stored_dan = 0.00 if abs(stored_dan) < 0.005 else round(stored_dan, 2)
    stored_dan = f"{stored_dan:.2f}"
    # Доход и иконки животных
    from ferma import get_user_farm_animals, is_animal_active, ANIMALS_CONFIG
    animals = get_user_farm_animals(user_id)
    animals_income = 0
    counts = {}
    for _, a in animals.items():
        a_type = a['type']
        counts[a_type] = counts.get(a_type, 0) + 1
        if is_animal_active(a):
            cfg = ANIMALS_CONFIG.get(a_type, {})
            animals_income += cfg.get('income_per_hour', 0)
    icons_map = { 'cow': '🐮', 'chicken': '🐔' }
    icons = ''.join(icons_map.get(t, '') * n for t, n in counts.items())
    income_text = (
        f"🌾 Доход в час: {farm['income_per_hour']} (+{animals_income} {icons})"
        if icons else f"🌾 Доход в час: {farm['income_per_hour']} (+0)"
    )
    reply = (
        f"👨‍🌾 🌾 {greeting}\n\n"
        f"🏡 Уровень фермы: {farm['level']}\n"
        f"{income_text}\n"
        f"📮 Вместимость склада: {farm['warehouse_capacity']}\n"
        f"📊 Место в топе по доходу: {place}\n\n"
        f"🌱 Дань на складе фермы: {stored_dan}\n"
        f"🪙 Дань на балансе: {bal}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈Улуч. Ферму", callback_data="upgrade_ferma"),
            InlineKeyboardButton(text="🧱Улуч. склад", callback_data="upgrade_warehouse")
        ],
        [InlineKeyboardButton(text="🐄 Животные", callback_data="farm_animals")],
        [InlineKeyboardButton(text="Собрать дань", callback_data="collect_ferma")]
    ])
    try:
        photo = FSInputFile("C:/BotKruz/ChatBotKruz/photo/fermaday.png" if 6 <= hour < 18 else "C:/BotKruz/ChatBotKruz/photo/fermanight.png")
        await message.answer_photo(photo, caption=reply, reply_markup=kb)
    except Exception as e:
        await message.reply(f"[Ошибка фото: {e}]\n" + reply, reply_markup=kb)
    # Удалено автоудаление
    return

# --- КОМАНДА ФАРМ ---
async def check_channel_subscription(user_id: int, channel_username: str = "DanuloKruz") -> bool:
    """Проверяет подписку пользователя на канал"""
    try:
        member = await bot.get_chat_member(f"@{channel_username}", user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        # Если канал недоступен для проверки участников, показываем сообщение о подписке
        print(f"Ошибка проверки подписки: {e}")
        return False  # Показываем сообщение о подписке

@dp.message(lambda message: message.text and message.text.lower().strip() in ["фарм", "/farm", "afhv"])
async def cmd_farm_collect(message: types.Message):
    """Команда 'фарм' и '/farm' - сбор дани с проверкой подписки на канал"""
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    
    # Проверяем подписку на канал
    is_subscribed = await check_channel_subscription(user_id)
    
    if not is_subscribed:
        await message.reply(
            '❌ Команда <b>"фарм"</b> работает после подписки на канал разработчика! \n\n✅ - - - > @DanuloKruz',
            parse_mode='HTML'
        )
        return
    
    # Если подписан - собираем дань с фермы
    from ferma import collect_dan
    
    # Получаем баланс до сбора
    user = db.get_user(user_id)
    if not user:
        safe_ensure_user_from_obj(message.from_user)
        user = db.get_user(user_id)
    
    balance_before = float(user.get("dan", 0)) if user else 0.0
    
    # Собираем дань (сначала начисляем на склад)
    collect_result = collect_dan(user_id)
    
    # Переводим дань со склада на баланс
    from ferma import transfer_dan_to_balance
    collected_amount = transfer_dan_to_balance(user_id)
    
    # Получаем баланс после сбора
    user_after = db.get_user(user_id)
    balance_after = float(user_after.get("dan", 0)) if user_after else 0.0
    
    # Форматируем числа с пробелами
    def format_balance(amount):
        return f"{amount:,.2f}".replace(",", " ")
    
    if collected_amount > 0:
        await message.reply(
            f"💰 Вы собрали дань!\n\n"
            f"💸 Получено: {format_balance(collected_amount)} дань\n"
            f"👤 Баланс до: {format_balance(balance_before)} дань\n"
            f"💰 Баланс сейчас: {format_balance(balance_after)} дань"
        )
    else:
        await message.reply(
            f"📦 Склад пуст!\n\n"
            f"💰 Ваш баланс: {format_balance(balance_after)} дань\n"
            f"⏰ Подождите немного, дань накопится на складе"
        )

# Callback для проверки подписки
@dp.callback_query(lambda c: c.data.startswith("check_subscription:"))
async def check_subscription_callback(callback: types.CallbackQuery):
    """Проверка подписки на канал по кнопке"""
    if not getattr(callback, 'from_user', None):
        return
    
    try:
        _, user_id = callback.data.split(":")
        user_id = int(user_id)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    # Проверяем, что кнопку нажал владелец
    if callback.from_user.id != user_id:
        await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
        return
    
    # Проверяем подписку
    is_subscribed = await check_channel_subscription(user_id)
    
    if is_subscribed:
        await callback.answer("✅ Отлично! Теперь можете использовать команду 'фарм'", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        await callback.answer("❌ Подписка не найдена. Убедитесь, что подписались на канал!", show_alert=True)

# --- КРЕСТИКИ-НОЛИКИ ---
@dp.message(lambda message: message.text and message.text.lower().startswith("нолик"))
async def tic_tac_toe_challenge_handler(message: types.Message):
    """Обработчик команды 'нолик СУММА' - вызов на крестики-нолики за нолики"""
    increment_games_count()
    
    if not message.from_user or not message.text:
        return
        
    # Проверяем что это ответ на сообщение
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("❌ Ответьте на сообщение пользователя которого хотите вызвать!\nПример: нолик 100")
        return
        
    user_id = message.from_user.id
    opponent_id = message.reply_to_message.from_user.id
    
    # Проверяем что не вызывают бота
    if is_bot_user(opponent_id):
        await message.reply("❌ Ой, бот не играет в такое!")
        return
        
    if user_id == opponent_id:
        await message.reply("❌ Нельзя играть самому с собой!")
        return
        
    safe_ensure_user(user_id, getattr(message.from_user, 'username', None))
    safe_ensure_user(opponent_id, getattr(message.reply_to_message.from_user, 'username', None))
    
    # Парсим ставку
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await message.reply("❌ Укажите ставку!\nПример: нолик 100")
        return
        
    try:
        bet_amount = int(parts[1])
    except ValueError:
        await message.reply("❌ Ставка должна быть числом!")
        return
        
    if bet_amount < 10:
        await message.reply("❌ Минимальная ставка 10 дань!")
        return
        
    # Проверяем баланс вызывающего (он будет играть за нолики - игрок 2)
    challenger_balance = db.get_user(user_id)
    if not challenger_balance or challenger_balance["dan"] < bet_amount:
        await message.reply(f"❌ У вас недостаточно дани! Нужно: {bet_amount}, у вас: {challenger_balance['dan'] if challenger_balance else 0}")
        return
        
    # Проверяем баланс противника
    opponent_balance = db.get_user(opponent_id)
    if not opponent_balance or opponent_balance["dan"] < bet_amount:
        opponent_name_short = message.reply_to_message.from_user.full_name or f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else f"ID{opponent_id}"
        await message.reply(f"❌ У {opponent_name_short} недостаточно дани! Нужно: {bet_amount}, у него: {opponent_balance['dan'] if opponent_balance else 0}")
        return
        
    # Создаем вызов (вызывающий будет игроком 2 - нолики)
    from plugins.games.tic_tac_toe import start_tic_tac_toe_challenge
    
    challenger_name = message.from_user.full_name or f"@{message.from_user.username}" if message.from_user.username else f"ID{user_id}"
    opponent_name = message.reply_to_message.from_user.full_name or f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else f"ID{opponent_id}"
    
    # Вызывающий хочет играть за нолики (player2), значит противник будет играть за крестики (player1)
    game = start_tic_tac_toe_challenge(opponent_id, opponent_name, user_id, challenger_name, bet_amount)
    # Регистрируем прогресс баттлов для обоих игроков
    try:
        tasks.record_battle_play(user_id)
        tasks.record_battle_play(opponent_id)
    except Exception:
        pass
    
    challenge_text = (
        f"⭕ <b>Вызов на крестики-нолики!</b>\n\n"
        f"🎯 {challenger_name} вызывает {opponent_name}\n"
        f"⭕ {challenger_name} играет за <b>нолики</b>\n"
        f"❌ {opponent_name} играет за <b>крестики</b>\n"
        f"💰 Ставка: {bet_amount} дань каждый\n"
        f"💸 Комиссия: 10% (при ничьей по 10% с каждого)\n\n"
        f"❓ {opponent_name}, принимаете вызов?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"ttt_accept:{game.game_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"ttt_decline:{game.game_id}")
        ]
    ])
    
    await message.reply(challenge_text, reply_markup=keyboard, parse_mode='HTML')

@dp.message(lambda message: message.text and (message.text.lower().startswith("хрестик") or message.text.lower().startswith("крестик") or message.text.lower().startswith("крестики")))
async def tic_tac_toe_cross_challenge_handler(message: types.Message):
    """Обработчик команд 'хрестик/крестик/крестики СУММА' - вызов на крестики-нолики за крестики"""
    increment_games_count()
    
    if not message.from_user or not message.text:
        return
        
    # Проверяем что это ответ на сообщение
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("❌ Ответьте на сообщение пользователя которого хотите вызвать!\nПример: хрестик 100")
        return
        
    user_id = message.from_user.id
    opponent_id = message.reply_to_message.from_user.id
    
    # Проверяем что не вызывают бота
    if is_bot_user(opponent_id):
        await message.reply("❌ Ой, бот не играет в такое!")
        return
        
    if user_id == opponent_id:
        await message.reply("❌ Нельзя играть самому с собой!")
        return
        
    safe_ensure_user(user_id, getattr(message.from_user, 'username', None))
    safe_ensure_user(opponent_id, getattr(message.reply_to_message.from_user, 'username', None))
    
    # Парсим ставку
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await message.reply("❌ Укажите ставку!\nПример: хрестик 100")
        return
        
    try:
        bet_amount = int(parts[1])
    except ValueError:
        await message.reply("❌ Ставка должна быть числом!")
        return
        
    if bet_amount < 10:
        await message.reply("❌ Минимальная ставка 10 дань!")
        return
        
    # Проверяем баланс вызывающего (он будет играть за крестики - игрок 1)
    challenger_balance = db.get_user(user_id)
    if not challenger_balance or challenger_balance["dan"] < bet_amount:
        await message.reply(f"❌ У вас недостаточно дани! Нужно: {bet_amount}, у вас: {challenger_balance['dan'] if challenger_balance else 0}")
        return
        
    # Проверяем баланс противника
    opponent_balance = db.get_user(opponent_id)
    if not opponent_balance or opponent_balance["dan"] < bet_amount:
        opponent_name_short = message.reply_to_message.from_user.full_name or f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else f"ID{opponent_id}"
        await message.reply(f"❌ У {opponent_name_short} недостаточно дани! Нужно: {bet_amount}, у него: {opponent_balance['dan'] if opponent_balance else 0}")
        return
        
    # Создаем вызов (вызывающий будет игроком 1 - крестики)
    from plugins.games.tic_tac_toe import start_tic_tac_toe_challenge
    
    challenger_name = message.from_user.full_name or f"@{message.from_user.username}" if message.from_user.username else f"ID{user_id}"
    opponent_name = message.reply_to_message.from_user.full_name or f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else f"ID{opponent_id}"
    
    # Вызывающий хочет играть за крестики (player1), значит противник будет играть за нолики (player2)
    game = start_tic_tac_toe_challenge(user_id, challenger_name, opponent_id, opponent_name, bet_amount)
    # Регистрируем прогресс баттлов для обоих игроков
    try:
        tasks.record_battle_play(user_id)
        tasks.record_battle_play(opponent_id)
    except Exception:
        pass
    
    challenge_text = (
        f"❌ <b>Вызов на крестики-нолики!</b>\n\n"
        f"🎯 {challenger_name} вызывает {opponent_name}\n"
        f"❌ {challenger_name} играет за <b>крестики</b>\n"
        f"⭕ {opponent_name} играет за <b>нолики</b>\n"
        f"💰 Ставка: {bet_amount} дань каждый\n"
        f"💸 Комиссия: 10% (при ничьей по 10% с каждого)\n\n"
        f"❓ {opponent_name}, принимаете вызов?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"ttt_accept:{game.game_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"ttt_decline:{game.game_id}")
        ]
    ])
    
    await message.reply(challenge_text, reply_markup=keyboard, parse_mode='HTML')

# Callback обработчики для крестиков-ноликов
@dp.callback_query(lambda c: c.data and c.data.startswith("ttt_accept:"))
async def tic_tac_toe_accept_callback(callback: types.CallbackQuery):
    """Принять вызов на крестики-нолики"""
    if not callback.from_user or not callback.data:
        return
        
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    from plugins.games.tic_tac_toe import accept_tic_tac_toe_challenge
    
    result = accept_tic_tac_toe_challenge(game_id, user_id)
    
    if not result["success"]:
        await callback.answer(f"❌ {result['error']}", show_alert=True)
        return
        
    game = result["game"]
    
    # Обновляем сообщение с игровым полем
    from plugins.games.tic_tac_toe import safe_edit_text
    await safe_edit_text(
        callback.message,
        game.get_status_text(),
        reply_markup=game.get_keyboard(),
        parse_mode='HTML'
    )
    
    # Увеличиваем счетчик игр
    increment_games_count()
    
    await callback.answer("✅ Игра началась!")

@dp.callback_query(lambda c: c.data and c.data.startswith("ttt_decline:"))
async def tic_tac_toe_decline_callback(callback: types.CallbackQuery):
    """Отклонить вызов на крестики-нолики"""
    if not callback.from_user or not callback.data:
        return
        
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    from plugins.games.tic_tac_toe import decline_tic_tac_toe_challenge
    
    result = decline_tic_tac_toe_challenge(game_id, user_id)
    
    if not result["success"]:
        await callback.answer(f"❌ {result['error']}", show_alert=True)
        return
    
    from plugins.games.tic_tac_toe import safe_edit_text
    await safe_edit_text(callback.message, "❌ Вызов отклонен")
    await callback.answer("❌ Вызов отклонен")

@dp.callback_query(lambda c: c.data and c.data.startswith("ttt_move:"))
async def tic_tac_toe_move_callback(callback: types.CallbackQuery):
    """Сделать ход в крестиках-ноликах"""
    if not callback.from_user or not callback.data:
        return
        
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
        
    game_id = parts[1]
    row = int(parts[2])
    col = int(parts[3])
    user_id = callback.from_user.id
    
    from plugins.games.tic_tac_toe import make_tic_tac_toe_move
    
    result = make_tic_tac_toe_move(game_id, user_id, row, col)
    
    if not result["success"]:
        await callback.answer(f"❌ {result['error']}", show_alert=True)
        return
        
    from plugins.games.tic_tac_toe import active_tic_tac_toe_games
    game = active_tic_tac_toe_games.get(game_id)
    
    if not game:
        await callback.answer("❌ Игра не найдена", show_alert=True)
        return
    
    # Обновляем сообщение
    from plugins.games.tic_tac_toe import safe_edit_text
    await safe_edit_text(
        callback.message,
        game.get_status_text(),
        reply_markup=game.get_keyboard(),
        parse_mode='HTML'
    )
    
    if result.get("game_over"):
        if game.winner == "draw":
            await callback.answer("🤝 Ничья! Комиссия списана", show_alert=True)
        else:
            winner_name = game.player1_name if game.winner == game.player1_id else game.player2_name
            await callback.answer(f"🏆 Победа: {winner_name}!", show_alert=True)
    else:
        await callback.answer("✅ Ход сделан!")

@dp.callback_query(lambda c: c.data and c.data == "ttt_noop")
async def tic_tac_toe_noop_callback(callback: types.CallbackQuery):
    """Пустой callback для занятых клеток"""
    await callback.answer("Эта клетка занята", show_alert=False)

# --- КОСТИ PvP ---
@dp.message(lambda message: message.text and message.text.lower().startswith("кости"))
async def dice_battle_handler(message: types.Message):
    increment_games_count()
    if not getattr(message, 'from_user', None) or not getattr(message, 'text', None):
        return
    user_id = message.from_user.id
    now = time.time()
    # Проверка блокировки
    # ...existing code...
    user_id = message.from_user.id
    safe_ensure_user(user_id, getattr(message.from_user, 'username', None))
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Формат: кости N (N — целое число >= 10)", show_alert=True)
        return
    try:
        bet = int(parts[1])
    except Exception:
        await message.answer("Ставка должна быть числом.", show_alert=True)
        return
    if bet < 10:
        await message.answer("Минимальная ставка — 10 Дань.", show_alert=True)
        return
    if message.reply_to_message and message.reply_to_message.from_user:
        # Проверяем что не вызывают бота
        if is_bot_user(message.reply_to_message.from_user.id):
            await message.reply("❌ Ой, бот не играет в такое!")
            return
        # Регистрируем прогресс баттлов для обоих игроков
        try:
            tasks.record_battle_play(user_id)
            tasks.record_battle_play(message.reply_to_message.from_user.id)
        except Exception:
            pass
        await betcosty.initiate_dice_battle(message, user_id, bet)
    else:
        await message.answer("Чтобы вызвать на кости, ответь на сообщение игрока и напиши 'кости N'.", show_alert=True)

# --- Обычные ставки ---
@dp.message(lambda message: message.text and message.text.lower().startswith("бет"))
async def universal_bet_handler(message: types.Message):
    increment_games_count()
    if not getattr(message, 'from_user', None) or not getattr(message, 'text', None):
        return
    user_id = message.from_user.id
    safe_ensure_user_from_obj(message.from_user)
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply("Пожалуйста, укажите ставку, например: бет 10")
        return
    bet = int(parts[1])
    if bet < 10:
        await message.reply("Минимальная ставка — 10 Дань.")
        return
    last_bet_stake[user_id] = bet
    # Регистрируем прогресс по ставкам
    try:
        tasks.record_bet_play(user_id, bet)
    except Exception:
        pass
    # Если это ответ на сообщение — PvP баттл
    if message.reply_to_message and message.reply_to_message.from_user:
        # Проверяем что не вызывают бота
        if is_bot_user(message.reply_to_message.from_user.id):
            await message.reply("❌ Ой, бот не играет в такое!")
            return
        # Регистрируем прогресс баттлов для обоих игроков
        try:
            tasks.record_battle_play(user_id)
            tasks.record_battle_play(message.reply_to_message.from_user.id)
        except Exception:
            pass
        await battles.initiate_battle(message, user_id, bet)
    else:
        await battles.solo_bet(message, user_id, bet)

# --- Банковская система ---
@dp.message(lambda message: message.text and message.text.lower().strip() == "банк")
async def bank_handler(message: types.Message):
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None) or "NoUsername"
    
    # Обеспечиваем пользователя в базе данных
    safe_ensure_user(user_id, username)
    
    # Получаем данные о банке и депозитах пользователя
    total_deposits_count = bank_system.get_total_deposits_count()
    total_bank_deposits = bank_system.get_total_bank_deposits()
    user_deposits_count = bank_system.get_user_deposits_count(user_id)
    user_total_deposits = bank_system.get_user_total_deposits(user_id)
    
    # Форматируем текст
    total_amount_text = format_full_amount(total_bank_deposits)
    user_amount_text = format_amount(user_total_deposits)
    
    text = (
        f"🏦 <b>БАНК KRUZCHAT</b> 🏦\n\n"
        f"📝 <b>Описание:</b>\n"
        f"Банк KruzChat — это безопасный способ заработать дань с гарантированной доходностью! Выбирайте срок депозита и получайте стабильную прибыль без рисков.\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🌍 Всего {total_deposits_count} депозитов в мире\n"
        f"💰 на сумму {total_amount_text} дань\n\n"
        f"👤 У вас {user_deposits_count} депозитов на {user_amount_text} дань\n\n"
        f"💎 <b>Тарифы:</b> (макс. 1,000,000 дань)\n"
        f"• 3 дня — 4% прибыли 📈\n"
        f"• 7 дней — 8% прибыли 📈\n"
        f"• 14 дней — 13% прибыли 📈\n"
        f"• 31 день — 31% прибыли 📈\n\n"
        f"🎯 <b>Выберите план депозита ниже:</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Кнопки планов депозитов (первый ряд)
        [
            InlineKeyboardButton(text="3", callback_data=f"bank_deposit_plan:3:4:{user_id}"),
            InlineKeyboardButton(text="7", callback_data=f"bank_deposit_plan:7:8:{user_id}"),
            InlineKeyboardButton(text="14", callback_data=f"bank_deposit_plan:14:13:{user_id}"),
            InlineKeyboardButton(text="31", callback_data=f"bank_deposit_plan:31:31:{user_id}")
        ],
        [InlineKeyboardButton(text="мои депозиты", callback_data=f"bank_my_deposits:{user_id}")]
    ])
    
    # Отправляем сообщение с банком
    await message.answer(text, reply_markup=keyboard, parse_mode='HTML')

@dp.message(Command("deposit"))
async def deposit_command_handler(message: types.Message):
    """Обработчик команды /deposit"""
    await bank_handler(message)

@dp.callback_query(lambda c: c.data.startswith("bank_menu:"))
async def bank_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки возврата в банк"""
    if not callback.from_user:
        return
    
    parts = callback.data.split(":")
    if len(parts) < 2:
        return
        
    owner_user_id = int(parts[1])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        await callback.answer("❌ Это не ваше меню!", show_alert=True)
        return
    
    # Создаем фейковое сообщение для вызова основного обработчика банка
    fake_message = type('FakeMessage', (), {
        'from_user': callback.from_user,
        'answer': callback.message.edit_text
    })()
    
    # Получаем данные о банке и депозитах пользователя
    user_id = callback.from_user.id
    total_deposits_count = bank_system.get_total_deposits_count()
    total_bank_deposits = bank_system.get_total_bank_deposits()
    user_deposits_count = bank_system.get_user_deposits_count(user_id)
    user_total_deposits = bank_system.get_user_total_deposits(user_id)
    
    # Форматируем текст
    total_amount_text = format_full_amount(total_bank_deposits)
    user_amount_text = format_amount(user_total_deposits)
    
    text = (
        f"🏦 <b>БАНК KRUZCHAT</b> 🏦\n\n"
        f"📝 <b>Описание:</b>\n"
        f"Банк KruzChat — это безопасный способ заработать дань с гарантированной доходностью! Выбирайте срок депозита и получайте стабильную прибыль без рисков.\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🌍 Всего {total_deposits_count} депозитов в мире\n"
        f"💰 на сумму {total_amount_text} дань\n\n"
        f"👤 У вас {user_deposits_count} депозитов на {user_amount_text} дань\n\n"
        f"💎 <b>Тарифы:</b> (макс. 1,000,000 дань)\n"
        f"• 3 дня — 4% прибыли 📈\n"
        f"• 7 дней — 8% прибыли 📈\n"
        f"• 14 дней — 13% прибыли 📈\n"
        f"• 31 день — 31% прибыли 📈\n\n"
        f"🎯 <b>Выберите план депозита ниже:</b>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Кнопки планов депозитов (первый ряд)
        [
            InlineKeyboardButton(text="3", callback_data=f"bank_deposit_plan:3:4:{user_id}"),
            InlineKeyboardButton(text="7", callback_data=f"bank_deposit_plan:7:8:{user_id}"),
            InlineKeyboardButton(text="14", callback_data=f"bank_deposit_plan:14:13:{user_id}"),
            InlineKeyboardButton(text="31", callback_data=f"bank_deposit_plan:31:31:{user_id}")
        ],
        [InlineKeyboardButton(text="мои депозиты", callback_data=f"bank_my_deposits:{user_id}")]
    ])
    
    await safe_edit_message(callback, text, keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data.startswith("bank_deposit_plan:"))
async def bank_deposit_plan_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора плана для ввода собственной суммы"""
    if not callback.from_user:
        return
    
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
        
    days = int(parts[1])
    interest_rate = int(parts[2])
    owner_user_id = int(parts[3])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        await callback.answer("❌ Это не ваш депозит!", show_alert=True)
        return
    
    # Переходим к состоянию ввода суммы для выбранного плана
    await state.set_state(BankStates.waiting_for_direct_deposit_amount)
    await state.update_data(
        user_id=owner_user_id, 
        days=days, 
        interest_rate=interest_rate,
        message_id=callback.message.message_id
    )
    
    # Получаем баланс пользователя
    user = db.get_user(owner_user_id)
    dan_balance = float(user.get("dan", 0)) if user else 0
    
    text = (
        f"💳 Депозит на {days} дней ({interest_rate}%)\n"
        f"-~-~-~-~-~-~-~-\n"
        f"💰 Ваш баланс: {format_amount(dan_balance)} дань\n\n"
        f"💵 Напишите сумму депозита <b><u>в ответ на это сообщение</u></b>:\n"
        f"💡 Минимум: 1000 дань\n"
        f"💎 Максимум: 1,000,000 дань"
    )
    
    # Создаем кнопки быстрого выбора сумм
    quick_amount_buttons = []
    
    # Первый ряд - кнопка "все X дань" или "всего 1м дань" для больших балансов (только если есть дань)
    if dan_balance > 0:
        if dan_balance >= 2000000:
            # Для больших балансов показываем кнопку "всего 1м дань"
            quick_amount_buttons.append([InlineKeyboardButton(text="всего 1м дань", callback_data=f"bank_quick_amount:1000000:{days}:{interest_rate}:{owner_user_id}")])
        else:
            # Для обычных балансов показываем кнопку "все X дань"
            quick_amount_buttons.append([InlineKeyboardButton(text=f"все {format_amount(dan_balance)} дань", callback_data=f"bank_quick_amount:{dan_balance}:{days}:{interest_rate}:{owner_user_id}")])
    
    # Второй ряд - стандартные суммы: 1к, 5к, 10к дань
    standard_amounts = [1000, 5000, 10000]
    
    # Создаем кнопки для стандартных сумм
    standard_buttons = []
    for amount in standard_amounts:
        if amount == 1000:
            text_btn = "1к дань"
        elif amount == 5000:
            text_btn = "5к дань"
        elif amount == 10000:
            text_btn = "10к дань"
        standard_buttons.append(InlineKeyboardButton(text=text_btn, callback_data=f"bank_quick_amount:{amount}:{days}:{interest_rate}:{owner_user_id}"))
    
    # Добавляем ряд со стандартными суммами (всегда показываем)
    quick_amount_buttons.append(standard_buttons)
    
    # Создаем клавиатуру с кнопками быстрого выбора сумм и отменой
    keyboard_rows = quick_amount_buttons + [
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"bank_cancel:{owner_user_id}")]
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Редактируем сообщение вместо создания нового
    # Сохраняем ID сообщения для проверки reply
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        # Сохраняем ID этого сообщения в state для проверки reply
        await state.update_data(prompt_message_id=callback.message.message_id)
        await callback.answer()
    except Exception as e:
        print(f"Ошибка редактирования сообщения с запросом суммы: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("bank_quick_amount:"))
async def bank_quick_amount_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопок быстрого выбора суммы депозита"""
    if not callback.from_user:
        return
    
    parts = callback.data.split(":")
    if len(parts) < 5:
        return
        
    amount_str = parts[1]
    days = int(parts[2])
    interest_rate = int(parts[3])
    owner_user_id = int(parts[4])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        await callback.answer("❌ Это не ваше меню!", show_alert=True)
        return
    
    try:
        amount = float(amount_str)
    except ValueError:
        await callback.answer("❌ Неверная сумма", show_alert=True)
        return
    
    # Проверяем минимальную сумму
    if amount < 1000:
        await callback.answer("❌ Минимальная сумма депозита: 1000 дань", show_alert=True)
        return
    
    # Проверяем максимальную сумму
    if amount > 1000000:
        await callback.answer("❌ Максимальная сумма депозита: 1,000,000 дань", show_alert=True)
        return
    
    # Проверяем баланс пользователя
    user = db.get_user(owner_user_id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    dan_balance = float(user.get("dan", 0))
    if amount > dan_balance:
        await callback.answer(f"❌ Недостаточно средств. Ваш баланс: {format_amount(dan_balance)} дань", show_alert=True)
        return
    
    # Создаем депозит сразу
    from bank import BankSystem
    bank = BankSystem()
    
    # Получаем имя пользователя
    username = callback.from_user.username or f"User_{owner_user_id}"
    
    success = bank.add_deposit(owner_user_id, username, amount, days, interest_rate / 100)
    
    if success:
        # Списываем средства
        from database import set_dan
        set_dan(owner_user_id, dan_balance - amount)
        
        profit = amount * (interest_rate / 100)
        total_return = amount + profit
        
        text = (
            f"✅ Депозит успешно создан!\n\n"
            f"💰 Сумма: {format_amount(amount)} дань\n"
            f"⏰ Срок: {days} дней\n"
            f"📈 Процент: {interest_rate}%\n"
            f"💎 Прибыль: +{format_amount(profit)} дань\n"
            f"💵 К выплате: {format_amount(total_return)} дань\n\n"
            f"💰 Ваш баланс: {format_amount(dan_balance - amount)} дань"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 В банк", callback_data=f"bank_menu:{owner_user_id}")]
        ])
        
        await safe_edit_message(callback, text, keyboard)
    else:
        await callback.answer("❌ Ошибка создания депозита", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("bank_my_deposits:"))
async def bank_my_deposits_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'мои депозиты'"""
    if not callback.from_user:
        return
    
    # Используем существующий обработчик bank_history_callback
    parts = callback.data.split(":")
    owner_user_id = int(parts[1])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        await callback.answer("❌ Это не ваши депозиты!", show_alert=True)
        return
    
    # Создаем фейковый callback для bank_history с первой страницей
    fake_callback = type('FakeCallback', (), {
        'from_user': callback.from_user,
        'message': callback.message,
        'data': f"bank_history:{owner_user_id}:1"
    })()
    
    await bank_history_callback(fake_callback)

@dp.callback_query(lambda c: c.data.startswith("bank_cancel:"))
async def bank_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик отмены депозита"""
    if not callback.from_user:
        return
    
    parts = callback.data.split(":")
    owner_user_id = int(parts[1])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await state.clear()
    
    # Возвращаемся к главному меню банка, редактируя текущее сообщение
    fake_callback = type('FakeCallback', (), {
        'from_user': callback.from_user,
        'message': callback.message,
        'data': f"bank_menu:{owner_user_id}",
        'answer': callback.answer
    })()
    
    await bank_menu_callback(fake_callback)

STAR_PACKAGES = [
    (1, 500), (10, 6000), (18, 12000), (34, 25000), (62, 50000), (112, 100000),
]

def get_today_games_count():
    """Получить количество игр за сегодня"""
    return get_games_count_from_db()

@dp.message(F.text.casefold().in_(["бал", "б", "баланс", "balance"]))
async def cmd_bal(message: types.Message):
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    safe_ensure_user(user_id, getattr(message.from_user, 'username', None))
    user = db.get_user(user_id)
    if not user:
        await message.reply("Пользователь не найден.")
        return
    dan = user["dan"]
    kruz = user["kruz"]
    games = user["games_played"]
    dan = float(dan)
    kruz = float(kruz)
    dan = 0.00 if abs(dan) < 0.005 else round(dan, 2)
    kruz = 0.00 if abs(kruz) < 0.005 else round(kruz, 2)
    
    # Красивое форматирование чисел с пробелами
    dan_formatted = format_number_beautiful(dan)
    kruz_formatted = format_number_beautiful(kruz)
    games_formatted = format_number_beautiful(games)
    
    await message.reply(
        f"Баланс:\n🪙 Дань: {dan_formatted}\n⭐ Stars: {kruz_formatted}\nИгр сыграно: {games_formatted}"
    )

# Обработчики текстовых сообщений для открытия меню
@dp.message(F.text.casefold().in_(["меню", "менюшка", "миню", "слоап"]))
async def text_menu_handler(message: types.Message):
    """Обработчик текстовых сообщений 'меню', 'менюшка', 'миню', 'слоап'"""
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    await show_main_menu(message, user_id)

# --- Обработчики банковских callback ---

@dp.callback_query(lambda c: c.data.startswith("bank_history:"))
async def bank_history_callback(callback: types.CallbackQuery):
    """Обработчик кнопки истории операций - показ списка депозитов"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    # Проверяем, что кнопку нажал владелец
    try:
        parts = callback.data.split(":")
        owner_user_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Получаем все депозиты пользователя
    all_deposits = bank_system.get_user_deposits(callback.from_user.id)
    
    if not all_deposits:
        text = (
            f"📋 Все ваши депозиты:\n\n"
            f"🤷‍♂️ Пока что здесь пусто...\n\n"
            f"💡 Самое время создать первый депозит!\n"
            f"🚀 Начните зарабатывать пассивный доход уже сегодня!"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bank_back:{owner_user_id}")]
        ])
        
        await safe_edit_message(callback, text, keyboard)
        return
    
    # Разбиваем на страницы
    page_deposits, current_page, max_page = paginate_deposits(all_deposits, page, per_page=6)
    
    text = (
        f"📋 Все ваши депозиты:\n\n"
        f"💎 Здесь собраны все ваши инвестиции! 🏆\n"
        f"✅ Готовые к сбору | ❓ Активные | ❓ Закрытые\n\n"
        f"👆 Нажмите на депозит для подробной информации\n"
    )
    
    # Создаем кнопки депозитов
    keyboard_rows = []
    
    for deposit in page_deposits:
        deposit_text = format_deposit_button_text(deposit)
        action_emoji = get_deposit_action_emoji(deposit['status'])
        
        # Кнопка с информацией о депозите и кнопка действия
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"{deposit_text}",
                callback_data=f"deposit_info:{deposit['id']}:{owner_user_id}"
            ),
            InlineKeyboardButton(
                text=f"{action_emoji}",
                callback_data=f"deposit_action:{deposit['id']}:{owner_user_id}"
            )
        ])
    
    # Навигация по страницам
    if max_page > 1:
        nav_buttons = []
        if current_page > 1:
            nav_buttons.append(InlineKeyboardButton(text="<", callback_data=f"bank_history:{owner_user_id}:{current_page-1}"))
        
        nav_buttons.append(InlineKeyboardButton(text=f"{current_page}/{max_page}", callback_data="noop"))
        
        if current_page < max_page:
            nav_buttons.append(InlineKeyboardButton(text=">", callback_data=f"bank_history:{owner_user_id}:{current_page+1}"))
        
        keyboard_rows.append(nav_buttons)
    
    # Кнопка назад
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bank_back:{owner_user_id}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await safe_edit_message(callback, text, keyboard)

# Обработчик информации о депозите
@dp.callback_query(lambda c: c.data.startswith("deposit_info:"))
async def deposit_info_callback(callback: types.CallbackQuery):
    """Показать подробную информацию о депозите"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, deposit_id, owner_user_id = callback.data.split(":")
        deposit_id = int(deposit_id)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Получаем информацию о депозите
    deposit = bank_system.get_deposit_info(callback.from_user.id, deposit_id)
    if not deposit:
        await callback.answer("Депозит не найден", show_alert=True)
        return
    
    amount = deposit['amount']
    days = deposit['duration_days']
    rate = deposit['interest_rate']
    remaining_days = deposit.get('remaining_days', 0)
    profit = amount * rate
    total_return = amount + profit
    status = deposit['status']
    
    # Определяем статус для отображения
    if status in ['closed_early', 'withdrawn_early', 'completed']:
        status_text = "❓ ДЕПОЗИТ ЗАКРЫТ!"
    else:
        status_text = f"❓ Осталось {remaining_days} дней."
    
    text = (
        f"💰 Сумма депозита: {amount:.0f} Дань\n"
        f"📅 Срок: {days} дней\n"
        f"📈 Процентная ставка: {int(rate*100)}%\n"
        f"💵 Прибыль: {profit:.0f} Дань\n"
        f"🎯 Итого к получению: {total_return:.0f} Дань\n"
        f"{status_text}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bank_history:{owner_user_id}:1")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)

# Обработчик действий с депозитом
@dp.callback_query(lambda c: c.data.startswith("deposit_action:"))
async def deposit_action_callback(callback: types.CallbackQuery):
    """Обработка действий с депозитом (X, ✅, 📋)"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, deposit_id, owner_user_id = callback.data.split(":")
        deposit_id = int(deposit_id)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Получаем информацию о депозите
    deposit = bank_system.get_deposit_info(callback.from_user.id, deposit_id)
    if not deposit:
        await callback.answer("Депозит не найден", show_alert=True)
        return
    
    status = deposit['status']
    
    if status == 'active':
        # Показываем меню подтверждения закрытия
        amount = deposit['amount']
        rate = deposit['interest_rate']
        remaining_days = deposit.get('remaining_days', 0)
        profit = amount * rate
        
        text = (
            f"💰 Сумма депозита: {amount:.0f} Дань\n"
            f"📈 Процентная ставка: {int(rate*100)}%\n"
            f"💵 Прибыль: {profit:.0f} Дань\n"
            f"📅 Осталько дней к получению: {remaining_days} дней\n\n"
            f"❓ Подтвердить ЗАКРЫТИЕ депозита?"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_close:{deposit_id}:{owner_user_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bank_history:{owner_user_id}:1")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        
    elif status == 'matured':
        # Собираем доходы
        success,  message_text, amount = bank_system.collect_completed_deposit(callback.from_user.id, deposit_id)
        
        if success:
            # Добавляем деньги на баланс
            db.add_dan(callback.from_user.id, int(amount))
            await callback.answer(f"✅ {message_text}", show_alert=True)
        else:
            await callback.answer(f"❌ {message_text}", show_alert=True)
        
        # Возвращаемся к списку депозитов
        fake_callback = types.CallbackQuery(
            id=callback.id,
            from_user=callback.from_user,
            chat_instance=callback.chat_instance,
            data=f"bank_history:{owner_user_id}:1",
            message=callback.message
        )
        await bank_history_callback(fake_callback)
        
    else:
        # Архивный депозит - просто показываем информацию
        await callback.answer("📋 Этот депозит уже закрыт", show_alert=True)

# Обработчик подтверждения закрытия депозита
@dp.callback_query(lambda c: c.data.startswith("confirm_close:"))
async def confirm_close_callback(callback: types.CallbackQuery):
    """Подтверждение закрытия депозита"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, deposit_id, owner_user_id = callback.data.split(":")
        deposit_id = int(deposit_id)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Закрываем депозит
    success, message_text = bank_system.close_deposit_early(callback.from_user.id, deposit_id)
    
    if success:
        # Получаем информацию о депозите для возврата суммы
        deposit = bank_system.get_deposit_info(callback.from_user.id, deposit_id)
        if deposit:
            amount = deposit['amount']
            db.add_dan(callback.from_user.id, int(amount))
        
        await callback.answer(f"✅ {message_text}", show_alert=True)
    else:
        await callback.answer(f"❌ {message_text}", show_alert=True)
    
    # Возвращаемся к списку депозитов
    fake_callback = types.CallbackQuery(
        id=callback.id,
        from_user=callback.from_user,
        chat_instance=callback.chat_instance,
        data=f"bank_history:{owner_user_id}:1",
        message=callback.message
    )
    await bank_history_callback(fake_callback)

# Заглушка для noop
@dp.callback_query(lambda c: c.data == "noop")
async def noop_callback(callback: types.CallbackQuery):
    """Заглушка для неактивных кнопок"""
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("bank_back:"))
async def bank_back_callback(callback: types.CallbackQuery):
    """Возврат в главное меню банка"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Используем новое меню банка через bank_menu_callback
    fake_callback = type('FakeCallback', (), {
        'from_user': callback.from_user,
        'message': callback.message,
        'data': f"bank_menu:{owner_user_id}",
        'answer': callback.answer
    })()
    
    await bank_menu_callback(fake_callback)

# Обработчик FSM для прямого ввода суммы депозита (когда план уже выбран)
@dp.message(BankStates.waiting_for_direct_deposit_amount)
async def process_direct_deposit_amount(message: types.Message, state: FSMContext):
    """Обработка ввода суммы для уже выбранного плана депозита"""
    if not getattr(message, 'from_user', None) or not getattr(message, 'text', None):
        return
    
    data = await state.get_data()
    user_id = data.get('user_id')
    days = data.get('days')
    interest_rate = data.get('interest_rate')
    
    if user_id != message.from_user.id:
        await state.clear()
        return
    
    # Проверяем что это reply на сообщение от бота (необязательно конкретное)
    # Это защитит от реакции на обычные сообщения с числами
    if not message.reply_to_message or not message.reply_to_message.from_user.is_bot:
        # Игнорируем обычные сообщения, реагируем только на reply на сообщения бота
        return
    
    try:
        amount = float(message.text.strip())
    except (ValueError, TypeError):
        await message.reply("❌ Введите корректную сумму числом")
        return
    
    if amount < 1000:
        await message.reply("❌ Минимальная сумма депозита: 1000 Дань")
        return
    
    if amount > 1000000:
        await message.reply("❌ Максимальная сумма депозита: 1,000,000 Дань")
        return
    
    # Проверяем баланс
    user = db.get_user(user_id)
    if not user:
        await message.reply("❌ Пользователь не найден")
        await state.clear()
        return
    
    dan_balance = float(user.get("dan", 0))
    if amount > dan_balance:
        await message.reply(f"❌ У вас недостаточно средств. Ваш баланс: {format_amount(dan_balance)} дань")
        return
    
    # Вычисляем прибыль (ставка в процентах, нужно перевести в десятичную)
    rate_decimal = interest_rate / 100
    profit = amount * rate_decimal
    total_return = amount + profit
    
    text = (
        f"💳 Подтверждение депозита\n"
        f"-~-~-~-~-~-~-~-\n\n"
        f"💰 Сумма депозита: {format_amount(amount)} дань\n"
        f"📅 Срок: {days} дней\n"
        f"📈 Процентная ставка: {interest_rate}%\n"
        f"💵 Прибыль: {format_amount(profit)} дань\n"
        f"🎯 Итого к получению: {format_amount(total_return)} дань\n\n"
        f"❓ Подтвердить создание депозита?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_direct_deposit:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"bank_cancel:{user_id}")]
    ])
    
    # Сохраняем данные для подтверждения
    await state.update_data(amount=amount, rate_decimal=rate_decimal)
    await state.set_state(BankStates.confirming_deposit)
    
    await message.answer(text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data.startswith("deposit_plan:"))
async def deposit_plan_callback(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 4: Обработка выбора плана и подтверждение"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, days_str, rate_str, owner_user_id = callback.data.split(":")
        days = int(days_str)
        rate = float(rate_str)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    data = await state.get_data()
    amount = data.get('amount', 0)
    
    if not amount:
        await callback.answer("Ошибка: сумма не найдена", show_alert=True)
        await state.clear()
        return
    
    # Вычисляем потенциальную прибыль
    profit = amount * rate
    total_return = amount + profit
    
    text = (
        f"💳 Подтверждение депозита\n"
        f"-~-~-~-~-~-~-~-\n\n"
        f"💰 Сумма депозита: {amount:.0f} Дань\n"
        f"📅 Срок: {days} дней\n"
        f"📈 Процентная ставка: {int(rate*100)}%\n"
        f"💵 Прибыль: {profit:.0f} Дань\n"
        f"🎯 Итого к получению: {total_return:.0f} Дань\n\n"
        f"❓ Подтвердить создание депозита?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_deposit:{days}:{rate}:{owner_user_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к выбору", callback_data=f"back_to_plans:{owner_user_id}")]
    ])
    
    await state.set_state(BankStates.confirming_deposit)
    await state.update_data(days=days, rate=rate)
    
    await safe_edit_message(callback, text, keyboard)

@dp.callback_query(lambda c: c.data.startswith("confirm_deposit:"))
async def confirm_deposit_callback(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 5: Финальное подтверждение и создание депозита"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, days_str, rate_str, owner_user_id = callback.data.split(":")
        days = int(days_str)
        rate = float(rate_str)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    data = await state.get_data()
    amount = data.get('amount', 0)
    
    if not amount:
        await callback.answer("Ошибка: данные депозита не найдены", show_alert=True)
        await state.clear()
        return
    
    # Проверяем баланс еще раз
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        await state.clear()
        return
    
    current_balance = float(user.get("dan", 0))
    if current_balance < amount:
        await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
        await state.clear()
        return
    
    # Списываем с баланса
    db.add_dan(callback.from_user.id, -int(amount))
    
    # Создаем депозит
    username = getattr(callback.from_user, 'username', None) or "NoUsername"
    success = bank_system.add_deposit(callback.from_user.id, username, amount, days, rate)
    
    if success:
        profit = amount * rate
        total_return = amount + profit
        
        text = (
            f"✅ Депозит успешно создан!\n\n"
            f"� Сумма: {amount:.0f} Дань\n"
            f"� Срок: {days} дней\n"
            f"📈 Ставка: {int(rate*100)}%\n"
            f"🎯 К получению: {total_return:.0f} Дань\n\n"
            f"💰 Деньги списаны с баланса.\n"
            f"📋 Депозит добавлен в ваши акты."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 Вернуться в банк", callback_data=f"bank_back:{owner_user_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("🎉 Депозит создан!", show_alert=True)
    else:
        # Возвращаем деньги в случае ошибки
        db.add_dan(callback.from_user.id, int(amount))
        await callback.answer("❌ Ошибка создания депозита. Деньги возвращены.", show_alert=True)
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("back_to_plans:"))
async def back_to_plans_callback(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору планов депозита"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    data = await state.get_data()
    amount = data.get('amount', 0)
    
    if not amount:
        await callback.answer("Ошибка: сумма не найдена", show_alert=True)
        await state.clear()
        return
    
    # Возвращаемся к выбору плана
    text = (
        f"💳 Депозит\n"
        f"-~-~-~-~-~-~-~-\n"
        f"Открывая депозит вы соглашаетесь с этими правилами... Подробнее...\n\n"
        f"Вы хотите открыть депозит на {amount:.0f} Дань."
    )
    
    # Создаем кнопки для планов депозита
    plan_buttons = []
    for days, rate in DEPOSIT_PLANS:
        plan_text = get_deposit_plan_text(days, rate)
        plan_buttons.append(InlineKeyboardButton(
            text=plan_text, 
            callback_data=f"deposit_plan:{days}:{rate}:{owner_user_id}"
        ))
    
    # Разбиваем кнопки по 3 в ряд
    keyboard_rows = [plan_buttons[i:i+3] for i in range(0, len(plan_buttons), 3)]
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ Вернуться", callback_data=f"bank_open:{owner_user_id}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("confirm_direct_deposit:"))
async def confirm_direct_deposit_callback(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение создания депозита для прямого выбора плана"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, owner_user_id = callback.data.split(":")
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    data = await state.get_data()
    amount = data.get('amount')
    days = data.get('days')
    interest_rate = data.get('interest_rate')
    rate_decimal = data.get('rate_decimal')
    
    if not all([amount, days, interest_rate, rate_decimal]):
        await callback.answer("Ошибка: данные депозита не найдены", show_alert=True)
        await state.clear()
        return
    
    # Проверяем баланс еще раз
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        await state.clear()
        return
    
    current_balance = float(user.get("dan", 0))
    if current_balance < amount:
        await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
        await state.clear()
        return
    
    # Списываем деньги с баланса
    db.add_dan(callback.from_user.id, -amount)
    
    # Создаем депозит
    username = getattr(callback.from_user, 'username', None) or "NoUsername"
    deposit_success = bank_system.add_deposit(
        callback.from_user.id, 
        username, 
        amount, 
        days, 
        rate_decimal
    )
    
    await state.clear()
    
    if deposit_success:
        profit = amount * rate_decimal
        total_return = amount + profit
        
        text = (
            f"✅ Депозит создан успешно!\n\n"
            f"💰 Сумма: {format_amount(amount)} дань\n"
            f"📅 Срок: {days} дней\n"
            f"📈 Ставка: {interest_rate}%\n"
            f"💵 Прибыль: {format_amount(profit)} дань\n"
            f"🎯 К получению: {format_amount(total_return)} дань\n\n"
            f"📋 Депозит добавлен в ваши акты."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 Вернуться в банк", callback_data=f"bank_back:{owner_user_id}")]
        ])
        
        await safe_edit_message(callback, text, keyboard)
        await callback.answer("🎉 Депозит создан!", show_alert=True)
    else:
        # Возвращаем деньги в случае ошибки
        db.add_dan(callback.from_user.id, amount)
        await callback.answer("❌ Ошибка создания депозита. Средства возвращены.", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("bank_quick_confirm:"))
async def bank_quick_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение создания депозита для быстрого выбора суммы"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, amount_str, days_str, rate_str, owner_user_id = callback.data.split(":")
        amount = float(amount_str)
        days = int(days_str)
        rate = int(rate_str)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Еще раз проверяем баланс
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    current_balance = float(user.get("dan", 0))
    if current_balance < amount:
        await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
        return
    
    # Вычисляем прибыль
    rate_decimal = rate / 100
    profit = amount * rate_decimal
    total_return = amount + profit
    
    # Показываем окончательное подтверждение
    text = (
        f"💳 Подтверждение депозита\n"
        f"-~-~-~-~-~-~-~-\n\n"
        f"💰 Сумма: {format_amount(amount)} дань\n"
        f"📅 Срок: {days} дней\n"
        f"📈 Ставка: {rate}%\n"
        f"💵 Прибыль: {format_amount(profit)} дань\n"
        f"🎯 К получению: {format_amount(total_return)} дань\n\n"
        f"❓ Создать депозит?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать депозит", callback_data=f"bank_final_confirm:{amount}:{days}:{rate}:{owner_user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"bank_cancel:{owner_user_id}")]
    ])
    
    await safe_edit_message(callback, text, keyboard)

@dp.callback_query(lambda c: c.data.startswith("bank_final_confirm:"))
async def bank_final_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Финальное создание депозита для быстрого потока"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        await callback.answer("Ошибка: данные недоступны", show_alert=True)
        return
    
    try:
        _, amount_str, days_str, rate_str, owner_user_id = callback.data.split(":")
        amount = float(amount_str)
        days = int(days_str)
        rate = int(rate_str)
        owner_user_id = int(owner_user_id)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных", show_alert=True)
        return
    
    if owner_user_id != callback.from_user.id:
        await callback.answer("Это не ваше меню!", show_alert=True)
        return
    
    # Финальная проверка баланса
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    current_balance = float(user.get("dan", 0))
    if current_balance < amount:
        await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
        return
    
    # Списываем деньги и создаем депозит
    db.add_dan(callback.from_user.id, -int(amount))
    
    username = getattr(callback.from_user, 'username', None) or "NoUsername"
    rate_decimal = rate / 100
    deposit_success = bank_system.add_deposit(
        callback.from_user.id, 
        username, 
        amount, 
        days, 
        rate_decimal
    )
    
    if deposit_success:
        profit = amount * rate_decimal
        total_return = amount + profit
        
        text = (
            f"✅ Депозит создан успешно!\n\n"
            f"💰 Сумма: {format_amount(amount)} дань\n"
            f"📅 Срок: {days} дней\n"
            f"📈 Ставка: {rate}%\n"
            f"💵 Прибыль: {format_amount(profit)} дань\n"
            f"🎯 К получению: {format_amount(total_return)} дань\n\n"
            f"📋 Депозит добавлен в ваши акты."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 Вернуться в банк", callback_data=f"bank_back:{owner_user_id}")],
            [InlineKeyboardButton(text="📋 Мои депозиты", callback_data=f"bank_my_deposits:{owner_user_id}")]
        ])
        
        await safe_edit_message(callback, text, keyboard)
        await callback.answer("🎉 Депозит создан!", show_alert=True)
    else:
        # Возвращаем деньги в случае ошибки
        db.add_dan(callback.from_user.id, int(amount))
        await callback.answer("❌ Ошибка создания депозита. Средства возвращены.", show_alert=True)

@dp.message(F.text.casefold() == "додеп")
async def cmd_dodep(message: types.Message):
    if not getattr(message, 'from_user', None):
        return
    user_id = message.from_user.id
    kb = InlineKeyboardBuilder()
    kb.button(text="FREE 99 Дань (раз в 7 дней)", callback_data="free_50")
    kb.button(text="500д/⭐️1", callback_data="buystars:1:500")
    kb.button(text="6к/10⭐️", callback_data="buystars:10:6000")
    kb.button(text="12к/18⭐️", callback_data="buystars:18:12000")
    kb.button(text="25к/34⭐️", callback_data="buystars:34:25000")
    kb.button(text="50к/62⭐️", callback_data="buystars:62:50000")
    kb.button(text="100к/112⭐️", callback_data="buystars:112:100000")
    kb.button(text="закрыть", callback_data="close_dodep")
    kb.adjust(1, 3, 2, 1, 1)
    await message.reply("Выберите вариант пополнения:", reply_markup=kb.as_markup())
# Команда /donat открывает меню додеп
@dp.message(Command("donat"))
async def cmd_donat(message: types.Message):
    await cmd_dodep(message)

@dp.message(Command("ticket"))
async def ticket_handler(message: types.Message):
    """Обработчик команды /ticket - система лотереи"""
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None) or "NoUsername"
    
    # Обеспечиваем пользователя в базе данных
    safe_ensure_user(user_id, username)
    
    # Получаем статистику билетов
    total_tickets_sold, total_tickets_value = get_total_tickets_info()
    user_tickets_count = get_user_tickets_count(user_id)
    
    # Получаем баланс пользователя
    user = db.get_user(user_id)
    dan_balance = float(user.get("dan", 0)) if user else 0
    
    # Вычисляем сколько дань потрачено на билеты сегодня
    spent_today = user_tickets_count * 100
    
    # Форматируем строку баланса
    if spent_today > 0:
        balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань (-{spent_today} дань потрачено сегодня)"
    else:
        balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань"
    
    # Вычисляем шанс на выигрыш
    win_chance = (user_tickets_count / total_tickets_sold * 100) if total_tickets_sold > 0 else 0
    
    # Получаем статичный дневной бонус
    preview_bonus = get_daily_lottery_bonus()
    
    text = (
        f"🎫 ЛОТЕРЕЯ 🎫\n\n"
        f"📊 Статистика:\n"
        f"🎟️ Сейчас куплено {total_tickets_sold} билетов, на {total_tickets_value:,.0f} дань\n\n"
        f"🎯 <b>Ваши шансы:</b>\n"
        f"📈 Шанс на выигрыш {win_chance:.1f}%\n"
        f"🎫 У вас {user_tickets_count} билетов (максимум 10)\n"
        f"🎁 Сегодня бонус +{preview_bonus:,} дань к ОБЩЕМУ призовому фонду!\n"
        f"{balance_text}\n\n"
        f"💰 Условия:\n"
        f"💵 Цена 1 билета: 100 дань\n"
        f"🕛 Ровно в 21:00 рандомно будет выбран победитель\n"
        f"🏆 Победитель получает ВСЕ деньги от билетов + бонус!"
    )
    
    # Построение текста/клавиатуры через глобальные helper-и
    text, keyboard = render_lottery_text(user_id)
    
    await message.answer(text, reply_markup=keyboard, parse_mode='HTML')

# Текстовые обработчики для лотереи
@dp.message(lambda message: message.text and message.text.lower().strip() in ["билет", "билеты", "ticket"])
async def text_ticket_handler(message: types.Message):
    """Обработчик текстового сообщения 'билет', 'билеты' или 'ticket'"""
    await ticket_handler(message)

# --- АРЕНА PvP ---

@dp.message(lambda message: message.text and message.text.lower().strip() in ["арена", "arena"])
async def arena_handler(message: types.Message):
    """Основное меню арены"""
    increment_games_count()
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None) or f"ID:{user_id}"
    safe_ensure_user(user_id, username)
    
    # Получаем рейтинг игрока
    rating_data = arena.get_arena_rating(user_id)
    
    # Определяем лигу
    rating = rating_data['rating']
    if rating < 1000:
        league = "🥉 Новичок"
    elif rating < 1500:
        league = "🥈 Боец"
    elif rating < 2000:
        league = "🥇 Воин"
    elif rating < 2500:
        league = "💎 Мастер"
    else:
        league = "👑 Легенда"
    
    text = f"🏟️ <b>АРЕНА KRUZCHAT</b> 🏟️\n\n"
    text += f"⚔️ <b>Тактические PvP бои!</b>\n"
    text += f"Сражайтесь в пошаговых боях, используя атаку, защиту и лечение. Каждое решение влияет на исход битвы!\n\n"
    text += f"🏆 <b>Ваш профиль:</b>\n"
    text += f"📊 Рейтинг: <b>{rating} PTS</b> ({league})\n"
    text += f"🏆 Побед: <b>{rating_data['wins']}</b>\n"
    text += f"💔 Поражений: <b>{rating_data['losses']}</b>\n"
    
    if rating_data['win_streak'] > 0:
        text += f"🔥 Серия побед: <b>{rating_data['win_streak']}</b>\n"
    
    text += f"\n🎯 <b>Как играть:</b>\n"
    text += f"• Каждый ход выбирайте действие\n"
    text += f"• ⚔️ <b>Атака</b>: наносит урон (15-25)\n"
    text += f"• 🛡️ <b>Защита</b>: дает броню и шанс уклонения\n"
    text += f"• 💚 <b>Лечение</b>: восстанавливает HP (5-10%)\n"
    text += f"• 💥 <b>Комбо</b>: 3 одинаковых действия = спецэффект!\n\n"
    text += f"⏱️ Время боя: 10 минут\n"
    text += f"❤️ HP: 100 | Критические удары: 15%"
    
    # Проверяем, не в очереди ли уже игрок
    in_queue = any(p['user_id'] == user_id for p in arena.arena_queue)
    in_game = any(game.fighter1.user_id == user_id or game.fighter2.user_id == user_id 
                  for game in arena.active_arenas.values() if game.is_active)
    
    keyboard = []
    
    if in_game:
        keyboard.append([InlineKeyboardButton(text="⚔️ Вернуться в бой", callback_data="arena_return_to_game")])
        keyboard.append([InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")])
    elif in_queue:
        keyboard.append([InlineKeyboardButton(text="⏳ Отменить поиск", callback_data="arena_cancel_search")])
        keyboard.append([InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot"),
            InlineKeyboardButton(text="🔍 Найти бой", callback_data="arena_find_match")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton(text="🎁 Забрать приз (скоро)", callback_data="arena_claim_level_reward")],
        [InlineKeyboardButton(text="📊 Рейтинг-таблица", callback_data="arena_leaderboard")],
        [InlineKeyboardButton(text="📋 Статистика", callback_data="arena_my_stats"), InlineKeyboardButton(text="❓ Справка", callback_data="arena_help")]
    ])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")

# Обработчики callback арены
@dp.callback_query(lambda c: c.data == "arena_find_match")
async def arena_find_match_callback(callback: types.CallbackQuery):
    """Начать поиск матча"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    username = getattr(callback.from_user, 'username', None) or f"ID:{user_id}"
    
    # Проверяем, не в игре ли уже
    in_game = any(game.fighter1.user_id == user_id or game.fighter2.user_id == user_id 
                  for game in arena.active_arenas.values() if game.is_active)
    
    if in_game:
        await callback.answer("❌ Вы уже в игре!", show_alert=True)
        return
    
    # Добавляем в очередь
    if arena.add_to_arena_queue(user_id, username, 0):  # Пока без ставок
        # Пытаемся найти противника
        opponent = arena.find_arena_opponent(user_id)
        
        if opponent:
            # Создаем игру
            player1_data = {'user_id': user_id, 'username': username}
            player2_data = {'user_id': opponent['user_id'], 'username': opponent['username']}
            
            game_id = arena.create_arena_game(player1_data, player2_data, 0)
            game = arena.get_arena_game(game_id)
            
            # ВАЖНО: Сохраняем информацию о чате для результата
            if callback.message and callback.message.chat:
                game.source_chat_id = callback.message.chat.id
                game.source_message_id = callback.message.message_id
            
            # Уведомляем в чате что бой начался
            await safe_edit_text_or_caption(
                callback.message, 
                f"⚔️ <b>БОЙ НАЧАЛСЯ!</b>\n\n👤 {username} VS 👤 {opponent['username']}\n\n🔄 Бой проходит в личных сообщениях игроков\n📢 Результат будет показан здесь", 
                reply_markup=None, 
                parse_mode="HTML"
            )
            
            # Отправляем интерфейс игры в ЛС каждому игроку
            for fighter in [game.fighter1, game.fighter2]:
                try:
                    text = game.get_arena_display(fighter.user_id)
                    keyboard = game.get_keyboard(fighter.user_id)
                    
                    # Отправляем в ЛС игрока
                    msg = await bot.send_message(
                        chat_id=fighter.user_id,
                        text=f"⚔️ <b>АРЕНА - БОЙ НАЧАЛСЯ!</b>\n\n{text}",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    
                    # Сохраняем ID сообщения для обновлений
                    game.message_ids[fighter.user_id] = msg.message_id
                    
                except Exception as e:
                    print(f"Ошибка отправки сообщения в ЛС игроку {fighter.user_id}: {e}")
                    # Если не удалось отправить в ЛС - уведомляем игрока
                    try:
                        await bot.send_message(
                            chat_id=fighter.user_id,
                            text="❌ Не удалось начать бой. Убедитесь что у бота есть доступ к личным сообщениям!"
                        )
                    except:
                        pass
            
            await callback.answer("⚔️ Противник найден! Проверьте ЛС для боя!")
        else:
            # Показываем экран поиска
            text = "🔍 <b>ПОИСК ПРОТИВНИКА</b>\n\n"
            text += "⏳ Ищем достойного соперника...\n"
            text += f"🎯 Ваш рейтинг: {arena.get_arena_rating(user_id)['rating']} PTS\n\n"
            text += "⚡ Поиск может занять до 30 минут\n"
            text += "🤖 После этого начнется бой с ботом"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="arena_cancel_search")]
            ])
            
            await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer("🔍 Поиск начат!")
    else:
        await callback.answer("❌ Вы уже в очереди!", show_alert=True)

@dp.callback_query(lambda c: c.data == "arena_cancel_search")
async def arena_cancel_search_callback(callback: types.CallbackQuery):
    """Отменить поиск"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    
    if arena.remove_from_arena_queue(user_id):
        # Сразу возвращаем в меню арены
        username = getattr(callback.from_user, 'username', None) or f"ID:{user_id}"
        safe_ensure_user(user_id, username)
        
        # Получаем рейтинг игрока
        rating_data = arena.get_arena_rating(user_id)
        
        # Определяем лигу
        rating = rating_data['rating']
        if rating < 1000:
            league = "🥉 Новичок"
        elif rating < 1500:
            league = "🥈 Боец"
        elif rating < 2000:
            league = "🥇 Воин"
        elif rating < 2500:
            league = "💎 Мастер"
        else:
            league = "👑 Легенда"

        text = f"🏟️ <b>АРЕНА KRUZCHAT</b> 🏟️\n\n"
        text += f"⚔️ <b>Тактические PvP бои!</b>\n"
        text += f"Сражайтесь в пошаговых боях, используя атаку, защиту и лечение. Каждое решение влияет на исход битвы!\n\n"
        text += f"🏆 <b>Ваш профиль:</b>\n"
        text += f"📊 Рейтинг: <b>{rating} PTS</b> ({league})\n"
        text += f"🏆 Побед: <b>{rating_data['wins']}</b>\n"
        text += f"💔 Поражений: <b>{rating_data['losses']}</b>\n"
        
        if rating_data['win_streak'] > 0:
            text += f"🔥 Серия побед: <b>{rating_data['win_streak']}</b>\n"
        
        text += f"\n🎯 <b>Как играть:</b>\n"
        text += f"• Каждый ход выбирайте действие\n"
        text += f"• ⚔️ <b>Атака</b>: наносит урон (15-25)\n"
        text += f"• 🛡️ <b>Защита</b>: дает броню и шанс уклонения\n"
        text += f"• 💚 <b>Лечение</b>: восстанавливает HP (5-10%)\n"
        text += f"• 💥 <b>Комбо</b>: 3 одинаковых действия = спецэффект!\n\n"
        text += f"⏱️ Время боя: 10 минут\n"
        text += f"❤️ HP: 100 | Критические удары: 15%"
        
        keyboard = []
        
        # Проверяем, не в игре ли уже
        in_game = any(game.fighter1.user_id == user_id or game.fighter2.user_id == user_id 
                      for game in arena.active_arenas.values() if game.is_active)
        
        if in_game:
            keyboard.append([InlineKeyboardButton(text="⚔️ Вернуться к бою", callback_data="arena_return_to_game")])
            keyboard.append([InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")])
        else:
            keyboard.append([
                InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot"),
                InlineKeyboardButton(text="🔍 Найти бой", callback_data="arena_find_match")
            ])
        
        keyboard.extend([
            [InlineKeyboardButton(text="📊 Рейтинг-таблица", callback_data="arena_leaderboard")],
            [InlineKeyboardButton(text="📋 Статистика", callback_data="arena_my_stats"), InlineKeyboardButton(text="❓ Справка", callback_data="arena_help")]
        ])
        
        await safe_edit_text_or_caption(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
        await callback.answer("❌ Поиск отменен")
    else:
        try:
            await callback.answer("❌ Вы не в очереди", show_alert=True)
        except Exception:
            pass  # Игнорируем устаревшие callback'и

@dp.callback_query(lambda c: c.data.startswith("arena_action:"))
async def arena_action_callback(callback: types.CallbackQuery):
    """Обработка действий в арене"""
    if not getattr(callback, 'from_user', None):
        return
    
    parts = callback.data.split(":")
    game_id = parts[1]
    action = parts[2]
    user_id = callback.from_user.id
    
    print(f"🎮 Arena action: user={user_id}, game={game_id}, action={action}")
    
    success, result = arena.process_arena_action(game_id, user_id, action)
    
    if not success:
        await callback.answer(f"❌ {result}", show_alert=True)
        return
    
    game = arena.get_arena_game(game_id)
    if not game:
        await callback.answer("❌ Игра не найдена", show_alert=True)
        return
    
    # Сохраняем message_id для дальнейших обновлений
    if callback.message and callback.message.message_id:
        game.message_ids[user_id] = callback.message.message_id
    
    # Сразу обновляем интерфейс с новым статусом
    text = game.get_arena_display(user_id)
    keyboard = game.get_keyboard(user_id)
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    
    print(f"🎮 Проверяем готовность игроков: {game.both_players_ready()}")
    
    # Проверяем есть ли бот в игре и нужно ли его запустить
    opponent = game.get_opponent(user_id)
    if opponent:
        print(f"🎮 Противник найден: ID={opponent.user_id}, username={opponent.username}")
        if opponent.user_id < 0:  # Это бот
            # Если бот еще не выбрал действие - запускаем его ИИ
            if game.waiting_for.get(opponent.user_id) is None:
                print(f"🎮 Запускаем ИИ бота {opponent.user_id} для игры {game_id}")
                asyncio.create_task(arena.bot_arena_ai(game_id, opponent.user_id))
            else:
                print(f"🎮 Бот {opponent.user_id} уже выбрал действие")
        else:
            print(f"🎮 Противник это игрок (ID={opponent.user_id}), не бот")
    else:
        print(f"🎮 Противник не найден")
    
    # Если оба игрока выбрали действие - мгновенно обрабатываем раунд  
    if game.both_players_ready():
        print(f"🎮 Оба игрока готовы в игре {game_id}, обрабатываем раунд")
        # Небольшая пауза чтобы игрок увидел выборы
        await asyncio.sleep(1)
        
        round_result, game_ended = game.process_round()
        if game_ended:
            game.is_active = False
            result_data = arena.end_arena_game(game_id)
            if result_data:
                await send_arena_game_result(result_data)
        else:
            # Обновляем интерфейс у ОБОИХ игроков после раунда
            for fighter in [game.fighter1, game.fighter2]:
                if fighter and fighter.user_id in game.message_ids:
                    try:
                        text = game.get_arena_display(fighter.user_id)
                        keyboard = game.get_keyboard(fighter.user_id)
                        
                        await bot.edit_message_text(
                            chat_id=fighter.user_id,
                            message_id=game.message_ids[fighter.user_id],
                            text=text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        print(f"🎮 Интерфейс обновлен для игрока {fighter.user_id}")
                    except Exception as e:
                        print(f"🎮 Ошибка обновления интерфейса для игрока {fighter.user_id}: {e}")
            
            # После раунда снова проверяем нужно ли запустить бота
            if opponent and opponent.user_id < 0 and game.waiting_for.get(opponent.user_id) is None:
                asyncio.create_task(arena.bot_arena_ai(game_id, opponent.user_id))
    
    try:
        await callback.answer()
    except Exception:
        pass  # Игнорируем устаревшие callback'и

async def send_arena_game_result(result_data):
    """Отправить результат игры в арену - в ЛС и в исходный чат"""
    game = result_data['game']
    
    # Удаляем интерфейс игры у обоих игроков
    for fighter in [game.fighter1, game.fighter2]:
        if fighter and fighter.user_id in game.message_ids:
            try:
                await bot.delete_message(
                    chat_id=fighter.user_id,
                    message_id=game.message_ids[fighter.user_id]
                )
                print(f"✅ Удалено сообщение с интерфейсом арены у игрока {fighter.user_id}")
            except Exception as e:
                print(f"❌ Не удалось удалить сообщение у игрока {fighter.user_id}: {e}")
    
    if result_data['is_draw']:
        # Текст для ЛС игроков
        result_text_dm = f"🤝 <b>НИЧЬЯ В АРЕНЕ!</b>\n\n"
        result_text_dm += f"👤 {game.fighter1.username}: {game.fighter1.get_hp_bar()}\n"
        result_text_dm += f"👤 {game.fighter2.username}: {game.fighter2.get_hp_bar()}\n\n"
        result_text_dm += f"⏰ Время истекло! Бой завершен ничьей.\n"
        result_text_dm += f"🏆 Рейтинг игроков не изменился"
        
        # Отправляем в ЛС каждому игроку
        for fighter in [game.fighter1, game.fighter2]:
            try:
                await bot.send_message(
                    chat_id=fighter.user_id,
                    text=result_text_dm,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка отправки результата игроку {fighter.user_id}: {e}")
        
        # Текст для исходного чата
        chat_result_text = f"🤝 <b>НИЧЬЯ В АРЕНЕ!</b>\n\n👤 {game.fighter1.username} VS 👤 {game.fighter2.username}\n\n⏰ Время истекло!"
        
    else:
        winner = result_data['winner']
        loser = result_data['loser']
        winner_pts = result_data['winner_pts']
        loser_pts = result_data['loser_pts']
        
        # Отслеживаем победу для заданий (проверяем, что оба игрока - люди)
        is_pvp = winner.user_id > 0 and loser.user_id > 0
        if winner.user_id > 0:
            try:
                _tasks.record_arena_win(winner.user_id, vs_real=is_pvp)
            except Exception as e:
                print(f"❌ Ошибка записи победы в арене для {winner.user_id}: {e}")
        
        # Текст для ЛС победителя
        winner_text = f"🏆 <b>ПОБЕДА В АРЕНЕ!</b>\n\n"
        winner_text += f"⚔️ Вы победили {loser.username}!\n\n"
        winner_text += f"📊 <b>Результат боя:</b>\n"
        winner_text += f"🟢 Вы: {winner.get_hp_bar()}\n"
        winner_text += f"🔴 Противник: {loser.get_hp_bar()}\n\n"
        winner_text += f"🏆 <b>Рейтинг:</b> +{winner_pts} PTS\n"
        
        # Начисляем опыт за победу (ежедневный бонус 1 раз в день)
        try:
            from arena_database import register_win_xp as _arena_win_xp
            xp_info = _arena_win_xp(winner.user_id)
            winner_text += f"📘 <b>Опыт:</b> +{xp_info['xp_gain']} XP\n"
            winner_text += f"🎚️ <b>Уровень:</b> {xp_info['level']} | Прогресс: {xp_info['xp']}/5000\n"
            if xp_info.get('leveled_up'):
                winner_text += "🎉 <b>Уровень повышен!</b> Доступна награда в меню арены.\n"
        except Exception as e:
            print(f"⚠️ Ошибка начисления опыта в арене: {e}")
        
        # Текст для ЛС проигравшего
        loser_text = f"💔 <b>ПОРАЖЕНИЕ В АРЕНЕ</b>\n\n"
        loser_text += f"⚔️ Вы проиграли {winner.username}\n\n"
        loser_text += f"📊 <b>Результат боя:</b>\n"
        loser_text += f"🔴 Вы: {loser.get_hp_bar()}\n"
        loser_text += f"🟢 Противник: {winner.get_hp_bar()}\n\n"
        loser_text += f"📉 <b>Рейтинг:</b> {loser_pts} PTS\n"
        loser_text += f"💪 Не сдавайтесь! Реванш всегда возможен!"
        
        # Кнопка возврата в меню арены
        arena_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать приз (скоро)", callback_data="arena_claim_level_reward")],
            [InlineKeyboardButton(text="⬅️ В меню арены", callback_data="arena_back_to_menu")]
        ])
        
        # Отправляем в ЛС игрокам
        try:
            await bot.send_message(
                chat_id=winner.user_id,
                text=winner_text,
                reply_markup=arena_keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки результата победителю {winner.user_id}: {e}")
            
        try:
            await bot.send_message(
                chat_id=loser.user_id,
                text=loser_text,
                reply_markup=arena_keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки результата проигравшему {loser.user_id}: {e}")
        
        # Текст для исходного чата
        chat_result_text = f"🏆 <b>ПОБЕДА В АРЕНЕ!</b>\n\n👤 **{winner.username}** победил 👤 {loser.username}\n\n🎉 Поздравляем победителя!"
    
    # Отправляем результат в исходный чат (если есть информация о нем)
    if hasattr(game, 'source_chat_id') and game.source_chat_id and hasattr(game, 'source_message_id') and game.source_message_id:
        try:
            await bot.edit_message_text(
                chat_id=game.source_chat_id,
                message_id=game.source_message_id,
                text=chat_result_text,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки результата в исходный чат {game.source_chat_id}: {e}")
            # Если не удалось отредактировать, отправляем новое сообщение
            try:
                await bot.send_message(
                    chat_id=game.source_chat_id,
                    text=chat_result_text,
                    parse_mode="HTML"
                )
            except Exception as e2:
                print(f"Ошибка отправки нового сообщения в чат {game.source_chat_id}: {e2}")

@dp.callback_query(lambda c: c.data == "arena_leaderboard")
async def arena_leaderboard_callback(callback: types.CallbackQuery):
    """Показать таблицу лидеров"""
    leaderboard = arena.get_arena_leaderboard(10)
    
    text = "🏆 <b>ТОП-10 АРЕНЫ</b>\n\n"
    
    for entry in leaderboard:
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry['rank'], f"{entry['rank']}.")
        
        # Определяем лигу
        rating = entry['rating']
        if rating < 1000:
            league = "🥉"
        elif rating < 1500:
            league = "🥈"
        elif rating < 2000:
            league = "🥇"
        elif rating < 2500:
            league = "💎"
        else:
            league = "👑"
        
        # Получаем отображаемое имя с учетом новой системы
        user_id = entry.get('user_id', 0)
        
        # Используем новую систему отображения имен с приватностью
        display_name = get_display_name(user_id, entry.get('username'))
        clickable_name = format_clickable_name(user_id, display_name)
        text += f"{rank_emoji} {league} {clickable_name}\n"
        text += f"📊 {entry['rating']} PTS | 🏆{entry['wins']}-💔{entry['losses']}"
        
        if entry['win_streak'] > 0:
            text += f" | 🔥{entry['win_streak']}"
        
        text += "\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать приз (скоро)", callback_data="arena_claim_level_reward")],
        [InlineKeyboardButton(text="⬅️ В меню арены", callback_data="arena_back_to_menu")]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# Временное хранилище для сгенерированных наград (user_id: [item1, item2, item3]) # ГЕНЕРАЦИЯ ПРИЗОВ
pending_level_rewards_choices = {}

def generate_level_reward_image(user_id: int, items: list) -> str:
    """Генерирует изображение с тремя призами для выбора"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import os
        
        print(f"🔧 [DEBUG] Генерация изображения для user_id={user_id}, items={items}")
        
        base_path = "C:/BotKruz/ChatBotKruz/photo/ItemWin.jpg"
        out_path = f"C:/BotKruz/ChatBotKruz/cache/reward_{user_id}.png"
        
        print(f"🔧 [DEBUG] Базовое изображение: {base_path}, существует: {os.path.exists(base_path)}")
        
        # Открываем базовое изображение
        img = Image.open(base_path).convert("RGBA")
        print(f"🔧 [DEBUG] Базовое изображение открыто, размер: {img.size}")
        width, height = img.size  # 498x233
        
        # Размеры и позиции для 3 слотов (черные квадраты на ItemWin.jpg)
        slot_size = 130  # Увеличенный размер изображения в слоте
        slot_width = 140  # Ширина черного квадрата
        slot_y = 18  # Вертикальная позиция от верха (выше на 12)
        
        # Позиции 3 черных квадратов (координаты левого верхнего угла квадрата)
        slot_positions = [
            (19, slot_y),           # Слот 1 (левый, идеально)
            (181, slot_y),          # Слот 2 (центральный, на 1 пиксель влево)
            (351, slot_y)           # Слот 3 (правый, +3 вправо)
        ]
        
        # Отрисовываем каждый приз
        for i, item in enumerate(items[:3]):
            if i >= len(slot_positions):
                break
            
            x, y = slot_positions[i]
            reward_type = item.get('reward_type', 'currency')
            reward_id = item.get('reward_id', 'dan')
            
            # Определяем путь к изображению награды
            item_image_path = None
            
            if reward_type == 'currency':
                if reward_id == 'dan':
                    item_image_path = "C:/BotKruz/ChatBotKruz/photo/dan_get.png"
                elif reward_id == 'pts':
                    item_image_path = "C:/BotKruz/ChatBotKruz/photo/pts_get.png"
            elif reward_type == 'item':
                # Маппинг item_id на изображения
                item_mappings = {
                    'case_1': "C:/BotKruz/ChatBotKruz/photo/inv/03.jpg",
                    'case_2': "C:/BotKruz/ChatBotKruz/photo/inv/02.jpg",
                    'case_3': "C:/BotKruz/ChatBotKruz/photo/inv/01.jpg",
                    'пшеница': "C:/BotKruz/ChatBotKruz/photo/inv/bone.jpg",
                    'кукурудза': "C:/BotKruz/ChatBotKruz/photo/inv/meat.jpg",
                    'СкладБесконечный': "C:/BotKruz/ChatBotKruz/photo/inv/05.jpg",
                }
                item_image_path = item_mappings.get(reward_id, f"C:/BotKruz/ChatBotKruz/photo/inv/{reward_id}.png")
            elif reward_type == 'special':
                item_image_path = f"C:/BotKruz/ChatBotKruz/photo/inv/{reward_id}.png"
            
            # Если изображение существует, накладываем его
            if item_image_path and os.path.exists(item_image_path):
                print(f"🔧 [DEBUG] Слот {i+1}: Загрузка изображения {item_image_path}")
                try:
                    item_img = Image.open(item_image_path).convert("RGBA")
                    
                    # Масштабируем изображение до увеличенного размера
                    item_img.thumbnail((slot_size, slot_size), Image.Resampling.LANCZOS)
                    
                    # Центрируем изображение внутри черного квадрата
                    paste_x = x + (slot_width - item_img.width) // 2
                    paste_y = y + (slot_width - item_img.height) // 2
                    
                    print(f"🔧 [DEBUG] Слот {i+1}: Вставка изображения в позицию ({paste_x}, {paste_y}), размер: {item_img.size}")
                    
                    # Накладываем на базу
                    img.paste(item_img, (paste_x, paste_y), item_img)
                    item_img.close()
                except Exception as e:
                    print(f"⚠️ Ошибка загрузки изображения {item_image_path}: {e}")
        
        img.save(out_path, "PNG")
        img.close()
        print(f"✅ [DEBUG] Изображение сохранено: {out_path}, существует: {os.path.exists(out_path)}")
        return out_path
    except Exception as e:
        print(f"⚠️ Ошибка генерации изображения наград: {e}")
        import traceback
        traceback.print_exc()
        # Если ошибка, возвращаем базовое изображение
        return "C:/BotKruz/ChatBotKruz/photo/ItemWin.jpg"

def generate_random_rewards() -> list:
    """Генерирует 3 случайных награды из базы данных"""
    # Получаем уровень пользователя (пока используем 1, можно передавать параметром)
    user_level = 1
    try:
        rewards = generate_random_level_rewards(user_level, count=3)
        return rewards
    except Exception as e:
        print(f"⚠️ Ошибка генерации наград: {e}")
        # Заглушка на случай ошибки
        return [
            {"reward_type": "currency", "reward_id": "dan", "reward_amount": 1000, "reward_name": "Дань"},
            {"reward_type": "currency", "reward_id": "dan", "reward_amount": 2000, "reward_name": "Дань"},
            {"reward_type": "currency", "reward_id": "dan", "reward_amount": 5000, "reward_name": "Дань"}
        ]

@dp.callback_query(lambda c: c.data and c.data.startswith("arena_claim_level_reward:"))
async def arena_claim_level_reward_callback(callback: types.CallbackQuery):
    """Показывает выбор награды за уровень"""
    try:
        user_id = int(callback.data.split(":")[1])
        
        print(f"🎁 [DEBUG] arena_claim_level_reward_callback вызван для user_id={user_id}")
        
        # Проверяем наличие наград
        xp_data = get_user_xp_data(user_id)
        pending_rewards = xp_data.get('pending_level_rewards', 0)
        user_level = xp_data.get('level', 1)
        
        print(f"🎁 [DEBUG] XP данные: level={user_level}, pending_rewards={pending_rewards}")
        
        if pending_rewards <= 0:
            await callback.answer("У вас нет наград для получения!", show_alert=True)
            return
        
        # Генерируем 3 случайных награды на основе уровня игрока
        rewards = generate_random_level_rewards(user_level, count=3)
        pending_level_rewards_choices[user_id] = rewards
        
        print(f"🎁 [DEBUG] Сгенерированы награды: {rewards}")
        
        # Создаем изображение
        image_path = generate_level_reward_image(user_id, rewards)
        
        print(f"🎁 [DEBUG] Путь к сгенерированному изображению: {image_path}")
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"arena_select_reward:0:{user_id}"),
                InlineKeyboardButton(text="2", callback_data=f"arena_select_reward:1:{user_id}"),
                InlineKeyboardButton(text="3", callback_data=f"arena_select_reward:2:{user_id}")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")
            ]
        ])
        
        # Отправляем сообщение с выбором
        caption = f"🎁 Награда за повышение уровня!\n\nВыберите один из трёх призов:"
        
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=FSInputFile(image_path), caption=caption),
                reply_markup=keyboard
            )
        except Exception:
            await callback.message.answer_photo(
                photo=FSInputFile(image_path),
                caption=caption,
                reply_markup=keyboard
            )
        
        await callback.answer()
        
    except Exception as e:
        await callback.answer("Произошла ошибка при получении награды", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("arena_select_reward:"))
async def arena_select_reward_callback(callback: types.CallbackQuery):
    """Обрабатывает выбор конкретной награды"""
    try:
        parts = callback.data.split(":")
        choice = parts[1]  # "0", "1", "2" или "random"
        user_id = int(parts[2])
        
        # Проверяем, что выбор делает тот же пользователь
        if callback.from_user.id != user_id:
            await callback.answer("Это не ваша награда!", show_alert=True)
            return
        
        # Проверяем наличие сохраненных наград
        if user_id not in pending_level_rewards_choices:
            await callback.answer("Награды не найдены. Попробуйте снова.", show_alert=True)
            return
        
        rewards = pending_level_rewards_choices[user_id]
        
        # Выбираем награду
        if choice == "random":
            import random
            selected_reward = random.choice(rewards)
            choice_text = "🎲 рандомный выбор"
        else:
            idx = int(choice)
            selected_reward = rewards[idx]
            choice_text = f"#{idx + 1}"
        
        # Выдаем награду в зависимости от типа
        reward_text = f"Вы получили: {selected_reward['reward_name']}"
        
        if selected_reward['reward_type'] == 'currency':
            # Выдаем валюту
            amount = selected_reward['reward_amount']
            currency_id = selected_reward['reward_id']
            
            if currency_id == 'dan':
                add_dan(user_id, amount)
                reward_text = f"🪙 Дань x{amount}"
            elif currency_id == 'kruz':
                add_kruz(user_id, amount)
                reward_text = f"⭐ Stars x{amount}"
            elif currency_id == 'pts':
                # Добавляем PTS в арену
                try:
                    import arena_database
                    current_rating = arena_database.get_player_rating(user_id)
                    new_rating = current_rating['rating'] + amount
                    arena_database.update_player_rating(user_id, new_rating)
                    reward_text = f"🏆 PTS x{amount}"
                except Exception as e:
                    print(f"⚠️ Ошибка добавления PTS: {e}")
                    reward_text = f"🏆 PTS x{amount} (ошибка)"
            
        elif selected_reward['reward_type'] == 'item':
            # Выдаем предмет в инвентарь
            item_id = selected_reward['reward_id']
            amount = selected_reward['reward_amount']
            
            try:
                from inv_py.inventory import add_item_to_json_db
                add_item_to_json_db(item_id, amount)
                reward_text = f"📦 {selected_reward['reward_name']} x{amount}"
            except Exception as e:
                print(f"⚠️ Ошибка выдачи предмета {item_id}: {e}")
                reward_text = f"📦 {selected_reward['reward_name']} x{amount} (ошибка)"
                
        elif selected_reward['reward_type'] == 'special':
            # Специальные награды (бесконечная ферма и т.д.)
            special_id = selected_reward['reward_id']
            
            if special_id == 'infinite_farm':
                # Здесь будет код для бесконечной фермы
                reward_text = f"🌟 {selected_reward['reward_name']} (скоро)"
            else:
                reward_text = f"✨ {selected_reward['reward_name']}"
        
        # Уменьшаем счетчик наград в БД (используем основную БД, не арену)
        claim_level_reward(user_id)
        
        # Удаляем из временного хранилища
        del pending_level_rewards_choices[user_id]
        
        # Показываем результат и возвращаем в главное меню
        await callback.answer(f"✅ {reward_text}", show_alert=True)
        await show_main_menu(callback, user_id)
        
    except Exception as e:
        await callback.answer("Произошла ошибка при выборе награды", show_alert=True)

@dp.callback_query(lambda c: c.data == "arena_return_to_game")
async def arena_return_to_game_callback(callback: types.CallbackQuery):
    """Вернуться в активный бой"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    
    # Ищем активную игру пользователя
    user_game = None
    for game in arena.active_arenas.values():
        if game.is_active and (game.fighter1.user_id == user_id or game.fighter2.user_id == user_id):
            user_game = game
            break
    
    if not user_game:
        await callback.answer("❌ Активная игра не найдена", show_alert=True)
        return
    
    # Отправляем текущее состояние игры в ЛС
    try:
        text = user_game.get_arena_display(user_id)
        keyboard = user_game.get_keyboard(user_id)
        
        msg = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Обновляем ID сообщения
        user_game.message_ids[user_id] = msg.message_id
        
        await callback.answer("⚔️ Возвращаемся в бой!")
        
    except Exception as e:
        print(f"Ошибка возврата в игру: {e}")
        await callback.answer("❌ Ошибка возврата в игру", show_alert=True)

@dp.callback_query(lambda c: c.data == "arena_back_to_menu")
async def arena_back_to_menu_callback(callback: types.CallbackQuery):
    """Вернуться в меню арены"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    
    # Получаем рейтинг игрока  
    rating_data = arena.get_arena_rating(user_id)
    
    # Определяем лигу
    rating = rating_data['rating']
    if rating < 1000:
        league = "🥉 Новичок"
    elif rating < 1500:
        league = "🥈 Боец"
    elif rating < 2000:
        league = "🥇 Воин"
    elif rating < 2500:
        league = "💎 Мастер"
    else:
        league = "👑 Легенда"

    # Создаем меню арены (заменяем текущее сообщение)
    text = f"🏟️ <b>АРЕНА KRUZCHAT</b> 🏟️\n\n"
    text += f"⚔️ <b>Тактические PvP бои!</b>\n"
    text += f"Сражайтесь в пошаговых боях, используя атаку, защиту и лечение. Каждое решение влияет на исход битвы!\n\n"
    text += f"🏆 <b>Ваш профиль:</b>\n"
    text += f"📊 Рейтинг: <b>{rating} PTS</b> ({league})\n"
    text += f"🏆 Побед: <b>{rating_data['wins']}</b>\n"
    text += f"💔 Поражений: <b>{rating_data['losses']}</b>\n"
    
    if rating_data['win_streak'] > 0:
        text += f"🔥 Серия побед: <b>{rating_data['win_streak']}</b>\n"
    
    text += f"\n🎯 <b>Как играть:</b>\n"
    text += f"• Каждый ход выбирайте действие\n"
    text += f"• ⚔️ <b>Атака</b>: наносит урон (15-25)\n"
    text += f"• 🛡️ <b>Защита</b>: дает броню и шанс уклонения\n"
    text += f"• 💚 <b>Лечение</b>: восстанавливает HP (5-10%)\n"
    text += f"• 💥 <b>Комбо</b>: 3 одинаковых действия = спецэффект!\n\n"
    text += f"⏱️ Время боя: 10 минут\n"
    text += f"❤️ HP: 100 | Критические удары: 15%"
    
    keyboard = []
    
    # Проверяем, не в игре ли уже
    in_game = any(game.fighter1.user_id == user_id or game.fighter2.user_id == user_id 
                  for game in arena.active_arenas.values() if game.is_active)
    
    if in_game:
        keyboard.append([InlineKeyboardButton(text="⚔️ Вернуться к бою", callback_data="arena_return_to_game")])
        keyboard.append([InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot"),
            InlineKeyboardButton(text="🔍 Найти бой", callback_data="arena_find_match")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton(text="📊 Рейтинг-таблица", callback_data="arena_leaderboard")],
        [InlineKeyboardButton(text="📋 Статистика", callback_data="arena_my_stats"), InlineKeyboardButton(text="❓ Справка", callback_data="arena_help")]
    ])
    
    # Заменяем текущее сообщение на меню арены
    await safe_edit_text_or_caption(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    
    try:
        await callback.answer()
    except Exception:
        pass

@dp.callback_query(lambda c: c.data == "arena_my_stats")
async def arena_my_stats_callback(callback: types.CallbackQuery):
    """Показать статистику игрока в арене"""
    if not getattr(callback, 'from_user', None):
        return
    
    user_id = callback.from_user.id
    username = getattr(callback.from_user, 'username', None) or f"ID:{user_id}"
    safe_ensure_user(user_id, username)
    
    # Получаем статистику игрока
    rating_data = arena.get_arena_rating(user_id)
    player_rank = arena.get_player_rank(user_id)
    
    # Определяем лигу
    rating = rating_data['rating']
    if rating < 1000:
        league = "🥉 Новичок"
    elif rating < 1500:
        league = "🥈 Боец"
    elif rating < 2000:
        league = "🥇 Воин"
    elif rating < 2500:
        league = "💎 Мастер"
    else:
        league = "👑 Легенда"
    
    # Получаем отображаемое имя с учетом новой системы
    display_name = get_display_name(user_id, username)
    clickable_name = format_clickable_name(user_id, display_name)
    
    text = f"📊 <b>СТАТИСТИКА АРЕНЫ</b>\n\n"
    text += f"👤 <b>Игрок:</b> {clickable_name}\n"
    text += f"🏆 <b>Рейтинг:</b> {rating} PTS\n"
    text += f"🎯 <b>Лига:</b> {league}\n"
    text += f"📈 <b>Место:</b> #{player_rank}\n\n"
    
    text += f"📈 <b>Результаты:</b>\n"
    text += f"🟢 Побед: <b>{rating_data['wins']}</b>\n"
    text += f"🔴 Поражений: <b>{rating_data['losses']}</b>\n"
    try:
        level = rating_data.get('level', 1)
        xp = rating_data.get('xp', 0)
        text += f"🎚️ Уровень: <b>{level}</b>\n"
        text += f"📘 Опыт: <b>{xp}/5000</b>\n"
    except Exception:
        pass
    
    if rating_data['wins'] + rating_data['losses'] > 0:
        winrate = (rating_data['wins'] / (rating_data['wins'] + rating_data['losses'])) * 100
        text += f"📊 Винрейт: <b>{winrate:.1f}%</b>\n"
    
    if rating_data['win_streak'] > 0:
        text += f"🔥 <b>Текущая серия:</b> {rating_data['win_streak']} побед\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню арены", callback_data="arena_back_to_menu")]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "arena_help")
async def arena_help_callback(callback: types.CallbackQuery):
    """Показать справку по арене"""
    if not getattr(callback, 'from_user', None):
        return
    
    text = f"❓ <b>СПРАВКА ПО АРЕНЕ</b>\n\n"
    text += f"🏟️ <b>Как играть:</b>\n"
    text += f"• Каждый ход выбирайте одно из трех действий\n"
    text += f"• ⚔️ <b>Атака</b>: наносит 15-30 урона\n"
    text += f"• 🛡️ <b>Защита</b>: блокирует 75%/50% урона\n"
    text += f"• 💚 <b>Лечение</b>: восстанавливает 10-20 HP\n\n"
    
    text += f"💥 <b>Система комбо:</b>\n"
    text += f"• Используйте 3 одинаковых действия подряд\n"
    text += f"• ⚔️⚔️⚔️ = <b>БЕРСЕРК</b>: +50% урон + кровотечение\n"
    text += f"• 💚💚💚 = <b>МОЩ.ИСЦЕЛЕНИЕ</b>: 25-35 HP + регенерация\n\n"
    
    text += f"🎯 <b>Статусные эффекты:</b>\n"
    text += f"🩸 <b>Кровотечение</b>: -3 HP в начале хода\n"
    text += f"💚 <b>Регенерация</b>: +5 HP в начале хода\n\n"
    
    text += f"🏆 <b>Рейтинговая система:</b>\n"
    text += f"• Победа: +10-50 очков (зависит от противника)\n"
    text += f"• Поражение: -5-25 очков\n"
    text += f"• Лиги: Новичок → Боец → Воин → Мастер → Легенда\n\n"
    
    text += f"⏱️ <b>Прочее:</b>\n"
    text += f"• Время боя: 10 минут\n"
    text += f"• Максимум раундов: 15\n"
    text += f"• HP: 100 для всех\n"
    text += f"• Критические удары: 15% шанс"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню арены", callback_data="arena_back_to_menu")]
    ])
    
    await safe_edit_text_or_caption(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# --- КОМАНДА /ИМЯ ---

@dp.message(Command("имя"))
async def cmd_set_name(message: types.Message):
    """Команда для установки кастомного имени"""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    text_parts = message.text.split(maxsplit=1) # pyright: ignore[reportOptionalMemberAccess]
    
    if len(text_parts) < 2:
        # Показываем текущее имя и инструкцию
        current_name = get_display_name(message.from_user)
        custom_name = get_custom_name(user_id)
        
        text = f"👤 <b>НАСТРОЙКА ИМЕНИ</b>\n\n"
        text += f"🔸 <b>Текущее отображение:</b> {current_name}\n"
        
        if custom_name:
            text += f"✨ <b>Кастомное имя:</b> {custom_name}\n"
        else:
            text += f"📝 <b>Кастомное имя:</b> не установлено\n"
        
        text += f"\n💡 <b>Как использовать:</b>\n"
        text += f"<code>/имя Новое Имя</code> - установить имя\n"
        text += f"<code>/имя сброс</code> - сбросить к настоящему\n\n"
        text += f"📏 <b>Требования:</b>\n"
        text += f"• От 3 до 20 символов\n"
        text += f"• Без символов < > \"\n"
        text += f"• Будет отображаться во всех играх и топах"
        
        await message.answer(text, parse_mode="HTML")
        return
    
    new_name = text_parts[1].strip()
    
    # Проверяем команду сброса
    if new_name.lower() in ["сброс", "reset", "удалить", "очистить"]:
        try:
            if db_pool:
                db_pool.execute_query("DELETE FROM custom_names WHERE user_id = ?", (user_id,))
                await message.answer("✅ Кастомное имя сброшено! Теперь используется ваше настоящее имя.")
            else:
                await message.answer("❌ Ошибка доступа к базе данных")
        except Exception:
            await message.answer("❌ Ошибка при сбросе имени")
        return
    
    # Проверяем и устанавливаем новое имя
    if len(new_name) < 3:
        await message.answer("❌ Имя слишком короткое! Минимум 3 символа.")
        return
    
    if len(new_name) > 20:
        await message.answer("❌ Имя слишком длинное! Максимум 20 символов.")
        return
    
    # Проверяем на запрещенные символы
    import re
    if re.search(r'[<>"]', new_name):
        await message.answer("❌ Имя содержит запрещенные символы: < > \"")
        return
    
    # Устанавливаем имя
    if set_custom_name(user_id, new_name):
        await message.answer(f"✅ Кастомное имя установлено: <b>{new_name}</b>\n\n"
                           f"Теперь в играх и топах вы будете отображаться как: {format_clickable_name(message.from_user)}", 
                           parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка при установке имени. Попробуйте еще раз.")

# Текстовая команда "имя"
@dp.message(lambda message: message.text and message.text.lower().strip().startswith("имя "))
async def text_set_name(message: types.Message):
    """Текстовая команда установки имени"""
    if not message.from_user:
        return
    
    # Извлекаем имя из сообщения
    new_name = message.text[4:].strip()  # type: ignore # Убираем "имя "
    
    user_id = message.from_user.id
    
    if not new_name:
        await cmd_set_name(message)  # Показываем справку
        return
    
    # Проверяем и устанавливаем
    if len(new_name) < 3:
        await message.answer("❌ Имя слишком короткое! Минимум 3 символа.")
        return
    
    if len(new_name) > 20:
        await message.answer("❌ Имя слишком длинное! Максимум 20 символов.")
        return
    
    import re
    if re.search(r'[<>"]', new_name):
        await message.answer("❌ Имя содержит запрещенные символы: < > \"")
        return
    
    if set_custom_name(user_id, new_name):
        await message.answer(f"✅ Кастомное имя установлено: <b>{new_name}</b>", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка при установке имени.")



# Обработчик переключения настройки приватности
@dp.callback_query(lambda c: c.data and c.data.startswith("privacy_toggle:"))
async def handle_privacy_toggle(callback: types.CallbackQuery):
    """Переключение настройки приватности профиля"""
    if not callback.from_user or not callback.data:
        return
    
    try:
        _, user_id_str = callback.data.split(":")
        user_id = int(user_id_str)
        
        # Проверяем права доступа
        if callback.from_user.id != user_id:
            await callback.answer("❌ Вы можете изменять только свои настройки!", show_alert=True)
            return
        
        # Переключаем настройку
        current_setting = get_profile_privacy(user_id)
        new_setting = not current_setting
        
        if set_profile_privacy(user_id, new_setting):
            # Успешно изменили настройку - обновляем кнопку
            status_text = "открытым" if new_setting else "приватным"
            privacy_status = "🔗 Открытый" if new_setting else "🔒 Приватный"
            
            # Создаем обновленную клавиатуру с новым статусом
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔒 Приватность: {privacy_status}", callback_data=f"privacy_toggle:{user_id}")],
                [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
            ])
            
            try:
                # Пытаемся обновить только клавиатуру (без текста)
                await callback.message.edit_reply_markup(reply_markup=kb) # type: ignore
                await callback.answer(f"✅ Профиль стал {status_text}!")
            except Exception:
                # Если не получилось обновить кнопку, просто отвечаем
                await callback.answer(f"✅ Профиль стал {status_text}! (обновится при следующем заходе)")
        else:
            await callback.answer("❌ Ошибка при сохранении настроек", show_alert=True)
    
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

# Обработчик информации о приватности - удаляем, так как больше не нужен

# --- КОМАНДА /GAME ИЛИ ИГРЫ ---

def get_games_list():
    """Возвращает полный список всех игр в боте"""
    games = [
        {
            "emoji": "🤵⚔️",
            "name": "БЕТ",
            "commands": "<code>бет</code> число",
            "type": "both"
        },
        {
            "emoji": "🤵",
            "name": "Клад",
            "commands": "<code>клад</code> число",
            "type": "solo"
        },
        {
            "emoji": "🤵",
            "name": "Сапёр",
            "commands": "<code>сапер</code> число",
            "type": "solo"
        },
        {
            "emoji": "⚔️",
            "name": "Кости",
            "commands": "<code>кости</code> число",
            "type": "battle"
        },
        {
            "emoji": "⚔️",
            "name": "Крестики-нолики",
            "commands": "<code>крестик</code>, <code>крестики</code>, <code>нолик</code> число",
            "type": "battle"
        },
        {
            "emoji": "🏟️⚔️",
            "name": "Арена",
            "commands": "<code>арена</code>, <code>arena</code>",
            "type": "battle"
        },
        # Новые боулинг-стайл игры
        {
            "emoji": "🎳",
            "name": "Боулинг",
            "commands": "Напиши: <code>боулинг</code> число",
            "type": "solo"
        },
        {
            "emoji": "⚽",
            "name": "Футбол",
            "commands": "Напиши: <code>футбол</code> число",
            "type": "solo"
        },
        {
            "emoji": "🎯",
            "name": "Дартс",
            "commands": "Напиши: <code>дартс</code> число",
            "type": "solo"
        }
    ]
    return games

def format_games_page(page: int = 1):
    """Форматирует страницу со списком игр"""
    games = get_games_list()
    per_page = 3  # По 3 игры на страницу  
    total_pages = (len(games) + per_page - 1) // per_page
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_games = games[start_idx:end_idx]
    
    text = f"🎮 <b>СПИСОК ИГР</b> 🎮\n\n"
    
    # Добавляем легенду
    text += f"<b>⚔️ - игры для батлов, ответом на сообщение</b>\n"
    text += f"<b>🤵 - Можно играть в соло</b>\n\n"
    
    for i, game in enumerate(page_games, 1):
        game_num = start_idx + i
        
        text += f"{game_num}. {game['emoji']} <b>{game['name']}</b>\n"
        text += f"   💬 Команды: {game['commands']}\n\n"
    
    return text, total_pages

def build_games_keyboard(current_page: int, total_pages: int):
    """Создает клавиатуру для навигации по играм"""
    buttons = []
    
    # Навигация по страницам
    if total_pages > 1:
        nav_row = []
        if current_page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"games_page:{current_page-1}"))
        
        nav_row.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="games_info"))
        
        if current_page < total_pages:
            nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"games_page:{current_page+1}"))
        
        buttons.append(nav_row)
    
    # Кнопка помощи
    buttons.append([InlineKeyboardButton(text="❓ Помощь по играм", callback_data="games_help")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("game"))
async def cmd_game(message: types.Message):
    """Команда /game - показывает список всех игр"""
    if not getattr(message, 'from_user', None):
        return
    
    text, total_pages = format_games_page(page=1)
    keyboard = build_games_keyboard(current_page=1, total_pages=total_pages)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(lambda message: message.text and message.text.lower().strip() == "игры")
async def cmd_games_text(message: types.Message):
    """Обработчик текстового сообщения 'игры'"""
    await cmd_game(message)

@dp.callback_query(lambda c: c.data.startswith("games_page:"))
async def games_page_callback(callback: types.CallbackQuery):
    """Навигация по страницам игр"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    try:
        page = int(callback.data.split(":")[1])
        text, total_pages = format_games_page(page=page)
        keyboard = build_games_keyboard(current_page=page, total_pages=total_pages)
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("Ошибка навигации", show_alert=True)

@dp.callback_query(lambda c: c.data == "games_info")
async def games_info_callback(callback: types.CallbackQuery):
    """Информация о списке игр"""
    await callback.answer("📋 Список всех доступных игр в боте", show_alert=False)

@dp.callback_query(lambda c: c.data == "games_help")
async def games_help_callback(callback: types.CallbackQuery):
    """Помощь по играм"""
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    
    help_text = (
        "❓ <b>ПОМОЩЬ ПО ИГРАМ</b> ❓\n\n"
        
        "🤵 <b>Соло игры:</b>\n"
        "• Играете против бота\n"
        "• Просто напишите команду с числом\n"
        "• Пример: <code>клад 100</code>\n\n"
        
        "⚔️ <b>Батл игры:</b>\n"
        "• Играете против других игроков\n"
        "• Ответьте на сообщение игрока командой\n"
        "• Пример: ответить на сообщение <code>кости 50</code>\n"
        "• Игрок может принять или отклонить вызов\n\n"
        
        "🤵⚔️ <b>Универсальные игры:</b>\n"
        "• Можно играть И соло, И в PvP режиме\n"
        "• Соло: просто команда <code>бет 100</code>\n"
        "• PvP: ответить на сообщение <code>бет 100</code>\n\n"
        
        "💡 <b>Как играть в батлы:</b>\n"
        "1. Найдите сообщение игрока\n"
        "2. Ответьте на него командой игры\n"
        "3. Дождитесь принятия вызова\n"
        "4. Играйте и побеждайте!\n\n"
        
        "� <b>Минимальные ставки:</b>\n"
        "• Большинство игр: от 10 дань\n"
        "• Лотерея: 100 дань за билет\n\n"
        
        "📞 Нужна помощь? Напишите /help"
    )
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к играм", callback_data="games_page:1")]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

# ===========================
# === БОУЛИНГ ИГРА ===
# ===========================

@dp.message(lambda m: m.text and re.search(r"боулинг|bowling", m.text, re.IGNORECASE) and re.search(r"\d+", m.text))
async def cmd_bowling_start(message: types.Message):
    """Запуск игры боулинг"""
    increment_games_count()
    
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    
    # ЗАЩИТА: Проверяем, нет ли уже активной игры у этого игрока
    if user_id in active_bowling_games:
        await message.reply("❌ У вас уже есть активная игра в боулинг! Завершите её сначала.")
        return
    
    text = message.text.strip().lower()
    
    # Парсим ставку из сообщения
    import re
    match = re.search(r'\d+', text)
    if not match:
        await message.reply("Формат: боулинг X (X — ставка в дань, минимум 10)")
        return
    
    try:
        bet = int(match.group())
    except Exception:
        await message.reply("Ставка должна быть числом!")
        return
    
    if bet < 10:
        await message.reply("❌ Минимальная ставка — 10 дань!")
        return
    
    # Проверяем баланс
    try:
        user = db.get_user(user_id)
    except Exception:
        await message.reply("❌ Ошибка получения баланса!")
        return
    
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await message.reply(f"❌ Недостаточно дань!\n💰 Ваш баланс: {balance}")
        return
    
    # Списываем ставку
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await message.reply("❌ Ошибка при списании ставки!")
        return
    
    # Создаём игру
    from plugins.games.bowling import BowlingGame, build_choice_keyboard
    username = format_clickable_name(message.from_user) if message.from_user else "Игрок"
    game = BowlingGame(user_id, username, bet)
    active_bowling_games[user_id] = game
    
    # Отправляем сообщение с выбором
    choice_text = (
        f"🎳 <b>Боулинг - выбери исход!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    
    await message.reply(choice_text, reply_markup=build_choice_keyboard(), parse_mode="HTML")


@dp.callback_query(lambda c: c.data and c.data.startswith("bowling_choice:"))
async def bowling_choice_callback(callback: types.CallbackQuery):
    """Обработчик выбора исхода в боулинге"""
    if not callback.from_user or not callback.message:
        return
    
    user_id = callback.from_user.id
    choice = callback.data.split(":")[1]
    
    # Проверяем, есть ли активная игра
    game = active_bowling_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена! Начните новую!", show_alert=True)
        return
    
    # ЗАЩИТА: Проверяем, что нажимает владелец игры
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    
    # Сохраняем выбор
    game.user_choice = choice
    
    # Удаляем сообщение с выбором
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    # Отправляем анимацию кегль (dice) 🎳
    dice_value = None
    try:
        # Кидаем dice с боулингом - Telegram вернёт значение от 1 до 6
        dice_msg = await callback.message.answer_dice(emoji="🎳")
        # Даём время на анимацию (~3-4 секунды)
        await asyncio.sleep(3)
        # Получаем реальное значение dice
        dice_value = dice_msg.dice.value
    except Exception as e:
        # Если dice не поддерживается, используем случайное значение
        await callback.message.answer("🎳" * 5 + " → " + "💥" * 5)
        await asyncio.sleep(1)
        dice_value = random.randint(1, 6)
    
    # ВАЖНО: Устанавливаем результат игры на основе РЕАЛЬНОГО значения dice
    # Telegram dice для боулинга: 1-6 (количество сбитых кегель)
    game.pins_fallen = dice_value
    
    # Теперь проверяем выигрыш на основе реального результата
    game.check_win()
    
    # Обновляем баланс если выиграли
    if game.winnings > 0:
        try:
            db.add_dan(user_id, game.winnings)
            db.increment_dan_win(user_id, game.winnings - game.bet)
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass
    else:
        try:
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass
    
    # Показываем результат
    result_text = game.get_status_text()
    # Если проигрыш — добавим строку с текущим балансом
    if game.winnings <= 0:
        try:
            user = db.get_user(user_id)
            if user and 'dan' in user:
                bal_txt = format_number_beautiful(user['dan']).replace('.', ',')
                result_text += f"\n\n⚡️ Баланс: {bal_txt}"
        except Exception:
            pass
    # Если проигрыш — добавим строку с текущим балансом
    if game.winnings <= 0:
        try:
            user = db.get_user(user_id)
            if user and 'dan' in user:
                bal_txt = format_number_beautiful(user['dan']).replace('.', ',')
                result_text += f"\n\n⚡️ Баланс: {bal_txt}"
        except Exception:
            pass
    
    # Кнопка для повтора
    repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎳 Играть ещё раз", callback_data=f"bowling_repeat:{game.bet}")]
    ])
    
    # Отправляем результат как новое сообщение (после анимации)
    await callback.message.answer(result_text, reply_markup=repeat_kb, parse_mode="HTML")
    
    # Удаляем игру из активных
    if user_id in active_bowling_games:
        del active_bowling_games[user_id]
    
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data == "bowling_cancel")
async def bowling_cancel_callback(callback: types.CallbackQuery):
    """Отмена игры в боулинг"""
    if not callback.from_user or not callback.message:
        return
    
    user_id = callback.from_user.id
    
    # Проверяем, есть ли активная игра
    game = active_bowling_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена!", show_alert=True)
        return
    
    # Проверяем, что отменяет владелец игры
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    
    # Удаляем игру из активных
    del active_bowling_games[user_id]
    
    # Редактируем сообщение
    await callback.message.edit_text("🎳 Игра отменена", reply_markup=None)
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("bowling_repeat:"))
async def bowling_repeat_callback(callback: types.CallbackQuery):
    """Повтор боулинга с той же ставкой"""
    if not callback.from_user:
        return
    
    user_id = callback.from_user.id
    bet_str = callback.data.split(":")[1]
    
    # Проверяем, нет ли уже активной игры
    if user_id in active_bowling_games:
        await callback.answer("❌ У вас уже есть активная игра в боулинг!", show_alert=True)
        return
    
    try:
        bet = int(bet_str)
    except Exception:
        await callback.answer("❌ Ошибка при повторе игры!", show_alert=True)
        return
    
    # Проверяем баланс
    try:
        user = db.get_user(user_id)
    except Exception:
        await callback.answer("❌ Ошибка получения баланса!", show_alert=True)
        return
    
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await callback.answer(f"❌ Недостаточно дань!\n💰 Баланс: {balance}", show_alert=True)
        return
    
    # Списываем ставку
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
        return
    
    # Создаём новую игру
    from plugins.games.bowling import BowlingGame, build_choice_keyboard
    username = format_clickable_name(callback.from_user) if callback.from_user else "Игрок"
    game = BowlingGame(user_id, username, bet)
    active_bowling_games[user_id] = game
    # Засчитываем как игру дня (любая игра)
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass
    
    # Отправляем сообщение с выбором через answer (новое сообщение)
    choice_text = (
        f"🎳 <b>Боулинг - выбери исход!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    
    await callback.message.answer(choice_text, reply_markup=build_choice_keyboard(), parse_mode="HTML")
    await callback.answer()


# ===========================
# === ДАРТС (🎯) ===
# ===========================

@dp.message(lambda m: m.text and re.search(r"дартс|darts|🎯", m.text, re.IGNORECASE) and re.search(r"\d+", m.text))
async def cmd_darts_start(message: types.Message):
    """Запуск игры дартс"""
    increment_games_count()
    if not message.from_user:
        return
    user_id = message.from_user.id

    # Защита от дубликатов
    if user_id in active_darts_games:
        await message.reply("❌ У вас уже есть активный дартс! Завершите его сначала.")
        return

    text = message.text.strip().lower()
    match = re.search(r"\d+", text)
    if not match:
        await message.reply("Формат: дартс X (минимум 10)")
        return
    try:
        bet = int(match.group())
    except Exception:
        await message.reply("Ставка должна быть числом!")
        return
    if bet < 10:
        await message.reply("❌ Минимальная ставка — 10 дань!")
        return

    # Баланс
    try:
        user = db.get_user(user_id)
    except Exception:
        await message.reply("❌ Ошибка получения баланса!")
        return
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await message.reply(f"❌ Недостаточно дань!\n💰 Ваш баланс: {balance}")
        return

    # Списание
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await message.reply("❌ Ошибка при списании ставки!")
        return

    # Создание игры
    from plugins.games.darts import DartsGame, build_choice_keyboard as darts_keyboard
    username = format_clickable_name(message.from_user) if message.from_user else "Игрок"
    game = DartsGame(user_id, username, bet)
    active_darts_games[user_id] = game
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass

    text = (
        f"🎯 <b>Дартс - выбери попадание!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    await message.reply(text, reply_markup=darts_keyboard(), parse_mode="HTML")


@dp.callback_query(lambda c: c.data and c.data.startswith("darts_choice:"))
async def darts_choice_callback(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    choice = callback.data.split(":")[1]
    game = active_darts_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена!", show_alert=True)
        return
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    game.user_choice = choice
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Бросаем 🎯
    dice_msg = None
    try:
        dice_msg = await callback.message.answer_dice(emoji="🎯")
        await asyncio.sleep(3)
        game.dice_value = dice_msg.dice.value
    except Exception:
        game.dice_value = random.randint(1, 6)

    game.check_win()
    # Баланс
    if game.winnings > 0:
        try:
            db.add_dan(user_id, game.winnings)
            db.increment_dan_win(user_id, game.winnings - game.bet)
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass
    else:
        try:
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass

    result_text = game.get_status_text()
    repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Играть ещё раз", callback_data=f"darts_repeat:{game.bet}")]
    ])
    # Отправляем как ответ (reply) на сообщение с кубиком, если оно есть
    try:
        if dice_msg is not None:
            await dice_msg.reply(result_text, reply_markup=repeat_kb, parse_mode="HTML")
        else:
            await callback.message.answer(result_text, reply_markup=repeat_kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(result_text, reply_markup=repeat_kb, parse_mode="HTML")
    if user_id in active_darts_games:
        del active_darts_games[user_id]
    await callback.answer()


@dp.callback_query(lambda c: c.data == "darts_cancel")
async def darts_cancel_callback(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    game = active_darts_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена!", show_alert=True)
        return
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    del active_darts_games[user_id]
    await callback.message.edit_text("🎯 Игра отменена", reply_markup=None)
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("darts_repeat:"))
async def darts_repeat_callback(callback: types.CallbackQuery):
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    try:
        bet = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("❌ Ошибка повтора!", show_alert=True)
        return
    if user_id in active_darts_games:
        await callback.answer("❌ У вас уже есть активный дартс!", show_alert=True)
        return
    try:
        user = db.get_user(user_id)
    except Exception:
        await callback.answer("❌ Ошибка баланса!", show_alert=True)
        return
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await callback.answer(f"❌ Недостаточно дань! Баланс: {balance}", show_alert=True)
        return
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await callback.answer("❌ Ошибка при списании!", show_alert=True)
        return
    from plugins.games.darts import DartsGame, build_choice_keyboard as darts_keyboard
    username = format_clickable_name(callback.from_user) if callback.from_user else "Игрок"
    game = DartsGame(user_id, username, bet)
    active_darts_games[user_id] = game
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass
    text = (
        f"🎯 <b>Дартс - выбери попадание!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    await callback.message.answer(text, reply_markup=darts_keyboard(), parse_mode="HTML")
    await callback.answer()


# ===========================
# === БАСКЕТБОЛ (заглушка) ===
# ===========================

@dp.message(lambda m: m.text and re.search(r"баскетбол|basketball|🏀", m.text, re.IGNORECASE) and re.search(r"\d+", m.text))
async def basketball_stub(message: types.Message):
    """Заглушка для баскетбола — пока в разработке"""
    try:
        text = (
            "🏀 <b>Баскетбол</b>\n\n"
            "Игра в разработке и скоро будет доступна.\n"
            "Следи за обновлениями!"
        )
        await message.reply(text, parse_mode="HTML")
    except Exception:
        pass


# ===========================
# === ФУТБОЛ (⚽) ===
# ===========================

@dp.message(lambda m: m.text and re.search(r"футбол|soccer|football|⚽", m.text, re.IGNORECASE) and re.search(r"\d+", m.text))
async def cmd_soccer_start(message: types.Message):
    increment_games_count()
    if not message.from_user:
        return
    user_id = message.from_user.id
    if user_id in active_soccer_games:
        await message.reply("❌ У вас уже есть активный футбол! Завершите его сначала.")
        return
    match = re.search(r"\d+", message.text)
    if not match:
        await message.reply("Формат: футбол X (минимум 10)")
        return
    try:
        bet = int(match.group())
    except Exception:
        await message.reply("Ставка должна быть числом!")
        return
    if bet < 10:
        await message.reply("❌ Минимальная ставка — 10 дань!")
        return
    try:
        user = db.get_user(user_id)
    except Exception:
        await message.reply("❌ Ошибка получения баланса!")
        return
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await message.reply(f"❌ Недостаточно дань!\n💰 Ваш баланс: {balance}")
        return
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await message.reply("❌ Ошибка при списании ставки!")
        return
    from plugins.games.soccer import SoccerGame, build_choice_keyboard as soccer_keyboard
    username = format_clickable_name(message.from_user) if message.from_user else "Игрок"
    game = SoccerGame(user_id, username, bet)
    active_soccer_games[user_id] = game
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass
    text = (
        f"⚽ <b>Футбол - угадай исход!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    await message.reply(text, reply_markup=soccer_keyboard(), parse_mode="HTML")


@dp.callback_query(lambda c: c.data and c.data.startswith("soccer_choice:"))
async def soccer_choice_callback(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    choice = callback.data.split(":")[1]
    game = active_soccer_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена!", show_alert=True)
        return
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    game.user_choice = choice
    try:
        await callback.message.delete()
    except Exception:
        pass
    # Бросаем ⚽
    dice_msg = None
    try:
        dice_msg = await callback.message.answer_dice(emoji="⚽")
        await asyncio.sleep(3)
        game.dice_value = dice_msg.dice.value
    except Exception:
        game.dice_value = random.randint(1, 6)

    game.check_win()
    if game.winnings > 0:
        try:
            db.add_dan(user_id, game.winnings)
            db.increment_dan_win(user_id, game.winnings - game.bet)
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass
    else:
        try:
            db.increment_dan_lose(user_id, game.bet)
        except Exception:
            pass
    result_text = game.get_status_text()
    repeat_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽ Играть ещё раз", callback_data=f"soccer_repeat:{game.bet}")]
    ])
    # Отправляем как reply на сообщение с кубиком, если оно есть
    try:
        if dice_msg is not None:
            await dice_msg.reply(result_text, reply_markup=repeat_kb, parse_mode="HTML")
        else:
            await callback.message.answer(result_text, reply_markup=repeat_kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(result_text, reply_markup=repeat_kb, parse_mode="HTML")
    if user_id in active_soccer_games:
        del active_soccer_games[user_id]
    await callback.answer()


@dp.callback_query(lambda c: c.data == "soccer_cancel")
async def soccer_cancel_callback(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    game = active_soccer_games.get(user_id)
    if not game:
        await callback.answer("❌ Игра не найдена!", show_alert=True)
        return
    if game.user_id != user_id:
        await callback.answer("❌ Это не ваша игра!", show_alert=True)
        return
    del active_soccer_games[user_id]
    await callback.message.edit_text("⚽ Игра отменена", reply_markup=None)
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("soccer_repeat:"))
async def soccer_repeat_callback(callback: types.CallbackQuery):
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    try:
        bet = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("❌ Ошибка повтора!", show_alert=True)
        return
    if user_id in active_soccer_games:
        await callback.answer("❌ У вас уже есть активный футбол!", show_alert=True)
        return
    try:
        user = db.get_user(user_id)
    except Exception:
        await callback.answer("❌ Ошибка баланса!", show_alert=True)
        return
    if not user or user["dan"] < bet:
        balance = user["dan"] if user else 0
        await callback.answer(f"❌ Недостаточно дань! Баланс: {balance}", show_alert=True)
        return
    try:
        db.withdraw_dan(user_id, bet)
    except Exception:
        await callback.answer("❌ Ошибка при списании!", show_alert=True)
        return
    from plugins.games.soccer import SoccerGame, build_choice_keyboard as soccer_keyboard
    username = format_clickable_name(callback.from_user) if callback.from_user else "Игрок"
    game = SoccerGame(user_id, username, bet)
    active_soccer_games[user_id] = game
    try:
        import tasks
        tasks.record_any_game(user_id)
    except Exception:
        pass
    text = (
        f"⚽ <b>Футбол - угадай исход!</b>\n\n"
        f"💰 <b>Ставка:</b> {bet} Дань\n"
    )
    await callback.message.answer(text, reply_markup=soccer_keyboard(), parse_mode="HTML")
    await callback.answer()


# Слоты (🎰) удалены по требованию: обработчики и модуль отключены


@dp.message(lambda message: message.text and message.text.lower().strip() in ["лотерея", "лотерейя", "lottery"])
async def text_lottery_handler(message: types.Message):
    """Обработчик текстового сообщения 'лотерея' или 'lottery'"""
    await ticket_handler(message)

@dp.callback_query(lambda c: c.data.startswith("buy_ticket:"))
async def buy_ticket_callback(callback: types.CallbackQuery):
    """Обработчик покупки билета"""
    if not callback.from_user:
        return
    
    # Проверяем на устаревший callback
    if not await check_callback_validity(callback):
        return
    
    parts = callback.data.split(":")
    owner_user_id = int(parts[1])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        try:
            await callback.answer("❌ Это не ваше меню!", show_alert=True)
        except Exception:
            pass
        return
    
    username = getattr(callback.from_user, 'username', None) or f"User_{owner_user_id}"
    success, message = buy_lottery_ticket(owner_user_id, username)
    
    if success:
        # Обновляем информацию и показываем обновленное меню
        total_tickets_sold, total_tickets_value = get_total_tickets_info()
        user_tickets_count = get_user_tickets_count(owner_user_id)
        win_chance = (user_tickets_count / total_tickets_sold * 100) if total_tickets_sold > 0 else 0
        
        # Получаем обновленный баланс пользователя
        user = db.get_user(owner_user_id)
        dan_balance = float(user.get("dan", 0)) if user else 0
        
        # Вычисляем сколько дань потрачено на билеты сегодня
        spent_today = user_tickets_count * 100
        
        # Форматируем строку баланса
        if spent_today > 0:
            balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань (-{spent_today} дань потрачено сегодня)"
        else:
            balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань"
        
        # Получаем статичный дневной бонус
        preview_bonus = get_daily_lottery_bonus()
        
        text = (
            f"🎫 <b>ЛОТЕРЕЯ KRUZCHAT</b> 🎫\n\n"
            f"✅ {message}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"🎟️ Сейчас куплено {total_tickets_sold} билетов, на {total_tickets_value:,.0f} дань\n\n"
            f"🎯 <b>Ваши шансы:</b>\n"
            f"📈 Шанс на выигрыш {win_chance:.1f}%\n"
            f"🎫 У вас {user_tickets_count} билетов (максимум 10)\n"
            f"🎁 Сегодня бонус +{preview_bonus:,} дань к призовому фонду!\n"
            f"{balance_text}\n\n"
            f"💰 <b>Условия:</b>\n"
            f"💵 Цена 1 билета: 100 дань\n"
            f"🕛 Ровно в 21:00 рандомно будет выбран победитель\n"
            f"🏆 Победитель получает ВСЕ!"
        )
        
        # Показываем кнопки в зависимости от текущего количества билетов у пользователя
        if user_tickets_count >= 10:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_user_id}")]])
            print(f"[LOTTERY] buy_ticket: user {owner_user_id} now has {user_tickets_count} tickets -> showing only CLOSE")
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎫 КУПИТЬ БИЛЕТ", callback_data=f"buy_ticket:{owner_user_id}"), InlineKeyboardButton(text="🧺 ДОКУПИТЬ ДО 10", callback_data=f"buy_to_10:{owner_user_id}")],[InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_user_id}")]])
            print(f"[LOTTERY] buy_ticket: user {owner_user_id} now has {user_tickets_count} tickets -> showing BUY and BUY_TO_10")
        
        edit_success = await safe_edit_message(callback, text, keyboard, parse_mode='HTML')
        if edit_success:
            try:
                await callback.answer("🎫 Билет куплен!")
            except Exception:
                print("Не удалось отправить уведомление о покупке билета")
            # Попробуем явно обновить клавиатуру через edit_reply_markup — это надежно для медиа-сообщений
            try:
                if getattr(callback, 'message', None):
                    await callback.message.edit_reply_markup(reply_markup=keyboard)
            except Exception as e:
                # Игнорируем: safe_edit_message уже пытался редактировать
                print(f"⚠️ Не удалось обновить reply_markup напрямую: {e}")
    else:
        try:
            await callback.answer(f"❌ {message}", show_alert=True)
        except Exception:
            print(f"Не удалось показать ошибку: {message}")

@dp.callback_query(lambda c: c.data.startswith("close_menu:"))
async def close_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки закрытия меню"""
    if not callback.from_user:
        return
    
    # Проверяем на устаревший callback
    if not await check_callback_validity(callback):
        return
    
    parts = callback.data.split(":")
    owner_user_id = int(parts[1])
    
    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        try:
            await callback.answer("❌ Это не ваше меню!", show_alert=True)
        except Exception:
            pass
        return
    
    # Удаляем сообщение
    try:
        await callback.message.delete()
        await callback.answer("Меню закрыто")
    except Exception:
        try:
            await callback.answer("Меню закрыто")
        except Exception:
            print("Не удалось ответить на callback при закрытии меню")


@dp.callback_query(lambda c: c.data.startswith("buy_to_10:"))
async def buy_to_10_callback(callback: types.CallbackQuery):
    """Докупить билеты до 10 шт. (сколько не хватает)"""
    if not callback.from_user:
        return

    # Проверяем на устаревший callback
    if not await check_callback_validity(callback):
        return

    parts = callback.data.split(":")
    owner_user_id = int(parts[1])

    # Проверяем права доступа
    if callback.from_user.id != owner_user_id:
        try:
            await callback.answer("❌ Это не ваше меню!", show_alert=True)
        except Exception:
            pass
        return

    # Сколько у пользователя уже есть
    user_tickets_count = get_user_tickets_count(owner_user_id)
    print(f"[LOTTERY] buy_to_10 called by {owner_user_id}, current tickets={user_tickets_count}")
    if user_tickets_count >= 10:
        try:
            await callback.answer("У вас уже 10 билетов", show_alert=True)
        except Exception:
            pass
        return

    needed = 10 - user_tickets_count

    # Даем быстрый ответ, чтобы пользователь видел реакцию
    try:
        await callback.answer("Пробую докупить билеты...", show_alert=False)
    except Exception:
        pass

    # Пытаемся купить needed билетов по одному (reuse buy_lottery_ticket logic)
    username = getattr(callback.from_user, 'username', None) or f"User_{owner_user_id}"
    bought = 0
    msg_err = None
    for _ in range(needed):
        success, message = buy_lottery_ticket(owner_user_id, username)
        if success:
            bought += 1
        else:
            msg_err = message
            break
    print(f"[LOTTERY] buy_to_10 result for {owner_user_id}: bought={bought}, err={msg_err}")
    print(f"[LOTTERY] buy_to_10 result for {owner_user_id}: bought={bought}, err={msg_err}")

    # Обновляем меню — повторяем тот же код что и в buy_ticket_callback (обновление текста/кнопок)
    total_tickets_sold, total_tickets_value = get_total_tickets_info()
    user_tickets_count = get_user_tickets_count(owner_user_id)
    win_chance = (user_tickets_count / total_tickets_sold * 100) if total_tickets_sold > 0 else 0
    user = db.get_user(owner_user_id)
    dan_balance = float(user.get("dan", 0)) if user else 0
    spent_today = user_tickets_count * 100
    balance_text = f"💰 Ваш баланс: {dan_balance:,.0f} дань (-{spent_today} дань потрачено сегодня)" if spent_today > 0 else f"💰 Ваш баланс: {dan_balance:,.0f} дань"
    preview_bonus = get_daily_lottery_bonus()

    # Формируем текст корректно — если что-то куплено, добавляем статус в начало
    status_block = f"✅ Куплено: {bought} билетов\n\n" if bought > 0 else ""
    text = (
        f"🎫 <b>ЛОТЕРЕЯ KRUZCHAT</b> 🎫\n\n"
        f"{status_block}"
        f"📊 <b>Статистика:</b>\n"
        f"🎟️ Сейчас куплено {total_tickets_sold} билетов, на {total_tickets_value:,.0f} дань\n\n"
        f"🎯 <b>Ваши шансы:</b>\n"
        f"📈 Шанс на выигрыш {win_chance:.1f}%\n"
        f"🎫 У вас {user_tickets_count} билетов (максимум 10)\n"
        f"🎁 Сегодня бонус +{preview_bonus:,} дань к призовому фонду!\n"
        f"{balance_text}\n\n"
        f"💰 <b>Условия:</b>\n"
        f"💵 Цена 1 билета: 100 дань\n"
        f"🕛 Ровно в 21:00 рандомно будет выбран победитель\n"
        f"🏆 Победитель получает ВСЕ!"
    )

    # Кнопки: если уже 10 — только закрыть, иначе две кнопки (купить 1 и докупить до 10)
    if user_tickets_count >= 10:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_user_id}")]])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎫 КУПИТЬ БИЛЕТ", callback_data=f"buy_ticket:{owner_user_id}"), InlineKeyboardButton(text="🧺 ДОКУПИТЬ ДО 10", callback_data=f"buy_to_10:{owner_user_id}")],
            [InlineKeyboardButton(text="❌ ЗАКРЫТЬ", callback_data=f"close_menu:{owner_user_id}")]
        ])

    # Сначала попробуем обновить только reply_markup (не трогая текст) — это часто надежнее
    try:
        if getattr(callback, 'message', None):
            await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        # Если не получилось (например, сообщение с медиа), пробуем полное редактирование
        try:
            # Обновляем меню
            await safe_edit_message(callback, text, keyboard, parse_mode='HTML')
        except Exception as e2:
            print(f"❌ Ошибка при обновлении меню лотереи: {e2}")
    else:
        # Если reply_markup обновился — попробуем обновить текст через safe_edit_message, но не критично
        try:
            await safe_edit_message(callback, text, keyboard, parse_mode='HTML')
        except Exception:
            pass
    try:
        if bought > 0:
            await callback.answer(f"Куплено {bought} билетов")
        elif msg_err:
            await callback.answer(f"{msg_err}", show_alert=True)
    except Exception:
        pass

@dp.message(Command("tell"))
async def admin_tell_handler(message: types.Message):
    """Админ команда для рассылки сообщения всем пользователям"""
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    
    # Проверяем права админа
    if user_id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    # Проверяем, является ли это ответом на сообщение
    if message.reply_to_message:
        # Режим пересылки - пересылаем сообщение, на которое ответили
        target_message = message.reply_to_message
        
        # Получаем всех пользователей из базы данных
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            all_users = cursor.fetchall()
            conn.close()
            
            if not all_users:
                await message.answer("❌ Нет пользователей в базе данных")
                return
            
            # Отправляем уведомление админу о начале рассылки
            await message.answer(f"📡 Начинаю пересылку сообщения {len(all_users)} пользователям...")
            
            # Пересылаем сообщение всем пользователям (с сохранением премиум эмодзи)
            success_count = 0
            failed_count = 0
            
            for (target_user_id,) in all_users:
                try:
                    # Используем forward_message для сохранения премиум эмодзи
                    # Отправитель будет виден, но премиум контент сохранится
                    await bot.forward_message(
                        chat_id=target_user_id,
                        from_chat_id=target_message.chat.id,
                        message_id=target_message.message_id
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    failed_count += 1
                    # Убираем вывод ошибок в консоль для чистоты лога
            
            # Отчет админу
            result_message = (
                f"✅ <b>Пересылка завершена!</b>\n\n"
                f"📊 Статистика:\n"
                f"✅ Успешно: {success_count}\n"
                f"❌ Ошибок: {failed_count}\n"
                f"👥 Всего: {len(all_users)}"
            )
            await message.answer(result_message, parse_mode='HTML')
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при пересылке: {e}")
    
    else:
        # Обычный режим - отправляем текст после команды
        command_text = message.text or ""
        if len(command_text.split(maxsplit=1)) < 2:
            await message.answer(
                "📝 <b>Использование команды /tell:</b>\n\n"
                "1️⃣ <b>Текстовая рассылка:</b>\n"
                "/tell <сообщение>\n"
                "Пример: /tell Привет всем! Обновление бота!\n\n"
                "2️⃣ <b>Пересылка сообщения:</b>\n"
                "Ответьте на любое сообщение командой /tell\n"
                "Сообщение будет скопировано всем пользователям с сохранением премиум эмодзи и форматирования",
                parse_mode='HTML'
            )
            return
        
        broadcast_message = command_text.split(maxsplit=1)[1]
        
        # Получаем всех пользователей из базы данных
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            all_users = cursor.fetchall()
            conn.close()
            
            if not all_users:
                await message.answer("❌ Нет пользователей в базе данных")
                return
            
            # Отправляем уведомление админу о начале рассылки
            await message.answer(f"📡 Начинаю рассылку сообщения {len(all_users)} пользователям...")
            
            # Отправляем сообщение всем пользователям
            success_count = 0
            failed_count = 0
            
            for (target_user_id,) in all_users:
                try:
                    await bot.send_message(target_user_id, broadcast_message, parse_mode='HTML')
                    success_count += 1
                    await asyncio.sleep(0.05) 
                except Exception as e:
                    failed_count += 1
                    # Убираем вывод ошибок в консоль для чистоты лога
            
            # Отчет админу
            result_message = (
                f"✅ <b>Рассылка завершена!</b>\n\n"
                f"📊 Статистика:\n"
                f"✅ Успешно: {success_count}\n"
                f"❌ Ошибок: {failed_count}\n"
                f"👥 Всего: {len(all_users)}"
            )
            await message.answer(result_message, parse_mode='HTML')
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при рассылке: {e}")

@dp.message(Command("test_lottery"))
async def test_lottery_handler(message: types.Message):
    """Закрытие текущей лотереи с розыгрышем и отправкой результатов в ЛС (доступно всем участникам)"""
    if not getattr(message, 'from_user', None):
        return
    
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', None) or f"User_{user_id}"
    
    await message.answer("🎲 Проводим тестовый розыгрыш лотереи...")
    
    try:
        # Проводим розыгрыш
        winner_info, total_tickets, prize_pool = conduct_lottery_draw()
        
        if winner_info:
            winner_user_id, winner_username, winner_ticket_count = winner_info
            
            result_text = (
                f"✅ Розыгрыш лотереи завершен!\n\n"
                f"🏆 Победитель: @{winner_username} (ID: {winner_user_id})\n"
                f"🎫 Билетов у победителя: {winner_ticket_count} из {total_tickets}\n"
                f"💰 Выигрыш: {prize_pool:,} дань\n\n"
                f"� Результаты отправлены всем участникам в ЛС\n"
                f"🔒 Все билеты помечены как разыгранные"
            )
            
            # Отправляем результаты участникам в ЛС
            await send_lottery_results(winner_info, total_tickets, prize_pool)
            
        elif winner_info == "no_participants_high_prize":
            # Случай высокого бонуса без участников
            result_text = (
                f"😱 Тестовый розыгрыш завершен!\n\n"
                f"❌ Участников не было\n" 
                f"💸 Упущенный бонус: {prize_pool:,} дань\n\n"
                f"📢 Всем пользователям отправлены уведомления о пропущенной возможности!"
            )
            
            # Отправляем уведомления всем пользователям
            await send_missed_lottery_notification(prize_pool)
            
        else:
            pass  # Нет участников, просто завершаем
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при тестировании: {e}")

@dp.message(lambda message: message.text and message.text.lower().strip() in ["итоги лотереи", "провести розыгрыш", "лотерея конец"])
async def admin_lottery_draw_command(message: types.Message):
    """Админская команда для принудительного проведения розыгрыша лотереи"""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    
    # Проверяем права администратора
    if user_id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для выполнения этой команды!")
        return
    
    try:
        await message.answer("🎲 Запускаю принудительный розыгрыш лотереи...")
        
        # Проводим розыгрыш
        winner_info, total_tickets, prize_pool = conduct_lottery_draw()
        
        if winner_info:
            winner_user_id, winner_username, winner_ticket_count = winner_info
            
            result_text = (
                f"🎉 <b>ПРИНУДИТЕЛЬНЫЙ РОЗЫГРЫШ ЗАВЕРШЕН!</b> 🎉\n\n"
                f"🏆 <b>Победитель:</b> {winner_username}\n"
                f"🆔 <b>ID победителя:</b> {winner_user_id}\n"
                f"🎫 <b>Билетов у победителя:</b> {winner_ticket_count} из {total_tickets}\n"
                f"📈 <b>Шанс победителя:</b> {(winner_ticket_count / total_tickets * 100):.1f}%\n"
                f"💰 <b>Размер выигрыша:</b> {prize_pool:,} дань\n\n"
                f"✅ <b>Приз начислен на баланс победителя</b>\n"
                f"📢 <b>Результаты отправлены всем участникам</b>"
            )
            
            # Отправляем результаты участникам
            await send_lottery_results(winner_info, total_tickets, prize_pool)
            
        else:
            result_text = (
                f"❌ <b>РОЗЫГРЫШ НЕ ПРОВЕДЕН</b>\n\n"
                f"📋 Причина: Нет активных участников лотереи\n"
                f"💡 Участники должны сначала купить билеты через команду 'лотерея'"
            )
        
        await message.answer(result_text, parse_mode='HTML')
        # После принудительного розыгрыша тоже сгенерируем бонус для следующего дня
        try:
            import pytz
            kyiv_tz = pytz.timezone('Europe/Kiev')
            now_utc = datetime.datetime.now(pytz.UTC)
            now_kyiv = now_utc.astimezone(kyiv_tz)
            tomorrow_kyiv = (now_kyiv + datetime.timedelta(days=1)).date()
            next_bonus = generate_deterministic_lottery_bonus_for_date(tomorrow_kyiv)
            set_stored_lottery_bonus_for_date(tomorrow_kyiv.isoformat(), next_bonus)
            print(f"🔁 (manual) Бонус для {tomorrow_kyiv.isoformat()} сохранён: {next_bonus}")
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении бонуса после принудительного розыгрыша: {e}")

    except Exception as e:
        await message.answer(f"❌ Ошибка при проведении розыгрыша: {e}")

@dp.message(lambda message: message.text and message.text.lower().strip().startswith("+опыт"))
async def admin_add_xp_command(message: types.Message):
    """Админская команда для выдачи опыта. Формат: +опыт <количество>"""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    
    # Проверяем права администратора
    if user_id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для выполнения этой команды!")
        return
    
    try:
        # Парсим количество опыта
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            await message.answer("❌ Укажите количество опыта!\nФормат: +опыт <количество>\nПример: +опыт 5000")
            return
        
        xp_amount = int(parts[1])
        
        if xp_amount <= 0:
            await message.answer("❌ Количество опыта должно быть положительным числом!")
            return
        
        # Добавляем опыт через основную БД
        result = add_xp(user_id, xp_amount)
        
        # Формируем ответ
        result_text = f"✅ <b>Опыт добавлен!</b>\n\n"
        result_text += f"➕ Получено опыта: <b>{xp_amount}</b>\n"
        result_text += f"📊 Текущий опыт: <b>{result['xp']}/5000</b>\n"
        result_text += f"⭐ Уровень: <b>{result['level']}</b>"
        
        if result['leveled_up']:
            result_text += f"\n\n🎉 <b>ПОВЫШЕНИЕ УРОВНЯ!</b>"
            result_text += f"\nПолучено уровней: <b>+{result['levels_gained']}</b>"
            result_text += f"\n🎁 Наград к получению: <b>{result['pending_rewards']}</b>"
        
        await message.answer(result_text, parse_mode='HTML')
        
    except ValueError:
        await message.answer("❌ Неверный формат!\nФормат: +опыт <число>\nПример: +опыт 5000")
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении опыта: {e}")

@dp.message(lambda message: message.text and message.text.lower().strip() in ["итоги лотереи", "результаты лотереи", "lottery results"])
async def lottery_results_command(message: types.Message):
    """Показывает итоги последних розыгрышей лотереи"""
    if not message.from_user:
        return
    
    try:
        conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
        cursor = conn.cursor()
        
        # Получаем последние 5 розыгрышей
        cursor.execute('''
            SELECT draw_date, winner_user_id, winner_username, total_tickets, prize_amount
            FROM lottery_draws 
            ORDER BY draw_date DESC 
            LIMIT 5
        ''')
        
        draws = cursor.fetchall()
        
        if not draws:
            await message.answer("📊 Пока не было проведено ни одного розыгрыша лотереи.")
            conn.close()
            return
        
        # Форматируем результаты
        results_text = "🏆 <b>ИТОГИ ПОСЛЕДНИХ РОЗЫГРЫШЕЙ ЛОТЕРЕИ</b> 🏆\n\n"
        
        for i, (draw_date, winner_id, winner_name, total_tickets, prize_amount) in enumerate(draws, 1):
            # Форматируем дату
            try:
                date_obj = datetime.datetime.strptime(draw_date, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except:
                formatted_date = draw_date
            
            results_text += f"<b>{i}. {formatted_date}</b>\n"
            results_text += f"🏆 Победитель: {winner_name or f'User_{winner_id}'}\n"
            results_text += f"🎫 Билетов участвовало: {total_tickets}\n"
            results_text += f"💰 Выигрыш: {prize_amount:,} дань\n\n"
        
        # Получаем статистику участников за сегодня
        import pytz
        kyiv_tz = pytz.timezone('Europe/Kiev')
        now_kyiv = datetime.datetime.now(pytz.UTC).astimezone(kyiv_tz)
        today_kyiv = now_kyiv.date().isoformat()
        
        cursor.execute('''
            SELECT COUNT(DISTINCT user_id) as participants, COUNT(*) as tickets
            FROM lottery_tickets 
            WHERE draw_date = ? AND status = 'active'
        ''', (today_kyiv,))
        
        today_stats = cursor.fetchone()
        participants_today = today_stats[0] if today_stats else 0
        tickets_today = today_stats[1] if today_stats else 0
        
        results_text += "📅 <b>СЕГОДНЯШНЯЯ ЛОТЕРЕЯ</b>\n"
        results_text += f"👥 Участников: {participants_today}\n"
        results_text += f"🎫 Билетов продано: {tickets_today}\n"
        results_text += f"💰 Призовой фонд: {tickets_today * 100:,} дань\n"
        results_text += f"🕚 Розыгрыш: сегодня в 21:00 по Киеву\n\n"
        
        results_text += "💡 Чтобы участвовать, напишите <b>лотерея</b>"
        
        conn.close()
        await message.answer(results_text, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении итогов: {e}")

# Админ-команды: +item/-item в ответ на сообщение — выдать/отобрать предмет у пользователя
@dp.message(lambda m: m.reply_to_message and m.text and (m.text.strip().startswith("+item") or m.text.strip().startswith("-item")))
async def admin_give_item(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Нет доступа.")
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("Формат: +item item_id count или -item item_id count")
        return

    operation = "add" if parts[0] == "+item" else "remove"
    item_id = parts[1]
    try:
        count = int(parts[2])
    except Exception:
        await message.reply("Количество должно быть числом.")
        return

    if item_id not in ITEMS_CONFIG:
        await message.reply("❌ Такого предмета нет в конфиге")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Нужно ответить на сообщение пользователя.")
        return

    target = message.reply_to_message.from_user
    display = getattr(target, 'full_name', None) or (f"@{getattr(target, 'username', None)}" if getattr(target, 'username', None) else str(getattr(target, 'id', 'unknown')))
    
    # Для животных — работаем с owned_animals как с индивидуальными сущностями
    if ITEMS_CONFIG[item_id].get('category') == 'animal':
        from ferma import add_owned_animal
        if operation == "add":
            for _ in range(max(0, count)):
                add_owned_animal(target.id, item_id, last_fed_time=0)
            await message.reply(f"✅ Пользователю {display} добавлено {count} индивидуальных: {ITEMS_CONFIG[item_id]['name']}")
        else:
            # Удаляем указанное количество из owned_animals (первые по id)
            try:
                import sqlite3
                conn = sqlite3.connect(DATABASE_FILE)
                cur = conn.cursor()
                cur.execute('SELECT id FROM owned_animals WHERE user_id=? AND animal_item_id=? ORDER BY id ASC LIMIT ?', (target.id, item_id, count))
                ids = [row[0] for row in cur.fetchall()]
                for oid in ids:
                    cur.execute('DELETE FROM owned_animals WHERE id=?', (oid,))
                conn.commit()
                conn.close()
                removed = len(ids)
            except Exception:
                removed = 0
            await message.reply(f"🗑️ У пользователя {display} изъято {removed} индивидуальных: {ITEMS_CONFIG[item_id]['name']}")
    else:
        if operation == "add":
            db.add_item(target.id, item_id, count)
            await message.reply(f"✅ Пользователю {display} выдано {count} x {ITEMS_CONFIG[item_id]['name']}")
        else:
            # Для удаления предмета
            db.remove_item(target.id, item_id, count)
            await message.reply(f"🗑️ У пользователя {display} изъято {count} x {ITEMS_CONFIG[item_id]['name']}")

# Админ-команда: +ban N в ответ на сообщение — дать мут в игре на N минут (макс 7 дней)
@dp.message(lambda m: m.reply_to_message and m.text and m.text.strip().startswith("+ban"))
async def admin_ban(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Нет доступа.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Формат: +ban N (где N - минуты)")
        return

    try:
        minutes = int(parts[1])
    except Exception:
        await message.reply("Количество минут должно быть числом.")
        return

    # Максимум 7 дней (10080 минут)
    if minutes > 10080:
        await message.reply("Максимальный бан: 7 дней (10080 минут)")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Нужно ответить на сообщение пользователя.")
        return

    target = message.reply_to_message.from_user
    display = getattr(target, 'full_name', None) or (f"@{getattr(target, 'username', None)}" if getattr(target, 'username', None) else str(getattr(target, 'id', 'unknown')))
    
    # Устанавливаем время окончания бана
    import time
    ban_until = int(time.time()) + (minutes * 60)
    
    # Добавляем запись о бане в базу данных
    try:
        db.add_ban(target.id, ban_until, message.from_user.id, f"Мут на {minutes} минут")
        
        hours = minutes // 60
        mins = minutes % 60
        time_str = f"{hours} ч {mins} мин" if hours > 0 else f"{minutes} мин"
        
        await message.reply(f"🔇 Пользователю {display} выдан мут на {time_str}")
    except Exception as e:
        await message.reply(f"❌ Ошибка при выдаче бана: {e}")

# --- СИСТЕМА ПЕРЕВОДОВ ДЕНЕГ ---

async def transfer_money(sender_id: int, receiver_id: int, amount: int, sender_username: str, receiver_username: str):
    """Выполняет перевод денег: проверяет баланс ПОЛУЧАТЕЛЯ и списывает с него, отдает ОТПРАВИТЕЛЮ"""
    try:
        # Регистрируем получателя, если его нет
        receiver = db.get_user(receiver_id)
        if not receiver:
            db.ensure_user(receiver_id, receiver_username)
            receiver = db.get_user(receiver_id)
            
        # Проверяем баланс ПОЛУЧАТЕЛЯ (того, у кого просят)
        receiver_balance = float(receiver.get("dan", 0)) if receiver else 0
        if receiver_balance < amount:
            # Используем новую систему имен для отображения
            receiver_display_name = get_display_name(receiver_id, receiver_username)
            receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
            return {"success": False, "message": f"❌ У получателя недостаточно дань! У {receiver_clickable}: {format_number_beautiful(receiver_balance)}, запрошено: {format_number_beautiful(amount)}"}
            
        # Регистрируем отправителя, если его нет
        sender = db.get_user(sender_id)
        if not sender:
            db.ensure_user(sender_id, sender_username)
            
        # Выполняем перевод: отнимаем у ПОЛУЧАТЕЛЯ, добавляем ОТПРАВИТЕЛЮ
        db.add_dan(receiver_id, -amount)  # Отнимаем у того, у кого просили
        db.add_dan(sender_id, amount)     # Добавляем тому, кто просил
        
        # Отслеживаем перевод для заданий (для того кто ДАЛ деньги)
        try:
            _tasks.record_dan_transfer(receiver_id)
        except Exception as e:
            print(f"❌ Ошибка записи перевода дани для {receiver_id}: {e}")
        
        # Получаем новые балансы
        receiver_new_balance = receiver_balance - amount
        sender_new = db.get_user(sender_id)
        sender_balance = float(sender_new.get("dan", 0)) if sender_new else amount
        
        # Уведомляем отправителя (кто просил деньги)
        try:
            sender_display_name = get_display_name(sender_id, sender_username)
            receiver_display_name = get_display_name(receiver_id, receiver_username)
            receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
            
            await bot.send_message(
                sender_id,
                f"💰 Вам дали деньги!\n\n"
                f"💸 Получено: {format_number_beautiful(amount)} дань\n"
                f"👤 От: {receiver_clickable}\n"
                f"💰 Ваш баланс: {format_number_beautiful(sender_balance)} дань",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Если не удалось отправить уведомление - не критично
        
        sender_clickable = format_clickable_name(sender_id, sender_display_name)
        return {
            "success": True, 
            "message": f"✅ Деньги переданы!\n\n"
                      f"💸 Отдано: {format_number_beautiful(amount)} дань\n"
                      f"👤 Получил: {sender_clickable}\n"
                      f"💰 Ваш баланс: {format_number_beautiful(receiver_new_balance)} дань"
        }
        
    except Exception as e:
        return {"success": False, "message": f"❌ Ошибка при переводе: {e}"}

async def give_money(sender_id: int, receiver_id: int, amount: int, sender_username: str, receiver_username: str):
    """Выполняет ПОДАРОК денег: проверяет баланс ОТПРАВИТЕЛЯ и списывает с него, отдает ПОЛУЧАТЕЛЮ"""
    try:
        # Проверяем баланс ОТПРАВИТЕЛЯ (кто дает подарок)
        sender = db.get_user(sender_id)
        if not sender:
            return {"success": False, "message": "❌ Вы не зарегистрированы в боте!"}
            
        sender_balance = float(sender.get("dan", 0))
        if sender_balance < amount:
            return {"success": False, "message": f"❌ Недостаточно дань! У вас: {format_number_beautiful(sender_balance)}, нужно: {format_number_beautiful(amount)}"}
            
        # Регистрируем получателя, если его нет
        receiver = db.get_user(receiver_id)
        if not receiver:
            db.ensure_user(receiver_id, receiver_username)
            
        # Выполняем перевод: отнимаем у ОТПРАВИТЕЛЯ, добавляем ПОЛУЧАТЕЛЮ
        db.add_dan(sender_id, -amount)   # Отнимаем у того, кто дает
        db.add_dan(receiver_id, amount)  # Добавляем тому, кому дают
        
        # Отслеживаем перевод для заданий (для того кто ДАЛ деньги)
        try:
            _tasks.record_dan_transfer(sender_id)
        except Exception as e:
            print(f"❌ Ошибка записи перевода дани для {sender_id}: {e}")
        
        # Получаем новые балансы
        sender_new_balance = sender_balance - amount
        receiver_new = db.get_user(receiver_id)
        receiver_balance = float(receiver_new.get("dan", 0)) if receiver_new else amount
        
        # Уведомляем получателя (кто получил подарок)
        try:
            sender_display_name = get_display_name(sender_id, sender_username)
            receiver_display_name = get_display_name(receiver_id, receiver_username)
            sender_clickable = format_clickable_name(sender_id, sender_display_name)
            
            await bot.send_message(
                receiver_id,
                f"💰 Вам подарили деньги!\n\n"
                f"💸 Получено: {format_number_beautiful(amount)} дань\n"
                f"👤 От: {sender_clickable}\n"
                f"💰 Ваш баланс: {format_number_beautiful(receiver_balance)} дань",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Если не удалось отправить уведомление - не критично
        
        receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
        return {
            "success": True, 
            "message": f"✅ Подарок отправлен!\n\n"
                      f"💸 Подарено: {format_number_beautiful(amount)} дань\n"
                      f"👤 Получатель: {receiver_clickable}\n"
                      f"💰 Ваш баланс: {format_number_beautiful(sender_new_balance)} дань"
        }
        
    except Exception as e:
        return {"success": False, "message": f"❌ Ошибка при подарке: {e}"}

# Обработчик кнопки "Принять" перевод
@dp.callback_query(lambda c: c.data and c.data.startswith("money_accept:"))
async def handle_money_accept(callback: types.CallbackQuery):
    if not callback.from_user or not callback.data:
        return
        
    try:
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("❌ Неверные данные", show_alert=True)
            return
            
        _, sender_id_str, receiver_id_str, amount_str = parts
        sender_id = int(sender_id_str)
        receiver_id = int(receiver_id_str)
        amount = int(amount_str)
        
        # Проверяем права (только получатель может принять)
        if callback.from_user.id != receiver_id:
            await callback.answer("❌ Этот запрос не для вас!", show_alert=True)
            return
        
        # Получаем данные отправителя и получателя
        sender = db.get_user(sender_id)
        if not sender:
            await callback.message.edit_text("❌ Отправитель не найден в системе")
            await callback.answer()
            return
            
        sender_username = sender.get("username", "NoUsername")
        receiver_username = callback.from_user.username or "NoUsername"
        
        # Получаем отображаемые имена
        sender_display_name = get_display_name(sender_id, sender_username)
        receiver_display_name = get_display_name(receiver_id, receiver_username)
        sender_clickable = format_clickable_name(sender_id, sender_display_name)
        receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
        
        # Выполняем перевод
        result = await transfer_money(sender_id, receiver_id, amount, sender_username, receiver_username)
        
        if result["success"]:
            await callback.message.edit_text(
                f"✅ Запрос принят!\n\n"
                f"💸 Вы дали: {format_number_beautiful(amount)} дань\n"
                f"👤 Получил: {sender_clickable}",
                parse_mode="HTML"
            )
            
            # Уведомляем отправителя
            try:
                await bot.send_message(
                    sender_id,
                    f"✅ Ваш запрос принят!\n\n"
                    f"💸 Получено: {format_number_beautiful(amount)} дань\n"
                    f"👤 Дал: {receiver_clickable}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await callback.message.edit_text(f"❌ Ошибка при переводе:\n{result['message']}", parse_mode="HTML")
            
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

# Обработчик кнопки "Отклонить" перевод
@dp.callback_query(lambda c: c.data and c.data.startswith("money_decline:"))
async def handle_money_decline(callback: types.CallbackQuery):
    if not callback.from_user or not callback.data:
        return
        
    try:
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("❌ Неверные данные", show_alert=True)
            return
            
        _, sender_id_str, receiver_id_str, amount_str = parts
        sender_id = int(sender_id_str)
        receiver_id = int(receiver_id_str)
        amount = int(amount_str)
        
        # Проверяем права (только получатель может отклонить)
        if callback.from_user.id != receiver_id:
            await callback.answer("❌ Этот запрос не для вас!", show_alert=True)
            return
        
        # Получаем данные отправителя
        sender = db.get_user(sender_id)
        sender_username = sender.get("username", "NoUsername") if sender else "NoUsername"
        receiver_username = callback.from_user.username or "NoUsername"
        
        # Получаем отображаемые имена
        sender_display_name = get_display_name(sender_id, sender_username)
        receiver_display_name = get_display_name(receiver_id, receiver_username)
        sender_clickable = format_clickable_name(sender_id, sender_display_name)
        receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
        
        await callback.message.edit_text(
            f"❌ Запрос отклонен\n\n"
            f"💸 Сумма: {amount:,} дань\n"
            f"👤 Просил: {sender_clickable}",
            parse_mode="HTML"
        )
        
        # Уведомляем отправителя (кто просил деньги)
        try:
            await bot.send_message(
                sender_id,
                f"❌ Ваш запрос отклонен\n\n"
                f"💸 Сумма: {amount:,} дань\n"
                f"👤 Отказал: {receiver_clickable}",
                parse_mode="HTML"
            )
        except Exception:
            pass
            
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

# Команда: дать N в ответ на сообщение — перевести деньги игроку
@dp.message(lambda m: m.reply_to_message and m.text and m.text.strip().lower().startswith("дать "))
async def give_money_reply(message: types.Message):
    if not message.from_user or not message.reply_to_message or not message.reply_to_message.from_user:
        return
        
    try:
        # Парсим сумму
        if not message.text:
            return
        text = message.text.strip()
        amount_str = text[5:].strip()  # Убираем "дать "
        
        # Проверяем специальные случаи
        if amount_str.lower() in ['дань', 'деньги', 'денег', 'бабки', 'баблос']:
            await message.reply("❌ Укажите конкретную сумму!\n\n📝 Используйте: дать 100 (где 100 - нужная сумма)")
            return
            
        amount = int(amount_str)
        
        if amount <= 0:
            await message.reply("❌ Сумма должна быть положительной!")
            return
            
        # Получаем отправителя и получателя
        sender_id = message.from_user.id
        sender_username = message.from_user.username or "NoUsername"
        receiver_id = message.reply_to_message.from_user.id
        receiver_username = message.reply_to_message.from_user.username or "NoUsername"
        
        # Проверяем верификацию отправителя
        sender_verification = get_verification_level(sender_id)
        if sender_verification < 2:
            if sender_verification == 1:
                await message.reply("❌ Для перевода денег нужна верификация 2/3!\n\n🏗️ Улучшите ферму, чтобы у вас была такая возможность")
            else:
                await message.reply("❌ Для перевода денег нужна верификация 2/3!\n\n🔐 Прокачайте ферму хотя бы раз на 500+ дань для получения верификации")
            return
        
        # Проверяем что не дарят боту
        if is_bot_user(receiver_id):
            await message.reply("❌ Боту нельзя давать деньги!")
            return
        
        # Проверяем, что не отправляем самому себе
        if sender_id == receiver_id:
            await message.reply("❌ Нельзя дарить деньги самому себе!")
            return
            
        # Выполняем подарок (отправитель дает получателю)
        result = await give_money(sender_id, receiver_id, amount, sender_username, receiver_username)
        if result["success"]:
            await message.reply(result["message"], parse_mode="HTML")
        else:
            await message.reply(result["message"], parse_mode="HTML")
            
    except ValueError:
        await message.reply("❌ Неверный формат! Используйте: дать 100 (где 100 - нужная сумма)\n\n💡 Примеры:\n• дать 50\n• дать 1000\n• дать 999999")
    except Exception as e:
        await message.reply(f"❌ Ошибка при переводе: {e}")

# Команда: дай N в ответ на сообщение — перевод с подтверждением получателя
@dp.message(lambda m: m.reply_to_message and m.text and m.text.strip().lower().startswith("дай "))
async def give_money_request(message: types.Message):
    if not message.from_user or not message.reply_to_message or not message.reply_to_message.from_user:
        return
        
    try:
        # Парсим сумму
        if not message.text:
            return
        text = message.text.strip()
        amount_str = text[4:].strip()  # Убираем "дай "
        
        # Проверяем специальные случаи
        if amount_str.lower() in ['дань', 'деньги', 'денег', 'бабки', 'баблос']:
            await message.reply("❌ Укажите конкретную сумму!\n\n📝 Используйте: дай 100 (где 100 - нужная сумма)")
            return
            
        amount = int(amount_str)
        
        if amount <= 0:
            await message.reply("❌ Сумма должна быть положительной!")
            return
            
        # Получаем отправителя и получателя
        sender_id = message.from_user.id
        sender_username = message.from_user.username or "NoUsername"
        receiver_id = message.reply_to_message.from_user.id
        receiver_username = message.reply_to_message.from_user.username or "NoUsername"
        
        # Проверяем верификацию отправителя
        sender_verification = get_verification_level(sender_id)
        if sender_verification < 2:
            if sender_verification == 1:
                await message.reply("❌ Для перевода денег нужна верификация 2/3!\n\n🏗️ Улучшите ферму, чтобы у вас была такая возможность")
            else:
                await message.reply("❌ Для перевода денег нужна верификация 2/3!\n\n🔐 Прокачайте ферму хотя бы раз на 500+ дань для получения верификации")
            return
        
        # Проверяем что не дают боту
        if is_bot_user(receiver_id):
            await message.reply("❌ Боту нельзя давать деньги!")
            return
        
        # Проверяем, что не отправляем самому себе
        if sender_id == receiver_id:
            await message.reply("❌ Нельзя давать деньги самому себе!")
            return
        
        # Проверяем, что получатель зарегистрирован (но НЕ проверяем баланс заранее)
        receiver = db.get_user(receiver_id)
        if not receiver:
            db.ensure_user(receiver_id, receiver_username)
        
        # Создаем клавиатуру для получателя
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Дать", callback_data=f"money_accept:{sender_id}:{receiver_id}:{amount}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"money_decline:{sender_id}:{receiver_id}:{amount}")
            ]
        ])
        
        # Получаем красивые имена для отображения
        sender_display_name = get_display_name(sender_id, sender_username)
        receiver_display_name = get_display_name(receiver_id, receiver_username)
        sender_clickable = format_clickable_name(sender_id, sender_display_name)
        receiver_clickable = format_clickable_name(receiver_id, receiver_display_name)
        
        # Отправляем запрос получателю (у кого просят деньги)
        request_message = await bot.send_message(
            receiver_id,
            f"💰 Запрос денег!\n\n"
            f"👤 Пользователь {sender_clickable} просит у вас {format_number_beautiful(amount)} дань\n\n"
            f"Дать или отказать?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Уведомляем отправителя (кто просит деньги)
        await message.reply(f"📤 Вы попросили у {receiver_clickable} {format_number_beautiful(amount)} дань. Ждем ответа...", parse_mode="HTML")
        
    except ValueError:
        await message.reply("❌ Неверный формат! Используйте: дай 100 (где 100 - нужная сумма)\n\n💡 Примеры:\n• дай 50\n• дай 1000\n• дай 999999")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

# --- Обработка кнопок костей ---
@dp.callback_query(lambda c: c.data and c.data.startswith('dice_accept:'))
async def callback_dice_accept(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    # Не отправляем быстрый ответ, чтобы show_alert работал ниже
    await betcosty.handle_dice_accept(callback)

@dp.callback_query(lambda c: c.data and c.data.startswith('dice_decline:'))
async def callback_dice_decline(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    # Не отправляем быстрый ответ, чтобы show_alert работал ниже
    await betcosty.handle_dice_decline(callback)

# --- Обработка кнопок батла (теперь кнопки реально принимают/отклоняют батл) ---
@dp.callback_query(lambda c: c.data and c.data.startswith('battle_button_accept:'))
async def callback_battle_accept(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    await callback.answer()  # быстрый ответ Telegram
    await battles.handle_accept_button(callback)

@dp.callback_query(lambda c: c.data and c.data.startswith('battle_button_decline:'))
async def callback_battle_decline(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    await callback.answer()  # быстрый ответ Telegram
    await battles.handle_decline_button(callback)

@dp.callback_query(lambda c: c.data and c.data.startswith('battle_button_'))
async def callback_battle_button(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    await callback.answer()  # быстрый ответ Telegram
    data = callback.data or ""
    if data.startswith("battle_button_accept:"):
        await battles.handle_accept_button(callback)
    elif data.startswith("battle_button_decline:"):
        await battles.handle_decline_button(callback)

# Callback handler for top-up and exchange (не ловит батловые кнопки)
@dp.callback_query(lambda c: not (c.data and c.data.startswith('battle_button_')))
async def dodep_callback(callback: types.CallbackQuery):
    if not getattr(callback, 'message', None) or not getattr(callback, 'from_user', None):
        return
    # Не отправляем быстрый ответ, чтобы show_alert работал ниже
    data = callback.data or ""
    user_id = callback.from_user.id
    if data == "free_50":
        if db.can_get_free(user_id):
            db.grant_free(user_id, 99)
            await callback.answer("Вы получили 99 Дань 🪙 (раз в 7 дней).", show_alert=True)
            # Сообщение с кнопками не удаляем
        else:
            # вычисляем сколько осталось
            user = db.get_user(user_id)
            now = int(time.time())
            last = user["last_free"] if user else 0
            cooldown = 7 * 24 * 3600
            left = cooldown - (now - last)
            if left < 0:
                left = 0
            days = left // 86400
            hours = (left % 86400) // 3600
            minutes = (left % 3600) // 60
            msg = "Free ещё не доступен. До следующего получения: "
            if days > 0:
                msg += f"{days} д. "
            if hours > 0 or days > 0:
                msg += f"{hours} ч. "
            msg += f"{minutes} мин."
            await callback.answer(msg, show_alert=True)
        return
    if data.startswith("buystars:"):
        try:
            _, stars, dan = data.split(":")
            stars = int(stars)
            dan = int(dan)
        except Exception:
            await callback.answer("Ошибка покупки.", show_alert=True)
            return
        
        # Выставляем счет за Telegram Stars
        try:
            prices = [LabeledPrice(label=f"{dan:,} Дань", amount=stars)]
            await bot.send_invoice(
                chat_id=user_id,
                title=f"Покупка {dan:,} Дань",
                description=f"Пополнение счета на {dan:,.2f} Дань за {stars}⭐️ Telegram Stars",
                payload=f"buy_dan_stars:{stars}:{dan}",
                provider_token="",  # пусто для Stars
                currency="XTR",
                prices=prices
            )
            await callback.answer(f"Счёт на {stars}⭐ выставлен!", show_alert=True)
        except Exception as e:
            print(f"Ошибка выставления счета: {e}")
            await callback.answer("Ошибка: не удалось выставить счёт. Напишите боту в личные сообщения.", show_alert=True)
        return
    if data == "close_dodep":
        await callback.message.delete()
        await callback.answer("✅ Меню закрыто")
        return
    # --- Кнопка "Собрать дань" - перевод со склада на баланс ---
    from ferma import transfer_dan_to_balance, get_farm, get_farm_leaderboard_position
    if data == "collect_ferma":
        # Переводим дань со склада фермы на баланс пользователя
        collected = transfer_dan_to_balance(user_id)
        
        if collected > 0:
            # Отслеживаем сбор дани с фермы для заданий
            try:
                _tasks.record_farm_collect(user_id)
            except Exception as e:
                print(f"❌ Ошибка записи сбора фермы для {user_id}: {e}")
            
            # Получаем обновленные данные
            farm = get_farm(user_id)
            place = get_farm_leaderboard_position(user_id)
            user_row = db.get_user(user_id)
            bal = user_row["dan"] if user_row else 0
            bal = float(bal)
            bal = 0.00 if abs(bal) < 0.005 else round(bal, 2)
            bal = format_number_beautiful(bal)
            
            collected = float(collected)
            collected = 0.00 if abs(collected) < 0.005 else round(collected, 2)
            collected = format_number_beautiful(collected)
            
            hour = datetime.datetime.now().hour
            greeting = "Доброе утро, фермер!" if 6 <= hour < 18 else "Доброй ночи, фермер!"
            photo_path = "C:/BotKruz/ChatBotKruz/photo/fermaday.png" if 6 <= hour < 18 else "C:/BotKruz/ChatBotKruz/photo/fermanight.png"
            
            # Данные склада после сбора
            stored_dan = farm['stored_dan'] if 'stored_dan' in farm else 0
            stored_dan = float(stored_dan)
            stored_dan = 0.00 if abs(stored_dan) < 0.005 else round(stored_dan, 2)
            stored_dan_text = f"{stored_dan:.2f}"
            
            # Проверяем активен ли бесконечный склад
            infinite_storage = db.get_user_effect(user_id, "infinite_storage")
            if infinite_storage:
                remaining_time = infinite_storage['expires_at'] - int(time.time())
                if remaining_time > 0:
                    days = remaining_time // 86400
                    hours = (remaining_time % 86400) // 3600
                    minutes = (remaining_time % 3600) // 60
                    storage_info = f"📮 Бесконечный склад активен: {days}д {hours}ч {minutes}м"
                else:
                    storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"
            else:
                storage_info = f"📮 Вместимость склада: {farm['warehouse_capacity']}"
            
            # Доход и иконки животных
            from ferma import get_user_farm_animals, is_animal_active, ANIMALS_CONFIG
            animals = get_user_farm_animals(user_id)
            animals_income = 0
            counts = {}
            for _, a in animals.items():
                a_type = a['type']
                counts[a_type] = counts.get(a_type, 0) + 1
                if is_animal_active(a):
                    cfg = ANIMALS_CONFIG.get(a_type, {})
                    animals_income += cfg.get('income_per_hour', 0)
            icons_map = { 'cow': '🐮', 'chicken': '🐔' }
            icons = ''.join(icons_map.get(t, '') * n for t, n in counts.items())
            income_text = (
                f"🌾 Доход в час: {farm['income_per_hour']} (+{animals_income} {icons})"
                if icons else f"🌾 Доход в час: {farm['income_per_hour']} (+0)"
            )

            reply = (
                f"👨‍🌾 🌾 {greeting}\n\n"
                f"🏡 Уровень фермы: {farm['level']}\n"
                f"{income_text}\n"
                f"{storage_info}\n"
                f"📊 Место в топе по доходу: {place}\n\n"
                f"✅ Собрано со склада: +{collected} Дань 🪙\n"
                f"🌱 Дань на складе фермы: {stored_dan_text}\n"
                f"🪙 Дань на балансе: {bal}"
            )
            
            # Получаем стоимость следующего улучшения
            from ferma import get_next_upgrade_cost
            next_cost = get_next_upgrade_cost(user_id)
            
            if next_cost is not None:
                # Форматируем стоимость красиво
                cost_formatted = format_number_beautiful(next_cost)
                upgrade_text = f"📈 Улучшить ({cost_formatted})"
            else:
                upgrade_text = "📈 Макс. уровень"
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=upgrade_text, callback_data="upgrade_ferma")],
                [InlineKeyboardButton(text="🐄 Животные", callback_data="farm_animals")],
                [InlineKeyboardButton(text="📥 Собрать дань", callback_data="collect_ferma")],
                [InlineKeyboardButton(text="⬅️ В МЕНЮ", callback_data="open_game_menu")]
            ])
            
            try:
                media = types.InputMediaPhoto(media=FSInputFile(photo_path), caption=reply)
                await callback.message.edit_media(media=media, reply_markup=kb)
            except Exception as e:
                await callback.answer("Ошибка обновления", show_alert=False)
        else:
            await callback.answer("На складе нет дани для сбора!", show_alert=True)
        return


# Debug fallback: log any callback_query that wasn't handled and ack it so user sees a response
@dp.callback_query()
async def _debug_callback_any(callback: types.CallbackQuery):
    try:
        uid = getattr(callback.from_user, 'id', None)
        data = getattr(callback, 'data', None)
        print(f"[main] debug callback received from {uid}: {data}")
        # acknowledge so UI shows it's handled
        try:
            await callback.answer()
        except Exception:
            pass
    except Exception:
        pass

# Функции для работы с счетчиком игр в БД
def get_games_count_from_db():
    """Получить количество игр за сегодня из БД"""
    try:
        today = datetime.date.today().isoformat()
        import sqlite3
        import os
        
        # Используем тот же путь, что и в database.py
        DB_FOLDER = os.path.join(os.path.dirname(__file__), "database")
        DB_PATH = os.path.join(DB_FOLDER, "game_bot.db")
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Создаем таблицу если не существует
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_games_count (
                date TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        ''')
        
        # Получаем количество игр за сегодня
        cursor.execute('SELECT count FROM daily_games_count WHERE date = ?', (today,))
        result = cursor.fetchone()
        
        conn.close()
        return result['count'] if result else 0
    except Exception as e:
        print(f"Ошибка получения счетчика игр: {e}")
        return 0

def increment_games_count():
    """Увеличить счетчик игр за сегодня в БД"""
    try:
        today = datetime.date.today().isoformat()
        import sqlite3
        import os
        
        # Используем тот же путь, что и в database.py
        DB_FOLDER = os.path.join(os.path.dirname(__file__), "database")
        DB_PATH = os.path.join(DB_FOLDER, "game_bot.db")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Создаем таблицу если не существует
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_games_count (
                date TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        ''')
        
        # Увеличиваем счетчик или создаем запись
        cursor.execute('''
            INSERT INTO daily_games_count (date, count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET count = count + 1
        ''', (today,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка увеличения счетчика игр: {e}")

def cleanup_old_games_count():
    """Очистка старых записей счетчика (старше 1 дня)"""
    try:
        week_ago = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        import sqlite3
        import os
        
        # Используем тот же путь, что и в database.py
        DB_FOLDER = os.path.join(os.path.dirname(__file__), "database")
        DB_PATH = os.path.join(DB_FOLDER, "game_bot.db")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM daily_games_count WHERE date < ?', (week_ago,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка очистки старых записей: {e}")

import asyncio

# ---existing code---
def safe_edit_text(message, *args, **kwargs):
    import asyncio
    from aiogram.exceptions import TelegramRetryAfter
    async def inner():
        try:
            await message.edit_text(*args, **kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.edit_text(*args, **kwargs)
            except Exception:
                pass
        except Exception:
            pass
    return asyncio.create_task(inner())

def safe_edit_reply_markup(message, *args, **kwargs):
    import asyncio
    from aiogram.exceptions import TelegramRetryAfter
    async def inner():
        try:
            await message.edit_reply_markup(*args, **kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.edit_reply_markup(*args, **kwargs)
            except Exception:
                pass
        except Exception:
            pass
    return asyncio.create_task(inner())

from PIL import Image, ImageDraw, ImageFont

def make_stat_image(count, base_path, out_path):
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Файл для фона не найден: {base_path}")
    img = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    text = f"Сегодня сыграно {count} раз"
    font_path = "C:/Windows/Fonts/arial.ttf"
    try:
        font = ImageFont.truetype(font_path, 48)
    except Exception:
        font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (img.width - text_width) // 2
    y = (img.height - text_height) // 2
    draw.text((x+2, y+2), text, font=font, fill=(0,0,0,128))
    draw.text((x, y), text, font=font, fill=(255,255,255,255))
    img.save(out_path)

def _get_callback_message(cb: types.CallbackQuery):
    """Return a types.Message from a CallbackQuery or None if not available."""
    msg = getattr(cb, 'message', None)
    if not msg:
        return None
    # Help the type checker: cast to Message for attribute access
    from typing import cast
    return cast(types.Message, msg)


async def edit_callback_media(cb: types.CallbackQuery, media, reply_markup=None):
    """Safely edit media on a callback's message. Returns True if succeeded."""
    msg = _get_callback_message(cb)
    if not msg:
        return False
    try:
        await msg.edit_media(media=media, reply_markup=reply_markup)
        return True
    except Exception:
        # Fallback: try to update caption/text instead
        try:
            # If media has caption attribute, use it
            caption = getattr(media, 'caption', None) or ''
            await safe_edit_text_or_caption(msg, caption, reply_markup)
            return True
        except Exception:
            return False


async def edit_callback_text(cb: types.CallbackQuery, text, reply_markup=None, parse_mode=None):
    msg = _get_callback_message(cb)
    if not msg:
        return False
    try:
        if parse_mode:
            await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception:
        try:
            await msg.edit_reply_markup(reply_markup=reply_markup)
            return True
        except Exception:
            return False

# Планировщик задач для лотереи
import datetime
import asyncio
from threading import Timer

class LotteryScheduler:
    def __init__(self):
        self.is_running = False
        self.timer = None
        self.loop = None
        self.backup_timer = None  # Дополнительный таймер для проверки
    
    def calculate_next_lottery_time(self):
        """Вычисляет время до следующего розыгрыша (21:00 по киевскому времени)"""
        import pytz
        
        kyiv_tz = pytz.timezone('Europe/Kiev')
        utc_tz = pytz.UTC
        
        now_utc = datetime.datetime.now(utc_tz)
        now_kyiv = now_utc.astimezone(kyiv_tz)
        
        # Определяем время следующего розыгрыша (21:00 по Киеву)
        target_kyiv = now_kyiv.replace(hour=21, minute=0, second=0, microsecond=0)

        # Если уже прошло 21:00, то следующий розыгрыш завтра
        if now_kyiv >= target_kyiv:
            target_kyiv = target_kyiv + datetime.timedelta(days=1)
        
        # Конвертируем в UTC для планировщика
        target_utc = target_kyiv.astimezone(utc_tz)
        
        # Вычисляем время ожидания в секундах
        wait_seconds = (target_utc - now_utc).total_seconds()
        
        print(f"⏰ Следующий розыгрыш через {wait_seconds/3600:.1f} ч")
        
        return wait_seconds
    
    async def run_lottery_draw(self):
        """Выполняет розыгрыш лотереи"""
        import pytz
        
        kyiv_tz = pytz.timezone('Europe/Kiev')
        now_utc = datetime.datetime.now(pytz.UTC)
        now_kyiv = now_utc.astimezone(kyiv_tz)
        
        # Проверяем, что розыгрыш запускается в правильное время (21:00-21:10)
        current_hour = now_kyiv.hour
        current_minute = now_kyiv.minute
        
        if current_hour == 21 and current_minute <= 10:
            pass  # Время подходит
        elif current_hour > 21 or (current_hour == 21 and current_minute > 10):
            # Проверяем, не был ли розыгрыш сегодня
            today_iso = now_kyiv.date().isoformat()
            conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT status FROM lottery_draws WHERE draw_date = ?', (today_iso,))
            row = cursor.fetchone()
            conn.close()
            if row:
                print(f"✅ Розыгрыш за {today_iso} в порядке")
                self.schedule_next_draw()
                return
        else:
            # Слишком рано, пробуем через час
            self.timer = Timer(3600, self._timer_callback)
            self.timer.start()
            return
        
        try:
            winner_info, total_tickets, prize_pool = conduct_lottery_draw()
            
            if winner_info == "no_participants_high_prize":
                await send_missed_lottery_notification(prize_pool)
            elif winner_info:
                await send_lottery_results(winner_info, total_tickets, prize_pool)
            
            # Очищаем старые билеты
            cleanup_old_tickets()
            
        except Exception as e:
            print(f"❌ Ошибка розыгрыша: {e}")
        
        # Генерация бонуса для следующего дня
        try:
            import pytz
            kyiv_tz = pytz.timezone('Europe/Kiev')
            now_utc = datetime.datetime.now(pytz.UTC)
            now_kyiv = now_utc.astimezone(kyiv_tz)
            tomorrow_kyiv = (now_kyiv + datetime.timedelta(days=1)).date()
            next_bonus = generate_deterministic_lottery_bonus_for_date(tomorrow_kyiv)
            set_stored_lottery_bonus_for_date(tomorrow_kyiv.isoformat(), next_bonus)
        except Exception:
            pass

        self.schedule_next_draw()
    
    def schedule_next_draw(self):
        """Планирует следующий розыгрыш"""
        if not self.is_running:
            return
            
        wait_seconds = self.calculate_next_lottery_time()
        
        # Планируем следующий розыгрыш
        self.timer = Timer(wait_seconds, self._timer_callback)
        self.timer.start()
        
        # ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: Запускаем резервный таймер на каждый час для проверки
        if self.backup_timer:
            self.backup_timer.cancel()
        self.backup_timer = Timer(3600, self._backup_check_callback)
        self.backup_timer.start()
    
    def _backup_check_callback(self):
        """Резервная проверка раз в час"""
        if self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self.check_missed_lottery(), self.loop)
                if self.is_running:
                    self.backup_timer = Timer(3600, self._backup_check_callback)
                    self.backup_timer.start()
            except Exception as e:
                print(f"❌ Ошибка резервной проверки: {e}")
    
    def _timer_callback(self):
        """Callback для Timer - запускает корутину в правильном контексте"""
        if self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self.run_lottery_draw(), self.loop)
            except Exception as e:
                print(f"❌ Ошибка запуска розыгрыша: {e}")
    
    async def check_missed_lottery(self):
        """Проверяет, не был ли пропущен розыгрыш за сегодня"""
        import pytz
        
        kyiv_tz = pytz.timezone('Europe/Kiev')
        now_utc = datetime.datetime.now(pytz.UTC)
        now_kyiv = now_utc.astimezone(kyiv_tz)
        
        # Проверяем только если уже после 21:00
        if now_kyiv.hour >= 21:
            today_iso = now_kyiv.date().isoformat()
            
            conn = sqlite3.connect(MESSAGES_DB_FILE_FILE)
            cursor = conn.cursor()
            
            # Проверяем, есть ли активные билеты на сегодня
            cursor.execute('''
                SELECT COUNT(*) FROM lottery_tickets 
                WHERE draw_date = ? AND status = 'active'
            ''', (today_iso,))
            active_tickets = cursor.fetchone()[0]
            
            # Проверяем, был ли розыгрыш
            cursor.execute('SELECT status FROM lottery_draws WHERE draw_date = ?', (today_iso,))
            draw_result = cursor.fetchone()
            
            conn.close()
            
            if active_tickets > 0 and not draw_result:
                print(f"🚨 ОБНАРУЖЕН ПРОПУЩЕННЫЙ РОЗЫГРЫШ ЗА {today_iso}!")
                print(f"📊 Активных билетов: {active_tickets}")
                print(f"⚡ Запускаем экстренный розыгрыш...")
                await self.run_lottery_draw()
            else:
                print(f"✅ Розыгрыш за {today_iso} в порядке")
    
    def start(self, loop=None):
        """Запускает планировщик"""
        if self.is_running:
            return
            
        # Сохраняем ссылку на event loop
        if loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                print("❌ Нет активного event loop для планировщика лотереи")
                return
        else:
            self.loop = loop
            
        self.is_running = True
        
        # Проверяем, не пропущен ли розыгрыш за сегодня
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.check_missed_lottery(), self.loop)
        
        self.schedule_next_draw()
    
    def stop(self):
        """Останавливает планировщик"""
        self.is_running = False
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.backup_timer:
            self.backup_timer.cancel()
            self.backup_timer = None
        print("🛑 Планировщик лотереи остановлен")

# Глобальный экземпляр планировщика
lottery_scheduler = LotteryScheduler()

if __name__ == "__main__":
    print("Bot started...")
    
    print("🔄 Инициализация базы данных...")
    try:
        init_shop()
    except Exception as e:
        print(f"⚠️ Ошибка инициализации магазина: {e}")
    
    print("🔄 Инициализация реферальной системы...")
    try:
        create_tables()
    except Exception as e:
        print(f"⚠️ Ошибка инициализации реферальной системы: {e}")
    
    print("🔄 Инициализация счетчика игр...")
    try:
        get_games_count_from_db()
        cleanup_old_games_count()
    except Exception as e:
        print(f"⚠️ Ошибка инициализации счетчика игр: {e}")
    
    print("🔄 Инициализация лотереи...")
    try:
        init_tickets_db()
    except Exception as e:
        print(f"⚠️ Ошибка инициализации билетов: {e}")
    
    print("🔄 Настройка таблицы сообщений...")
    def ensure_ref_count_column():
        # Реализация для SQLite: создаёт таблицу messages, если её нет, и добавляет столбец ref_count, если его нет
        import sqlite3
        db_path = 'MESSAGES_DB_FILE'  # Измените путь к вашей базе, если нужно
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Создаём таблицу, если её нет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                ref_count INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        # Проверяем, есть ли столбец ref_count (на случай, если таблица была создана раньше без него)
        cursor.execute("PRAGMA table_info(messages)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'ref_count' not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN ref_count INTEGER DEFAULT 0")
            conn.commit()
        conn.close()

    ensure_ref_count_column()

    print("🔄 Загрузка игровых модулей...")
    lazy_import_heavy_modules()
    import_game_modules()
    
    print("✅ Инициализация завершена\n")
   
    # Фоновая задача для проверки таймаутов арены
    async def arena_timeout_checker():
        """Проверяет таймауты поиска и истекшие игры в арене"""
        while True:
            try:
                # 1. Проверяем таймауты поиска (1 час)
                timed_out_players = arena.check_arena_timeouts()
                
                for user_id in timed_out_players:
                    try:
                        # Удаляем из очереди
                        player_data = None
                        for i, p in enumerate(arena.arena_queue):
                            if p['user_id'] == user_id:
                                player_data = arena.arena_queue.pop(i)
                                break
                        
                        if not player_data:
                            continue
                        
                        # Отправляем сообщение о неудачном поиске
                        text = arena.get_search_failed_message()
                        
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔍 Попробовать снова", callback_data="arena_find_match")],
                            [InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="arena_play_with_bot")],
                            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")]
                        ])
                        
                        await bot.send_message(
                            chat_id=user_id,
                            text=text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        
                    except Exception as e:
                        print(f"Ошибка обработки таймаута поиска для {user_id}: {e}")
                
                # 2. Проверяем истекшие игры (5 минут)
                expired_games = arena.check_expired_games()
                
                for game_id in expired_games:
                    try:
                        # Завершаем игру по таймауту
                        result_data = arena.end_arena_game(game_id)
                        if result_data:
                            await send_arena_game_result(result_data)
                            print(f"🕐 Игра {game_id} завершена по таймауту")
                        
                    except Exception as e:
                        print(f"Ошибка завершения истекшей игры {game_id}: {e}")
                
                await asyncio.sleep(30)  # Проверяем каждые 30 секунд для более точного контроля времени
                
            except Exception as e:
                print(f"Ошибка в arena_timeout_checker: {e}")
                await asyncio.sleep(60)
    
    # Функция удалена - теперь обновления происходят мгновенно
    
    async def daily_cleanup_task():
        """Фоновая задача для ежедневной очистки старых записей в конце дня"""
        while True:
            try:
                # Ждем до 18:59 (конец дня)
                now = datetime.datetime.now()
                end_of_day = datetime.datetime.combine(now.date(), datetime.time(8, 00))

                # Если уже прошло 8:00 сегодня, то ждем до 8:00 завтра
                if now >= end_of_day:
                    end_of_day = datetime.datetime.combine(now.date() + datetime.timedelta(days=7), datetime.time(8, 00))

                seconds_until_cleanup = (end_of_day - now).total_seconds()
                
                await asyncio.sleep(seconds_until_cleanup)
                
                cleanup_old_games_count()
                
                # Ждем минуту, чтобы не запускать очистку несколько раз
                await asyncio.sleep(60)
                
            except Exception as e:
                print(f"❌ Ошибка в задаче очистки: {e}")
                # Ждем час и пробуем снова
                await asyncio.sleep(3600)
    
    async def main():
        # Регистрируем обработчики арены (передаем bot и dp в модуль)
        arena.register_arena_handlers(bot, dp)
        
        # Подключаем роутер игр
        from plugins.games import setup_games_router
        games_router = setup_games_router()
        dp.include_router(games_router)
        print("✅ Роутер игр подключен")
        
        # Подключаем роутер кейсов
        from plugins.games.case_system import setup_case_router
        case_router = setup_case_router()
        dp.include_router(case_router)
        print("✅ Роутер кейсов подключен")
        
        # Запускаем планировщик лотереи
        current_loop = asyncio.get_running_loop()
        lottery_scheduler.start(current_loop)
        
        # Запускаем фоновые задачи
        asyncio.create_task(arena_timeout_checker())
        asyncio.create_task(daily_cleanup_task())
        
        print("✅ Бот запущен\n")
        
        try:
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            print("\n🛑 Остановка бота")
        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
        finally:
            lottery_scheduler.stop()
            await bot.session.close()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")

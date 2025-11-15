"""
Games Router - Централизованный роутер для всех игровых модулей
Обрабатывает команды и callback-и для: арены, сапера, клада, боулинга, битв, костей, крестиков-ноликов
"""

import sys
import os
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

# Добавляем корневую директорию в путь для импорта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Импорты игровых модулей
from plugins.games import arena, battles, betcosty, bowling, case_system, clad, saper, tic_tac_toe

# Импорт основных модулей
import database as db

# Создаем роутер для игр
games_router = Router(name="games")


# ==============================================
# ARENA (PvP Арена)
# ==============================================

@games_router.callback_query(lambda c: c.data == "arena_find_match")
async def arena_find_match_callback(callback: CallbackQuery):
    """Поиск матча в арене"""
    from main import arena_find_match_handler
    await arena_find_match_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_cancel_search")
async def arena_cancel_search_callback(callback: CallbackQuery):
    """Отмена поиска матча"""
    from main import arena_cancel_search_handler
    await arena_cancel_search_handler(callback)


@games_router.callback_query(lambda c: c.data.startswith("arena_action:"))
async def arena_action_callback(callback: CallbackQuery):
    """Действия в арене"""
    from main import arena_action_handler
    await arena_action_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_leaderboard")
async def arena_leaderboard_callback(callback: CallbackQuery):
    """Таблица лидеров арены"""
    from main import arena_leaderboard_handler
    await arena_leaderboard_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_return_to_game")
async def arena_return_to_game_callback(callback: CallbackQuery):
    """Возврат к игре в арене"""
    from main import arena_return_to_game_handler
    await arena_return_to_game_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_back_to_menu")
async def arena_back_to_menu_callback(callback: CallbackQuery):
    """Возврат в меню арены"""
    from main import arena_back_to_menu_handler
    await arena_back_to_menu_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_my_stats")
async def arena_my_stats_callback(callback: CallbackQuery):
    """Статистика игрока в арене"""
    from main import arena_my_stats_handler
    await arena_my_stats_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_help")
async def arena_help_callback(callback: CallbackQuery):
    """Справка по арене"""
    from main import arena_help_handler
    await arena_help_handler(callback)


@games_router.callback_query(lambda c: c.data == "arena_play_with_bot")
async def arena_play_with_bot_callback(callback: CallbackQuery):
    """Игра с ботом в арене"""
    from main import arena_play_with_bot_handler
    await arena_play_with_bot_handler(callback)


# ==============================================
# SAPER (Сапёр)
# ==============================================

@games_router.callback_query(F.data.startswith("saper_"))
async def saper_callback(callback: CallbackQuery):
    """Обработка всех callback-ов сапёра"""
    await saper.saper_callback_handler(callback)


@games_router.callback_query(lambda c: c.data == "saper_repeat")
async def saper_repeat_callback(callback: CallbackQuery):
    """Повтор игры в сапёра"""
    from main import saper_repeat_handler
    await saper_repeat_handler(callback)


# ==============================================
# CLAD (Клад)
# ==============================================

@games_router.callback_query(lambda c: c.data and c.data.startswith("repeat_clad:"))
async def repeat_clad_callback(callback: CallbackQuery):
    """Повтор игры в клад"""
    from main import repeat_clad_handler
    await repeat_clad_handler(callback)


@games_router.callback_query(lambda c: c.data and c.data.startswith("clad:"))
async def clad_callback(callback: CallbackQuery):
    """Обработка действий в кладе"""
    from main import clad_handler
    await clad_handler(callback)


# ==============================================
# BOWLING (Боулинг)
# ==============================================

@games_router.callback_query(lambda c: c.data and c.data.startswith("bowling_choice:"))
async def bowling_choice_callback(callback: CallbackQuery):
    """Выбор исхода в боулинге"""
    from main import bowling_choice_handler
    await bowling_choice_handler(callback)


@games_router.callback_query(lambda c: c.data and c.data == "bowling_cancel")
async def bowling_cancel_callback(callback: CallbackQuery):
    """Отмена игры в боулинг"""
    from main import bowling_cancel_handler
    await bowling_cancel_handler(callback)


@games_router.callback_query(lambda c: c.data and c.data.startswith("bowling_repeat:"))
async def bowling_repeat_callback(callback: CallbackQuery):
    """Повтор игры в боулинг"""
    from main import bowling_repeat_handler
    await bowling_repeat_handler(callback)


# ==============================================
# DICE BATTLES (Битвы на костях)
# ==============================================

@games_router.callback_query(lambda c: c.data and c.data.startswith('dice_accept:'))
async def dice_accept_callback(callback: CallbackQuery):
    """Принятие вызова на кости"""
    await betcosty.handle_dice_accept(callback)


@games_router.callback_query(lambda c: c.data and c.data.startswith('dice_decline:'))
async def dice_decline_callback(callback: CallbackQuery):
    """Отказ от вызова на кости"""
    await betcosty.handle_dice_decline(callback)


# ==============================================
# PVP BATTLES (PvP Битвы)
# ==============================================

@games_router.callback_query(lambda c: c.data and c.data.startswith('battle_button_accept:'))
async def battle_accept_callback(callback: CallbackQuery):
    """Принятие вызова на батл"""
    await battles.handle_accept_button(callback)


@games_router.callback_query(lambda c: c.data and c.data.startswith('battle_button_decline:'))
async def battle_decline_callback(callback: CallbackQuery):
    """Отказ от вызова на батл"""
    await battles.handle_decline_button(callback)


# ==============================================
# CASE SYSTEM (Система кейсов)
# ==============================================

@games_router.callback_query(lambda c: c.data == "close_case")
async def close_case_callback(callback: CallbackQuery):
    """Закрытие окна кейса"""
    from main import close_case_handler
    await close_case_handler(callback)


# ==============================================
# Функция настройки роутера
# ==============================================

def setup_games_router():
    """
    Возвращает настроенный роутер для подключения к главному диспетчеру
    """
    return games_router


# Экспорт для удобного доступа
__all__ = ['games_router', 'setup_games_router']

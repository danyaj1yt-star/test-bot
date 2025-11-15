"""
Games Plugin Package
Содержит все игровые модули бота
"""

# Экспортируем основные компоненты для удобного импорта
from .games_router import setup_games_router

# Lazy imports - модули будут импортированы при обращении
__all__ = [
    'setup_games_router'
]

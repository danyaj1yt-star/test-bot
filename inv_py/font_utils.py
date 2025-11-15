"""
Утилиты для работы со шрифтами - поиск лучших шрифтов с поддержкой русского, английского и эмодзи
"""
import os
from PIL import ImageFont
from typing import Optional

def find_best_font(size: int = 12) -> ImageFont.FreeTypeFont:
    """
    Находит лучший шрифт с поддержкой русского, английского и эмодзи
    Приоритет отдается шрифтам в стиле iPhone
    """
    # Список шрифтов в порядке приоритета (лучшие первые)
    font_candidates = [
        # Эмодзи шрифты Windows (лучшая поддержка эмодзи)
        "C:/Windows/Fonts/seguiemj.ttf",  # Segoe UI Emoji - основной шрифт эмодзи Windows
        "C:/Windows/Fonts/NotoColorEmoji.ttf",  # Noto Color Emoji если установлен
        
        # Системные шрифты с хорошей поддержкой Unicode
        "C:/Windows/Fonts/segoeui.ttf",   # Segoe UI - основной шрифт Windows
        "C:/Windows/Fonts/calibri.ttf",   # Calibri - хорошая поддержка Unicode
        "C:/Windows/Fonts/tahoma.ttf",    # Tahoma - отличная поддержка кириллицы
        
        # Старые надежные шрифты
        "C:/Windows/Fonts/arial.ttf",     # Arial - базовая поддержка
        "C:/Windows/Fonts/verdana.ttf",   # Verdana - хорошая читаемость
    ]
    
    for font_path in font_candidates:
        try:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, size)
                print(f"✅ Используем шрифт: {font_path}")
                return font
        except Exception as e:
            print(f"⚠️ Ошибка загрузки {font_path}: {e}")
            continue
    
    # Fallback к системному шрифту
    try:
        font = ImageFont.load_default()
        print("⚠️ Используем системный шрифт по умолчанию")
        return font
    except Exception:
        # Совсем крайний случай
        return None

def get_emoji_font(size: int = 12) -> Optional[ImageFont.FreeTypeFont]:
    """
    Специально для эмодзи - ищет шрифт с лучшей поддержкой эмодзи
    """
    emoji_fonts = [
        "C:/Windows/Fonts/seguiemj.ttf",  # Segoe UI Emoji
        "C:/Windows/Fonts/NotoColorEmoji.ttf",  # Noto Color Emoji
        "C:/Windows/Fonts/AppleColorEmoji.ttc",  # Apple шрифт эмодзи если есть
    ]
    
    for font_path in emoji_fonts:
        try:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    
    return None

def get_composite_font_config(base_size: int = 12) -> dict:
    """
    Возвращает конфигурацию составного шрифта для разных типов текста
    """
    return {
        'main': find_best_font(base_size),           # Основной текст
        'emoji': get_emoji_font(base_size),          # Эмодзи
        'large': find_best_font(int(base_size * 2.25)),  # Крупный текст (номера слотов)
        'small': find_best_font(max(8, int(base_size * 0.8))),  # Мелкий текст
    }

def test_font_support():
    """
    Тестирует поддержку различных символов в найденных шрифтах
    """
    print("🔍 Тестирование шрифтов:")
    
    test_strings = [
        "Hello World",      # Английский
        "Привет мир",       # Русский
        "💰🏛️⏰📦✨",        # Эмодзи
        "x50 по 5💰/шт",    # Смешанный текст
    ]
    
    fonts = get_composite_font_config()
    
    for font_name, font_obj in fonts.items():
        if font_obj:
            print(f"\n📝 {font_name.upper()} шрифт:")
            for test_str in test_strings:
                try:
                    # Пытаемся измерить текст (косвенная проверка поддержки)
                    from PIL import Image, ImageDraw
                    test_img = Image.new('RGB', (100, 50), 'white')
                    test_draw = ImageDraw.Draw(test_img)
                    bbox = test_draw.textbbox((0, 0), test_str, font=font_obj)
                    print(f"  ✅ '{test_str}' - поддерживается")
                except Exception as e:
                    print(f"  ❌ '{test_str}' - ошибка: {e}")

if __name__ == "__main__":
    test_font_support()
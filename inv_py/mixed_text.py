"""
Модуль для продвинутого рендеринга текста с эмодзи
"""
from PIL import Image, ImageDraw, ImageFont
import os
import re
from typing import Tuple, Optional

def get_mixed_fonts(base_size: int = 12) -> dict:
    """
    Возвращает словарь с оптимальными шрифтами для разных типов текста
    """
    fonts = {}
    
    # Основной шрифт для текста (латиница, кириллица, цифры)
    text_candidates = [
        "C:/Windows/Fonts/segoeui.ttf",    # Segoe UI - четкий, современный
        "C:/Windows/Fonts/tahoma.ttf",     # Tahoma - отличная кириллица
        "C:/Windows/Fonts/calibri.ttf",   # Calibri - хорошая читаемость
        "C:/Windows/Fonts/arial.ttf",     # Arial - универсальный
    ]
    
    # Эмодзи шрифт
    emoji_candidates = [
        "C:/Windows/Fonts/seguiemj.ttf",  # Segoe UI Emoji
        "C:/Windows/Fonts/NotoColorEmoji.ttf",  # Noto Color Emoji
    ]
    
    # Находим лучший текстовый шрифт
    fonts['text'] = None
    for candidate in text_candidates:
        try:
            if os.path.exists(candidate):
                fonts['text'] = ImageFont.truetype(candidate, base_size)
                break
        except Exception:
            continue
    
    # Находим лучший эмодзи шрифт  
    fonts['emoji'] = None
    for candidate in emoji_candidates:
        try:
            if os.path.exists(candidate):
                fonts['emoji'] = ImageFont.truetype(candidate, base_size)
                break
        except Exception:
            continue
    
    # Fallback
    if fonts['text'] is None:
        fonts['text'] = ImageFont.load_default()
    if fonts['emoji'] is None:
        fonts['emoji'] = fonts['text']
        
    return fonts

def has_emoji(text: str) -> bool:
    """
    Проверяет, содержит ли текст эмодзи
    """
    # Простой regex для Unicode эмодзи
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F]|"  # emoticons
        "[\U0001F300-\U0001F5FF]|"  # symbols & pictographs
        "[\U0001F680-\U0001F6FF]|"  # transport & map symbols
        "[\U0001F1E0-\U0001F1FF]|"  # flags (iOS)
        "[\U00002702-\U000027B0]|"  # dingbats
        "[\U000024C2-\U0001F251]"
    )
    return bool(emoji_pattern.search(text))

def split_text_and_emoji(text: str) -> list:
    """
    Разделяет текст на части: обычный текст и эмодзи
    Возвращает список кортежей (text_part, is_emoji)
    """
    parts = []
    current_text = ""
    
    for char in text:
        if has_emoji(char):
            # Сохраняем накопленный текст
            if current_text:
                parts.append((current_text, False))
                current_text = ""
            # Добавляем эмодзи
            parts.append((char, True))
        else:
            current_text += char
    
    # Добавляем оставшийся текст
    if current_text:
        parts.append((current_text, False))
    
    return parts

def draw_mixed_text(draw: ImageDraw.Draw, position: Tuple[int, int], text: str, 
                   text_font: ImageFont.FreeTypeFont, emoji_font: ImageFont.FreeTypeFont, 
                   fill=(0, 0, 0)) -> int:
    """
    Рисует текст с эмодзи, используя разные шрифты
    Возвращает ширину отрисованного текста
    """
    x, y = position
    total_width = 0
    
    parts = split_text_and_emoji(text)
    
    for part_text, is_emoji in parts:
        if not part_text:
            continue
            
        font_to_use = emoji_font if is_emoji else text_font
        
        # Рисуем часть текста
        draw.text((x + total_width, y), part_text, font=font_to_use, fill=fill)
        
        # Вычисляем ширину для следующей части
        bbox = draw.textbbox((0, 0), part_text, font=font_to_use)
        part_width = bbox[2] - bbox[0]
        total_width += part_width
    
    return total_width

def get_mixed_text_size(text: str, text_font: ImageFont.FreeTypeFont, 
                       emoji_font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """
    Вычисляет размер текста с эмодзи
    """
    # Создаем временное изображение для измерений
    temp_img = Image.new('RGB', (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)
    
    parts = split_text_and_emoji(text)
    total_width = 0
    max_height = 0
    
    for part_text, is_emoji in parts:
        if not part_text:
            continue
            
        font_to_use = emoji_font if is_emoji else text_font
        bbox = temp_draw.textbbox((0, 0), part_text, font=font_to_use)
        part_width = bbox[2] - bbox[0]
        part_height = bbox[3] - bbox[1]
        
        total_width += part_width
        max_height = max(max_height, part_height)
    
    return total_width, max_height
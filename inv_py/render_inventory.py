from PIL import Image, ImageDraw, ImageFont
import os
from typing import Iterable, Tuple, cast
from .mixed_text import get_mixed_fonts, draw_mixed_text, get_mixed_text_size

# Совместимость с разными версиями Pillow для фильтра LANCZOS
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
except Exception:
    RESAMPLE_LANCZOS = getattr(Image, "LANCZOS", Image.BICUBIC)  # type: ignore[attr-defined]

def render_inventory_grid(items, item_images, grid_size=(3, 3), cell_size=128, font_path=None, greyed_out=None):
    """
    Renders inventory grid with optional grayed out items
    greyed_out: set of item_ids that should be rendered with reduced opacity
    """
    cols, rows = grid_size
    width = cols * cell_size
    height = rows * cell_size
    bg_color = (245, 235, 220)
    img = Image.new('RGBA', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    if greyed_out is None:
        greyed_out = set()

    # Получаем шрифты для текста и эмодзи
    fonts = get_mixed_fonts(12)
    text_font = fonts['text']
    emoji_font = fonts['emoji']

    for idx, (item_id, count, name) in enumerate(items):
        col = idx % cols
        row = idx // cols
        x = col * cell_size
        y = row * cell_size
        if item_id == "empty":
            slot_num = str(idx + 1)
            # Шрифт для номеров слотов
            big_fonts = get_mixed_fonts(27)
            big_font = big_fonts['text']
            
            bbox = draw.textbbox((0, 0), slot_num, font=big_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = x + (cell_size - text_w) // 2
            text_y = y + (cell_size - text_h) // 2
            for dx in [-2, 0, 2]:
                for dy in [-2, 0, 2]:
                    if dx != 0 or dy != 0:
                        draw.text((text_x+dx, text_y+dy), slot_num, font=big_font, fill=(255,255,255))
            draw.text((text_x, text_y), slot_num, font=big_font, fill=(120, 60, 30))
        else:
            icon_path = item_images.get(item_id)
            is_greyed = item_id in greyed_out
            
            if icon_path and os.path.exists(icon_path):
                icon = Image.open(icon_path).convert('RGBA').resize((cell_size-16, cell_size-16), RESAMPLE_LANCZOS)
                
                # Apply graying effect if item is out of stock
                if is_greyed:
                    # Convert to grayscale and reduce opacity
                    grayscale = icon.convert('L')  # Convert to grayscale
                    grayscale_rgba = Image.merge('RGBA', (grayscale, grayscale, grayscale, icon.split()[-1]))
                    
                    # Reduce opacity
                    pixels = cast(Iterable[Tuple[int,int,int,int]], grayscale_rgba.getdata())
                    new_pixels = []
                    for r, g, b, a in pixels:
                        new_a = int(a * 0.5) if a > 0 else 0
                        new_pixels.append((r, g, b, new_a))
                    grayscale_rgba.putdata(new_pixels)
                    icon = grayscale_rgba
                
                img.paste(icon, (x+8, y+8), icon)
            
            # Поддержка «сырых» меток без префикса x: если count строка и начинается с '!', рисуем как есть
            if isinstance(count, str):
                if count.startswith('!'):
                    count_text = count[1:]
                else:
                    count_text = f"x{count}"
            else:
                count_text = f"x{count}"
            name_text = name
            
            # Choose text colors based on whether item is greyed out
            if is_greyed:
                shadow_color = (200, 200, 200)  # Lighter shadow for greyed items
                text_color = (120, 120, 120)    # Gray text
            else:
                shadow_color = (255, 255, 255)  # White shadow for normal items
                text_color = (60, 20, 10)       # Dark brown text
            
            # Вычисляем размеры текста используя смешанные шрифты
            w1, h1 = get_mixed_text_size(count_text, text_font, emoji_font)
            w2, h2 = get_mixed_text_size(name_text, text_font, emoji_font)
            total_h = h1 + h2 + 2
            y0 = y + cell_size - total_h - 28
            x1 = x + (cell_size - w1) // 2
            x2 = x + (cell_size - w2) // 2
            
            # Рисуем тени
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        draw_mixed_text(draw, (x1+dx, y0+dy), count_text, text_font, emoji_font, fill=shadow_color)
                        draw_mixed_text(draw, (x2+dx, y0+h1+2+dy), name_text, text_font, emoji_font, fill=shadow_color)
            
            # Рисуем основной текст с эмодзи
            draw_mixed_text(draw, (x1, y0), count_text, text_font, emoji_font, fill=text_color)
            draw_mixed_text(draw, (x2, y0+h1+2), name_text, text_font, emoji_font, fill=text_color)

    return img

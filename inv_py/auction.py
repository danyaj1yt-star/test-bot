"""
Модуль для отображения аукциона с красивым визуальным интерфейсом
"""
from inv_py.config_inventory import ITEMS_CONFIG
from inv_py.render_inventory import render_inventory_grid
import tempfile
import time
import os
import hashlib
import shutil
from typing import List, Tuple, Optional


def _short_number(n: int) -> str:
    """Краткое форматирование числа под стиль 'к/кк/ккк' и запятая как разделитель.
    Примеры: 1_000 -> '1к', 1_500 -> '1,5к', 1_150_000 -> '1,15кк' -> округляем до 1 знак: '1,2кк'.
    """
    try:
        n = int(n)
    except Exception:
        return str(n)

    def fmt(v: float) -> str:
        s = f"{v:.1f}".rstrip('0').rstrip('.')
        return s.replace('.', ',')

    if n >= 1_000_000_000:
        return f"{fmt(n/1_000_000_000)}ккк"
    if n >= 1_000_000:
        return f"{fmt(n/1_000_000)}кк"
    if n >= 1000:
        return f"{fmt(n/1000)}к"
    return str(n)

def render_auction_grid(auction_items: List[Tuple], font_path: Optional[str] = None):
    """
    Рендерит красивое изображение лотов аукциона как в магазине/инвентаре
    
    Args:
        auction_items: список кортежей (auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status)
        font_path: путь к шрифту (если None, используется оптимальный системный шрифт)
    
    Returns:
        str: путь к временному файлу с изображением
    """
    # Используем читаемый шрифт для основного текста
    # Эмодзи будут обрабатываться отдельно если потребуется
    if font_path is None:
        # Segoe UI для хорошей читаемости русских и английских букв
        font_path = "C:/Windows/Fonts/segoeui.ttf"
    # Ограничиваем до 9 лотов на страницу (3x3 сетка)
    PER_PAGE = 9
    page_items = auction_items[:PER_PAGE]
    
    grid_items = []
    item_images = {}
    
    for auction_id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status in page_items:
        # Получаем конфигурацию предмета
        item_config = ITEMS_CONFIG.get(item_id, {})
        item_name = item_config.get('name', item_id)
        item_image = item_config.get('photo_square')
        
        # Формируем верхнюю строку с ценой в коротком виде и нижнюю с названием
        price_short = _short_number(price_per_item)
        top_label = f"!{price_short} дань"  # '!' сигнализирует рендереру рисовать без префикса 'x'
        bottom_label = item_name  # без количества

        grid_items.append((item_id, top_label, bottom_label))
        item_images[item_id] = item_image
    
    # Дополняем пустыми слотами до 9
    while len(grid_items) < PER_PAGE:
        grid_items.append(("empty", "", "Нет лотов"))
        item_images["empty"] = None
    
    # Рендерим изображение
    img = render_inventory_grid(
        grid_items,
        item_images,
        grid_size=(3, 3),
        cell_size=128,
        font_path=font_path
    )
    
    # Сохраняем во временный файл
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    img.save(tmp_path)
    return tmp_path


def _auction_cache_key(auction_items: List[Tuple]) -> str:
    """Формирует стабильный ключ кеша для первых 9 лотов.
    Учитываем item_id/qty/price/expires, порядок важен.
    """
    key_parts = []
    for lot in auction_items[:9]:
        # Структура лота: (id, seller_id, item_id, quantity, price_per_item, created_at, expires_at, status)
        try:
            _, _, item_id, qty, price, _, exp, _ = lot
            key_parts.append(f"{item_id}:{qty}:{price}:{exp}")
        except Exception:
            key_parts.append(str(lot))
    raw = "|".join(key_parts)
    return hashlib.sha1(raw.encode()).hexdigest()


def render_auction_grid_cached(auction_items: List[Tuple], ttl_seconds: int = 60) -> str:
    """Кеширует изображение аукциона: актуализируем раз в ttl_seconds.
    Возвращает путь к PNG в директории cache/.
    """
    from pathlib import Path
    cache_dir = Path("C:/BotKruz/ChatBotKruz/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _auction_cache_key(auction_items)
    cache_path = cache_dir / f"auction_{key}.png"

    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        if time.time() - mtime < ttl_seconds:
            return str(cache_path)

    # Генерируем новое изображение и кладём в кеш
    tmp_path = render_auction_grid(auction_items)
    try:
        shutil.move(tmp_path, cache_path)
    except Exception:
        # Если move не удался (например, на другой диск) — копируем
        try:
            shutil.copyfile(tmp_path, cache_path)
            os.remove(tmp_path)
        except Exception:
            # В крайнем случае возвращаем временный путь
            return tmp_path
    return str(cache_path)

def format_auction_caption(auction_data: dict, current_page: int = 1) -> str:
    """
    Форматирует подпись для изображения аукциона
    
    Args:
        auction_data: данные аукциона из get_auction_items
        current_page: текущая страница
        
    Returns:
        str: отформатированная подпись
    """
    total_items = auction_data["total"]
    total_pages = auction_data["total_pages"]
    
    if total_items == 0:
        return "🏛️ <b>АУКЦИОН</b> 🏛️\n\n❌ Активных лотов нет\n\n💡 Выставьте свои предметы на продажу!"

    caption = f"🏛️ <b>АУКЦИОН</b> 🏛️\n\n"
    caption += f"📄 Страница {current_page}/{total_pages}\n"
    caption += f"📦 Всего лотов: {total_items}\n\n"
    caption += "💰 = цена за штуку в дани\n"
    caption += "🔹 ⏰ = время до окончания торгов\n"
    caption += "� Нажмите на номер лота для покупки\n\n"
    caption += "✨ Новые лоты отображаются первыми"
    
    return caption

def get_auction_display_data(page: int = 1, per_page: int = 9):
    """
    Получает данные аукциона для отображения
    
    Args:
        page: номер страницы
        per_page: количество лотов на странице
        
    Returns:
        dict: данные для отображения аукциона
    """
    from database import get_auction_items, cleanup_expired_auctions
    
    # Очищаем истекшие лоты
    cleanup_expired_auctions()
    
    # Получаем лоты (они уже отсортированы по created_at DESC - новые первые)
    auction_data = get_auction_items(page=page, per_page=per_page)
    
    return auction_data
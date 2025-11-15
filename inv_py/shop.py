from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram import types
import database as db
from inv_py.config_inventory import ITEMS_CONFIG
from inv_py.inventory_db import get_item_quantity
import tempfile
import os
from inv_py.render_inventory import render_inventory_grid
from typing import Optional

SHOP_ITEMS = {}

SHOP_CATEGORIES = {
    "tools": {"name": "🔧 Инструменты", "items": []},
    "food": {"name": "🍎 Еда", "items": []},
    "materials": {"name": "🧱 Материалы", "items": []},
    "special": {"name": "⭐ Особое", "items": []}
}

PER_PAGE = 9

def get_shop_categories():
    categories = []
    for cat_id, cat_data in SHOP_CATEGORIES.items():
        if cat_data["items"]:
            categories.append((cat_id, cat_data["name"]))
    return categories

def get_all_shop_items(page: int = 1):
    """Получить все предметы магазина для отображения на одной странице"""
    # Берем все предметы из SHOP_ITEMS (загруженные товары)
    all_items = []
    for item_id, shop_data in SHOP_ITEMS.items():
        # 🔄 ПОКАЗЫВАЕМ ВСЕ ТОВАРЫ, включая с stock=0
        price = shop_data.get('price', 0)
        stock = shop_data.get('stock', -1)
        all_items.append((item_id, price, stock))  # Добавляем stock для отслеживания
    
    total = len(all_items)
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    page_items = all_items[start:end]
    
    # Дополняем до 9 слотов пустыми слотами
    while len(page_items) < PER_PAGE:
        page_items.append(("empty", 0, 0))  # Добавляем третий элемент для stock
    
    max_page = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return page_items, total, max_page

def get_item_by_slot(slot_num: int, page: int = 1):
    """Получить предмет по номеру слота (1-9) на указанной странице"""
    if slot_num < 1 or slot_num > 9:
        return None, 0, 0
    
    page_items, total, max_page = get_all_shop_items(page)
    try:
        item = page_items[slot_num - 1]  # slot_num начинается с 1, а индекс с 0
        if len(item) == 3:
            return item  # (item_id, price, stock)
        else:
            # Обратная совместимость для старого формата (item_id, price)
            return item[0], item[1], -1
    except IndexError:
        return "empty", 0, 0

def build_shop_main_menu(page: int = 1, max_page: int = 1):
    """Построить главное меню магазина с сеткой 3x3 с цифровыми кнопками"""
    kb = []
    
    # Создаем сетку 3x3 со слотами от 1 до 9 (всегда цифры)
    slot_num = 1
    for row in range(3):
        button_row = []
        for col in range(3):
            # Всегда показываем кнопку как цифру в квадратных скобках
            button_text = f"[{slot_num}]"
            
            button_row.append(InlineKeyboardButton(
                text=button_text,
                callback_data=f"shop_item:{slot_num}:{page}"
            ))
            slot_num += 1
        kb.append(button_row)

    # Добавляем навигацию [<][>] если нужно
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"shop_page:{page-1}"))
    if max_page > 1:
        nav_row.append(InlineKeyboardButton(text=f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"shop_page:{page+1}"))

    if nav_row:
        kb.append(nav_row)    # Кнопка "Назад"
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_category_items(category_id: str, page: int = 1):
    if category_id not in SHOP_CATEGORIES:
        return [], 0, 1
    items = SHOP_CATEGORIES[category_id]["items"]
    total = len(items)
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    # Normalize page items to tuples (item_id, count)
    page_items = []
    for i in items[start:end]:
        if isinstance(i, (list, tuple)):
            iid = i[0]
            cnt = i[1] if len(i) > 1 and isinstance(i[1], int) else 0
            page_items.append((iid, cnt))
        else:
            page_items.append((i, 0))
    while len(page_items) < PER_PAGE:
        page_items.append(("empty", 0))
    max_page = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return page_items, total, max_page

# Устаревшая функция по категориям - теперь используем новый интерфейс
def build_shop_category_menu(category_id: str, page: int, max_page: int):
    kb = []
    num = 1
    for _ in range(3):
        row = []
        for _ in range(3):
            row.append(InlineKeyboardButton(text=f"[{num}]", callback_data=f"shop_item:{category_id}:{num}:{page}"))
            num += 1
        kb.append(row)
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"shop_cat:{category_id}:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"shop_cat:{category_id}:{page+1}"))
    kb.append(nav_row)
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="shop_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def build_item_purchase_menu(category_id: str, item_id: str, page: int):
    if item_id not in SHOP_ITEMS:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_cat:{category_id}:{page}")]])
    item_data = SHOP_ITEMS[item_id]
    kb = [[InlineKeyboardButton(text="💰 Купить 1 шт.", callback_data=f"shop_buy:{item_id}:1:{category_id}:{page}")], [InlineKeyboardButton(text="💰 Купить 5 шт.", callback_data=f"shop_buy:{item_id}:5:{category_id}:{page}"), InlineKeyboardButton(text="💰 Купить 10 шт.", callback_data=f"shop_buy:{item_id}:10:{category_id}:{page}")], [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_cat:{category_id}:{page}")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def can_afford_item(user_id: int, item_id: str, quantity: int = 1):
    if item_id not in SHOP_ITEMS:
        return False, "Предмет не найден"
    item_data = SHOP_ITEMS[item_id]
    total_cost = item_data["price"] * quantity
    user = db.get_user(user_id)
    if not user:
        return False, "Пользователь не найден"
    if item_data["currency"] == "dan":
        if user["dan"] < total_cost:
            return False, f"Недостаточно дань. Нужно: {total_cost}, есть: {user['dan']}"
    elif item_data["currency"] == "kruz":
        if user["kruz"] < total_cost:
            return False, f"Недостаточно круза. Нужно: {total_cost}, есть: {user['kruz']}"
    if item_data.get("stock", -1) != -1 and item_data["stock"] < quantity:
        return False, "Недостаточно товара в магазине"
    return True, "OK"

def purchase_item(user_id: int, item_id: str, quantity: int = 1):
    can_buy, reason = can_afford_item(user_id, item_id, quantity)
    if not can_buy:
        return False, reason
    
    item_data = SHOP_ITEMS[item_id]
    total_cost = item_data["price"] * quantity
    
    # Списываем валюту
    if item_data["currency"] == "dan":
        success = db.withdraw_dan(user_id, total_cost)
        if not success:
            return False, "Ошибка списания дань"
    elif item_data["currency"] == "kruz":
        success = db.withdraw_kruz(user_id, total_cost)
        if not success:
            return False, "Ошибка списания круза"
    
    # Добавляем предмет в инвентарь
    db.add_item(user_id, item_id, quantity)
    
    # ✅ СОХРАНЯЕМ ИЗМЕНЕНИЕ СТОКА В ФАЙЛ
    if item_data.get("stock", -1) != -1:  # Если сток ограничен
        old_stock = item_data["stock"]
        new_stock = old_stock - quantity
        item_data["stock"] = new_stock  # Обновляем в памяти
        
        # Сохраняем в файл
        save_stock_to_file(item_id, new_stock)
        print(f"📦 Товар {item_id}: сток {old_stock} → {new_stock}")
    
    item_name = ITEMS_CONFIG.get(item_id, {}).get("name", item_id)
    currency_symbol = "✨" if item_data["currency"] == "dan" else "⭐"
    return True, f"✅ Куплено: {quantity}x {item_name} за {total_cost} {currency_symbol}"

def save_stock_to_file(item_id: str, new_stock: int):
    """Сохраняет обновленный сток товара в shop_config.py"""
    try:
        import os
        config_path = os.path.join(os.path.dirname(__file__), "shop_config.py")
        
        # Читаем текущий файл
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Обновляем конкретный товар
        import re
        pattern = rf'"{item_id}":\s*\{{\s*"stock":\s*(-?\d+)\s*\}}'
        replacement = f'"{item_id}": {{"stock": {new_stock}}}'
        
        new_content = re.sub(pattern, replacement, content)
        
        # Записываем обновленный файл
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Сток товара {item_id} сохранен в файл: {new_stock}")
        
    except Exception as e:
        print(f"❌ Ошибка сохранения стока для {item_id}: {e}")

def get_item_info(item_id: str):
    if item_id == "empty" or item_id not in SHOP_ITEMS:
        return None
    shop_data = SHOP_ITEMS[item_id]
    item_config = ITEMS_CONFIG.get(item_id, {})
    info = {"name": item_config.get("name", item_id), "description": item_config.get("desc", "Описание отсутствует"), "price": shop_data["price"], "currency": shop_data["currency"], "currency_symbol": "✨" if shop_data["currency"] == "dan" else "⭐", "stock": shop_data.get("stock", -1), "photo": item_config.get("photo_square", item_config.get("photo_full"))}
    return info

def render_shop_grid(page: int = 1, font_path: Optional[str] = None):
    """Render shop grid showing stock quantities and graying out items with 0 stock"""
    from inv_py.render_inventory import render_inventory_grid
    
    page_items, total, max_page = get_all_shop_items(page)
    
    grid_items = []
    item_images = {}
    greyed_out = set()
    
    for item_id, price, stock in page_items:
        if item_id == "empty":
            name = "Пусто"
            count = 0
            count_text = "0"  # Исправляем: добавляем count_text для пустых слотов
            item_images[item_id] = None
        else:
            cfg = ITEMS_CONFIG.get(item_id, {})
            name = cfg.get("name", item_id)
            
            # Show stock quantity instead of price
            if stock == -1:
                count_text = "∞ шт"  # Infinite stock
                count = "∞"
            elif stock == 0:
                count_text = "0 шт"  # Out of stock
                count = 0
                greyed_out.add(item_id)  # Mark for graying out
            else:
                count_text = f"{stock} шт"
                count = stock
            
            item_images[item_id] = cfg.get("photo_square")
        
        grid_items.append((item_id, count_text, name))
    
    # Fill remaining slots with empty
    while len(grid_items) < PER_PAGE:
        grid_items.append(("empty", 0, "Пусто"))
    
    # Render with graying out for out-of-stock items
    img = render_inventory_grid(
        grid_items, 
        item_images, 
        grid_size=(3, 3), 
        cell_size=128, 
        font_path=font_path,
        greyed_out=greyed_out
    )
    
    # Save to temporary file
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    img.save(tmp_path)
    return tmp_path

def render_category_image(category_id: str, page: int, font_path: Optional[str] = None):
    items, total, max_page = get_category_items(category_id, page)
    grid_items = []
    item_images = {}
    for item_id, _ in items:
        if item_id == "empty":
            name = "Пусто"
            count = 0
            item_images[item_id] = None
        else:
            cfg = ITEMS_CONFIG.get(item_id, {})
            name = cfg.get("name", item_id)
            shop_data = SHOP_ITEMS.get(item_id, {})
            price = shop_data.get("price", 0)
            count = price
            item_images[item_id] = cfg.get("photo_square")
        grid_items.append((item_id, count, name))
    while len(grid_items) < PER_PAGE:
        grid_items.append(("empty", 0, "Пусто"))
    img = render_inventory_grid(grid_items, item_images, grid_size=(3,3), cell_size=128, font_path=font_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    img.save(tmp_path)
    return tmp_path

def init_shop():
    try:
        from inv_py.shop_config import load_shop_items
        load_shop_items()
    except ImportError:
        print("inv_py/shop_config.py не найден, используется пустой магазин")
    except Exception as e:
        print(f"Ошибка загрузки конфигурации магазина: {e}")
    # Информационное сообщение об инициализации магазина
    print(f"Магазин инициализирован. Товаров: {len(SHOP_ITEMS)}")

def add_shop_item(item_id: str, price: int, currency: str = "dan", category: str = "materials", stock: int = -1):
    if item_id not in ITEMS_CONFIG:
        print(f"Предмет {item_id} не найден в ITEMS_CONFIG")
        return False
    SHOP_ITEMS[item_id] = {"price": price, "currency": currency, "stock": stock}
    if category in SHOP_CATEGORIES:
        if item_id not in SHOP_CATEGORIES[category]["items"]:
            SHOP_CATEGORIES[category]["items"].append(item_id)
    print(f"Товар {item_id} добавлен в магазин (категория: {category}, цена: {price} {currency})")
    return True

def get_shop_stats():
    total_items = len(SHOP_ITEMS)
    categories_count = len([cat for cat in SHOP_CATEGORIES.values() if cat["items"]])
    return {"total_items": total_items, "categories": categories_count, "items_per_category": {cat_id: len(cat_data["items"]) for cat_id, cat_data in SHOP_CATEGORIES.items()}}
# shop module moved under inv_py (legacy duplicate below preserved but disabled)
LEGACY_SHOP_CODE = r"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram import types
import database as db
from inv_py.config_inventory import ITEMS_CONFIG
import tempfile
import os
from inv_py.render_inventory import render_inventory_grid

# Конфигурация магазина - какие предметы продаются
# Preserve existing SHOP_ITEMS if already defined
if 'SHOP_ITEMS' not in globals():
    SHOP_ITEMS = {}

# Категории товаров для удобной навигации
_DEFAULT_SHOP_CATEGORIES = {
    "tools": {"name": "🔧 Инструменты", "items": []},
    "food": {"name": "🍎 Еда", "items": []},
    "materials": {"name": "🧱 Материалы", "items": []},
    "special": {"name": "⭐ Особое", "items": []}
}
if 'SHOP_CATEGORIES' not in globals():
    SHOP_CATEGORIES = {k: {"name": v["name"], "items": list(v["items"])} for k, v in _DEFAULT_SHOP_CATEGORIES.items()}
else:
    # Merge without losing existing items
    for k, v in _DEFAULT_SHOP_CATEGORIES.items():
        if k not in SHOP_CATEGORIES:
            SHOP_CATEGORIES[k] = {"name": v["name"], "items": []}
        else:
            SHOP_CATEGORIES[k].setdefault("name", v["name"])
            SHOP_CATEGORIES[k].setdefault("items", [])

PER_PAGE = 9  # Количество товаров на странице


def get_shop_categories():
    categories = []
    for cat_id, cat_data in SHOP_CATEGORIES.items():
        if cat_data["items"]:
            categories.append((cat_id, cat_data["name"]))
    return categories


def get_category_items(category_id: str, page: int = 1):
    if category_id not in SHOP_CATEGORIES:
        return [], 0, 1
    
    items = SHOP_CATEGORIES[category_id]["items"]
    total = len(items)
    
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    # Normalize page items to tuples (item_id, count)
    page_items = []
    for i in items[start:end]:
        if isinstance(i, (list, tuple)):
            iid = i[0]
            cnt = i[1] if len(i) > 1 and isinstance(i[1], int) else 0
            page_items.append((iid, cnt))
        else:
            page_items.append((i, 0))
    
    while len(page_items) < PER_PAGE:
        page_items.append(("empty", 0))
    
    max_page = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return page_items, total, max_page


def build_shop_main_menu():
    categories = get_shop_categories()
    kb = []
    row = []
    for cat_id, cat_name in categories:
        row.append(InlineKeyboardButton(text=cat_name, callback_data=f"shop_cat:{cat_id}:1"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def build_shop_category_menu(category_id: str, page: int, max_page: int):
    kb = []
    num = 1
    for _ in range(3):
        row = []
        for _ in range(3):
            row.append(InlineKeyboardButton(
                text=f"[{num}]", 
                callback_data=f"shop_item:{category_id}:{num}:{page}"
            ))
            num += 1
        kb.append(row)
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"shop_cat:{category_id}:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"shop_cat:{category_id}:{page+1}"))
    kb.append(nav_row)
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="shop_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def build_item_purchase_menu(category_id: str, item_id: str, page: int):
    if item_id not in SHOP_ITEMS:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_cat:{category_id}:{page}")]
        ])
    item_data = SHOP_ITEMS[item_id]
    kb = [
        [InlineKeyboardButton(text="💰 Купить 1 шт.", callback_data=f"shop_buy:{item_id}:1:{category_id}:{page}")],
        [
            InlineKeyboardButton(text="💰 Купить 5 шт.", callback_data=f"shop_buy:{item_id}:5:{category_id}:{page}"),
            InlineKeyboardButton(text="💰 Купить 10 шт.", callback_data=f"shop_buy:{item_id}:10:{category_id}:{page}")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_cat:{category_id}:{page}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def can_afford_item(user_id: int, item_id: str, quantity: int = 1):
    if item_id not in SHOP_ITEMS:
        return False, "Предмет не найден"
    item_data = SHOP_ITEMS[item_id]
    total_cost = item_data["price"] * quantity
    user = db.get_user(user_id)
    if not user:
        return False, "Пользователь не найден"
    if item_data["currency"] == "dan":
        if user["dan"] < total_cost:
            return False, f"Недостаточно дань. Нужно: {total_cost}, есть: {user['dan']}"
    elif item_data["currency"] == "kruz":
        if user["kruz"] < total_cost:
            return False, f"Недостаточно круза. Нужно: {total_cost}, есть: {user['kruz']}"
    if item_data.get("stock", -1) != -1 and item_data["stock"] < quantity:
        return False, "Недостаточно товара в магазине"
    return True, "OK"


def get_item_info(item_id: str):
    if item_id == "empty" or item_id not in SHOP_ITEMS:
        return None
    shop_data = SHOP_ITEMS[item_id]
    item_config = ITEMS_CONFIG.get(item_id, {})
    info = {
        "name": item_config.get("name", item_id),
        "description": item_config.get("desc", "Описание отсутствует"),
        "price": shop_data["price"],
        "currency": shop_data["currency"],
        "currency_symbol": "✨" if shop_data["currency"] == "dan" else "⭐",
        "stock": shop_data.get("stock", -1),
        "photo": item_config.get("photo_square", item_config.get("photo_full"))
    }
    return info


def render_category_image(category_id: str, page: int, font_path: Optional[str] = None):
    items, total, max_page = get_category_items(category_id, page)
    grid_items = []
    item_images = {}
    for item_id, _ in items:
        if item_id == "empty":
            name = "Пусто"
            count = 0
            item_images[item_id] = None
        else:
            cfg = ITEMS_CONFIG.get(item_id, {})
            name = cfg.get("name", item_id)
            shop_data = SHOP_ITEMS.get(item_id, {})
            price = shop_data.get("price", 0)
            count = price
            item_images[item_id] = cfg.get("photo_square")
        grid_items.append((item_id, count, name))
    while len(grid_items) < PER_PAGE:
        grid_items.append(("empty", 0, "Пусто"))
    img = render_inventory_grid(grid_items, item_images, grid_size=(3,3), cell_size=128, font_path=font_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    img.save(tmp_path)
    return tmp_path


def init_shop():
    try:
        from inv_py.shop_config import load_shop_items
        load_shop_items()
    except ImportError:
        print("shop_config.py не найден, используется пустой магазин")
    except Exception as e:
        print(f"Ошибка загрузки конфигурации магазина: {e}")
    print(f"Магазин инициализирован. Товаров: {len(SHOP_ITEMS)}")


def add_shop_item(item_id: str, price: int, currency: str = "dan", category: str = "materials", stock: int = -1):
    if item_id not in ITEMS_CONFIG:
        print(f"Предмет {item_id} не найден в ITEMS_CONFIG")
        return False
    SHOP_ITEMS[item_id] = {
        "price": price,
        "currency": currency,
        "stock": stock
    }
    if category in SHOP_CATEGORIES:
        if item_id not in SHOP_CATEGORIES[category]["items"]:
            SHOP_CATEGORIES[category]["items"].append(item_id)
    print(f"Товар {item_id} добавлен в магазин (категория: {category}, цена: {price} {currency})")
    return True


def get_shop_stats():
    total_items = len(SHOP_ITEMS)
    categories_count = len([cat for cat in SHOP_CATEGORIES.values() if cat["items"]])
    return {
        "total_items": total_items,
        "categories": categories_count,
        "items_per_category": {cat_id: len(cat_data["items"]) 
                               for cat_id, cat_data in SHOP_CATEGORIES.items()}
    }
"""

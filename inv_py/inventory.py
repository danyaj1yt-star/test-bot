from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from inv_py.config_inventory import ITEMS_CONFIG
from inv_py.inventory_db import get_item_quantity, set_item_quantity, modify_item_quantity
from typing import Optional
import database as db

PER_PAGE = 9

def sync_inventory_with_json_db(user_id: int):
    """Синхронизировать инвентарь пользователя с JSON базой данных без создания дубликатов"""
    # Получаем текущий инвентарь из основной БД (уже агрегированный)
    current_inv = db.get_inventory(user_id)  # [(item_id, count)]
    
    # Создаем словарь для быстрого доступа
    inventory_dict = {item_id: count for item_id, count in current_inv}
    
    # Получаем данные из JSON БД
    from inv_py.inventory_db import get_all_quantities
    json_quantities = get_all_quantities()
    
    # Флаг изменений для минимизации обращений к БД
    changes_made = False
    
    for item_id, json_count in json_quantities.items():
        if json_count > 0:
            current_count = inventory_dict.get(item_id, 0)
            
            # Обновляем только если есть реальная разница
            if json_count != current_count:
                inventory_dict[item_id] = max(json_count, current_count)
                db.set_inventory_item(user_id, item_id, inventory_dict[item_id])
                changes_made = True
    
    # Преобразуем обратно в список кортежей, исключая предметы с нулевым количеством
    updated_inv = [(item_id, count) for item_id, count in inventory_dict.items() if count > 0]
    
    # Сортируем для стабильного порядка
    updated_inv.sort(key=lambda x: x[0])
    
    return updated_inv

def get_user_inventory(user_id: int, page: int = 1, force_sync: bool = False):
    """Получить инвентарь пользователя с опциональной синхронизацией.
    Теперь животные отображаются КАЖДОЕ КАК ОТДЕЛЬНЫЙ ПРЕДМЕТ (не стакаются).
    Формат item_id для индивидуального животного: "<base_id>@<owned_id>", например "08@123".
    """
    # Синхронизируем с JSON БД только при необходимости
    if force_sync:
        base_inv = sync_inventory_with_json_db(user_id)
    else:
        # Используем агрегированные данные из БД напрямую
        base_inv = db.get_inventory(user_id)

    # 1) Миграция: конвертируем агрегированные животные (08,09) в индивидуальные owned_animals
    animal_base_ids = {"08", "09"}
    try:
        from ferma import add_owned_animal
        # Пробегаем по базе инвентаря и переносим животных, если вдруг они есть в агрегированном виде
        for item_id, count in list(base_inv):
            if item_id in animal_base_ids and count > 0:
                # Создаём столько же индивидуальных животных
                for _ in range(count):
                    add_owned_animal(user_id, item_id, last_fed_time=0)
                # Обнуляем агрегированное количество
                try:
                    db.remove_item(user_id, item_id, count)
                except Exception:
                    pass
        # Обновим базовый список после миграции
        base_inv = [(i, c) for i, c in db.get_inventory(user_id)]
    except Exception:
        pass

    # 2) Убираем животных из агрегированного инвентаря (08, 09)
    filtered_inv = [(item_id, count) for item_id, count in base_inv if item_id not in animal_base_ids]

    # 3) Добавляем индивидуальных животных из owned_animals как отдельные элементы
    try:
        from ferma import list_owned_animals
        owned = list_owned_animals(user_id)
    except Exception:
        owned = []

    # Превращаем каждое животное в отдельный «предмет» со своим item_id с постфиксом @id
    for a in owned:
        pseudo_item_id = f"{a['item_id']}@{a['id']}"  # например 08@17
        filtered_inv.append((pseudo_item_id, 1))

    # Финальный список и пагинация
    total = sum(c for _, c in filtered_inv)
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    items = filtered_inv[start:end]

    while len(items) < PER_PAGE:
        items.append(("empty", 0))

    max_page = max(1, (len(filtered_inv) + PER_PAGE - 1) // PER_PAGE)
    return items, total, max_page

def build_inventory_markup(page: int, max_page: int, owner_user_id: int | None = None):
    kb = []
    num = 1
    for _ in range(3):
        row = []
        for _ in range(3):
            if owner_user_id:
                row.append(InlineKeyboardButton(text=f"[{num}]", callback_data=f"inv_item:{num}:{page}:{owner_user_id}"))
            else:
                row.append(InlineKeyboardButton(text=f"[{num}]", callback_data=f"inv_item:{num}:{page}"))
            num += 1
        kb.append(row)
    
    # Кнопки навигации по страницам
    nav_row = []
    
    # Кнопка "назад" - только если не первая страница
    if page > 1:
        if owner_user_id:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv_page:{page-1}:{owner_user_id}"))
        else:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv_page:{page-1}"))
    
    # Индикатор страницы (всегда показываем)
    nav_row.append(InlineKeyboardButton(text=f"{page}/{max_page}", callback_data="noop"))
    
    # Кнопка "вперед" - только если не последняя страница
    if page < max_page:
        if owner_user_id:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"inv_page:{page+1}:{owner_user_id}"))
        else:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"inv_page:{page+1}"))
    
    kb.append(nav_row)
    
    # Кнопка "Назад"
    if owner_user_id:
        kb.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"open_game_menu:{owner_user_id}")
        ])
    else:
        kb.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")
        ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def show_item_card(message, user_id: int, item_id: str, count: int, page: int, owner_user_id: int | None = None):
    item = ITEMS_CONFIG.get(item_id)
    if not item:
        await message.answer("❌ Ошибка: предмет не найден.")
        return

    if owner_user_id is None:
        owner_user_id = user_id
    
    # Кнопки с owner_user_id для поддержки приватности
    kb = [[InlineKeyboardButton(text="💰 Продавать", callback_data=f"sell:{item_id}:{page}:{owner_user_id}")]]
    if item.get("usable"):
        kb.append([InlineKeyboardButton(text="✨ Использовать", callback_data=f"use:{item_id}:{page}:{owner_user_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"inv_page:{page}:{owner_user_id}")])

    caption = f"{item['name']}\nЦена: {item['price']} Дань\nУ вас: {count} шт."
    try:
        photo = FSInputFile(item["photo_full"])
        await message.answer_photo(photo, caption=caption, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except Exception:
        await message.answer(caption, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

async def use_item(message, user_id: int, item_id: str):
    item = ITEMS_CONFIG.get(item_id)
    if not item or not item.get("usable"):
        await message.answer("❌ Этот предмет нельзя использовать.")
        return

    inv = db.get_inventory(user_id)
    user_item = next(((i, c) for i, c in inv if i == item_id), None)
    
    if not user_item or user_item[1] <= 0:
        await message.answer("❌ У вас нет этого предмета.")
        return

    command = item.get("use_command")
    if command:
        from main import ITEM_USE_HANDLERS
        handler = ITEM_USE_HANDLERS.get(command)
        if handler:
            # Сначала удаляем предмет из инвентаря
            db.remove_item(user_id, item_id, 1)
            
            # Затем вызываем обработчик
            await handler(message, user_id, item_id)
            
            # Для кейсов вообще не показываем сообщения об использовании
            if command.startswith("open_chest"):
                return
            else:
                await message.answer(f"✅ Вы использовали {item['name']}")
                return

    # Обычное использование предмета (без команды)
    # Но для кейсов (сундуков) не показываем сообщение
    if "Сундук" in item.get('name', '') or "📦" in item.get('name', ''):
        db.remove_item(user_id, item_id, 1)
        return
    
    db.remove_item(user_id, item_id, 1)
    await message.answer(f"✅ Вы использовали {item['name']}")

# Функции для управления инвентарем через JSON БД
def add_item_to_json_db(item_id: str, quantity: int, name: Optional[str] = None, description: Optional[str] = None):
    """Добавить товар в JSON базу данных"""
    if not name and item_id in ITEMS_CONFIG:
        name = ITEMS_CONFIG[item_id].get('name', f'Товар {item_id}')
    if not description and item_id in ITEMS_CONFIG:
        description = f"Цена: {ITEMS_CONFIG[item_id].get('price', 0)} Дань"
    
    current_qty = get_item_quantity(item_id)
    new_qty = current_qty + quantity
    return set_item_quantity(item_id, new_qty, name, description)

def remove_item_from_json_db(item_id: str, quantity: int):
    """Удалить товар из JSON базы данных"""
    return modify_item_quantity(item_id, -quantity)

def set_item_in_json_db(item_id: str, quantity: int, name: Optional[str] = None, description: Optional[str] = None):
    """Установить точное количество товара в JSON базе данных"""
    if not name and item_id in ITEMS_CONFIG:
        name = ITEMS_CONFIG[item_id].get('name', f'Товар {item_id}')
    if not description and item_id in ITEMS_CONFIG:
        description = f"Цена: {ITEMS_CONFIG[item_id].get('price', 0)} Дань"
    
    return set_item_quantity(item_id, quantity, name, description)

def get_json_db_info():
    """Получить информацию о JSON базе данных"""
    from inv_py.inventory_db import get_database_info
    return get_database_info()

__all__ = [k for k in globals().keys() if not k.startswith('_')]

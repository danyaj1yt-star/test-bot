"""
Модуль для управления динамической базой данных количества товаров.
Поддерживает автоматическую перезагрузку при изменении файла.
"""
import json
import os
from datetime import datetime
from typing import Dict, Optional

# Путь к файлу базы данных
DB_FILE = "database/inventory_quantities.json"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", DB_FILE)

# Кэш данных и время последней загрузки
_cache = {}
_last_modified = 0

def _get_file_mtime():
    """Получить время последней модификации файла"""
    try:
        return os.path.getmtime(DB_PATH)
    except FileNotFoundError:
        return 0

def _load_database():
    """Загрузить данные из JSON файла"""
    global _cache, _last_modified
    
    try:
        if not os.path.exists(DB_PATH):
            # Создать файл с базовой структурой, если он не существует
            _create_default_db()
        
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            _cache = data.get('items', {})
            _last_modified = _get_file_mtime()
            return True
    except Exception as e:
        print(f"Ошибка загрузки базы данных: {e}")
        return False

def _create_default_db():
    """Создать файл базы данных по умолчанию"""
    default_data = {
        "_info": "База данных количества товаров в инвентаре. Редактируйте количество (quantity) в реальном времени!",
        "_format": "item_id: { quantity: число }",
        "_auto_reload": True,
        "items": {},
        "_last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_version": "1.0"
    }
    
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(default_data, f, ensure_ascii=False, indent=4)

def _should_reload():
    """Проверить, нужно ли перезагрузить данные"""
    return _get_file_mtime() > _last_modified

def _ensure_loaded():
    """Убедиться, что данные загружены и актуальны"""
    if not _cache or _should_reload():
        _load_database()

def get_item_quantity(item_id: str) -> int:
    """Получить количество товара по ID"""
    _ensure_loaded()
    return _cache.get(item_id, {}).get('quantity', 0)

def set_item_quantity(item_id: str, quantity: int, name: Optional[str] = None, description: Optional[str] = None) -> bool:
    """Установить количество товара"""
    try:
        # Загрузить актуальные данные
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Обновить или создать запись товара
        if 'items' not in data:
            data['items'] = {}
        
        if item_id not in data['items']:
            data['items'][item_id] = {}
        
        data['items'][item_id]['quantity'] = quantity
        if name:
            data['items'][item_id]['name'] = name
        if description:
            data['items'][item_id]['description'] = description
        
        data['_last_modified'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Сохранить изменения
        with open(DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # Обновить кэш
        _load_database()
        return True
        
    except Exception as e:
        print(f"Ошибка при сохранении количества товара {item_id}: {e}")
        return False

def modify_item_quantity(item_id: str, delta: int) -> int:
    """Изменить количество товара на указанную величину"""
    current_quantity = get_item_quantity(item_id)
    new_quantity = max(0, current_quantity + delta)  # Не допускаем отрицательных значений
    
    if set_item_quantity(item_id, new_quantity):
        return new_quantity
    return current_quantity

def get_all_quantities() -> Dict[str, int]:
    """Получить все количества товаров"""
    _ensure_loaded()
    return {item_id: item_data.get('quantity', 0) 
            for item_id, item_data in _cache.items()}

def get_database_info() -> Dict:
    """Получить информацию о базе данных"""
    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            'file_path': DB_PATH,
            'last_modified': data.get('_last_modified'),
            'version': data.get('_version'),
            'items_count': len(data.get('items', {})),
            'auto_reload': data.get('_auto_reload', True)
        }
    except Exception as e:
        return {'error': str(e)}

def reload_database() -> bool:
    """Принудительно перезагрузить базу данных"""
    global _cache, _last_modified
    _cache = {}
    _last_modified = 0
    return _load_database()

# Инициализация при импорте модуля
if not _cache:
    _load_database()
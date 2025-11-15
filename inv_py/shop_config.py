# shop_config moved into inv_py
SHOP_CONFIG = {
    "01": {"stock": -1},
    "02": {"stock": 999},
    "03": {"stock": 49},
    "04": {"stock": 1},
    "05": {"stock": -1},  # Бесконечно в наличии
}

def load_shop_items():
    from inv_py.shop import add_shop_item
    from inv_py.config_inventory import ITEMS_CONFIG
    
    loaded_count = 0
    for item_id, config in SHOP_CONFIG.items():
        # Получаем цену и валюту из ITEMS_CONFIG
        item_config = ITEMS_CONFIG.get(item_id, {})
        price = item_config.get('price', 0)
        
        # Используем актуальный сток из конфигурации
        stock = config.get("stock", -1)
        
        success = add_shop_item(
            item_id=item_id,
            price=price,
            currency="dan",  # Всегда дань
            category="materials",  # Все товары в категории materials
            stock=stock
        )
        if success:
            loaded_count += 1
    print(f"Загружено товаров в магазин: {loaded_count}/{len(SHOP_CONFIG)}")
    return loaded_count

def reload_shop_config():
    """Перезагружает конфигурацию магазина из файла (актуальные стоки)"""
    try:
        import importlib
        import sys
        
        # Перезагружаем модуль для получения актуальных данных
        if 'inv_py.shop_config' in sys.modules:
            importlib.reload(sys.modules['inv_py.shop_config'])
        
        return True
    except Exception as e:
        print(f"❌ Ошибка перезагрузки конфигурации магазина: {e}")
        return False

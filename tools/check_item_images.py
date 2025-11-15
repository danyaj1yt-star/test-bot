import os
import sys

# Ensure project root is on sys.path when run directly so `inv_py` imports resolve.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from inv_py.config_inventory import ITEMS_CONFIG, NULL_ITEM
except Exception as e:
    print('Не удалось импортировать config_inventory:', e)
    sys.exit(1)

print('Проверка изображений для ITEMS_CONFIG...')
missing = []
for item_id, cfg in ITEMS_CONFIG.items():
    sq = cfg.get('photo_square')
    full = cfg.get('photo_full')
    print(f"- {item_id}: {cfg.get('name','(no name)')}")
    if not sq or not os.path.exists(sq):
        print(f"  -> Отсутствует square: {sq}")
        missing.append((item_id, 'square', sq))
    else:
        size = None
        try:
            from PIL import Image
            with Image.open(sq) as im:
                size = im.size
        except Exception:
            pass
        print(f"  square ok {sq} size={size}")
    if not full or not os.path.exists(full):
        print(f"  -> Отсутствует full: {full}")
        missing.append((item_id, 'full', full))
    else:
        size = None
        try:
            from PIL import Image
            with Image.open(full) as im:
                size = im.size
        except Exception:
            pass
        print(f"  full ok {full} size={size}")

if not missing:
    print('\nВсе изображения найдены!')
else:
    print('\nОтсутствующие файлы:')
    for item_id, kind, path in missing:
        print(f"  - {item_id} ({kind}): {path}")
    print('\nРекомендуемые размеры: square ~128x128 (png/jpg), full - произвольный, но не меньше 300px в ширину.')

print('\nГотово.')

import os
import sys
from PIL import Image, ImageDraw, ImageFont

try:
    from inv_py.config_inventory import ITEMS_CONFIG, NULL_ITEM
except Exception as e:
    print('Не удалось импортировать config_inventory:', e)
    sys.exit(1)

os.makedirs('C:/BotKruz/ChatBotKruz/photo/inv', exist_ok=True)

font_path = 'C:/Windows/Fonts/arial.ttf'
for item_id, cfg in ITEMS_CONFIG.items():
    name = cfg.get('name', item_id)
    sq = cfg.get('photo_square') or f'C:/BotKruz/ChatBotKruz/photo/inv/{item_id}.png'
    full = cfg.get('photo_full') or f'C:/BotKruz/ChatBotKruz/photo/inv/{item_id}_full.png'

    # square placeholder 128x128
    try:
        img = Image.new('RGBA', (128,128), (200,180,160))
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype(font_path, 18)
        except Exception:
            f = ImageFont.load_default()
        text = name
        bbox = d.textbbox((0,0), text, font=f)
        w = bbox[2]-bbox[0]
        h = bbox[3]-bbox[1]
        d.text(((128-w)//2, (128-h)//2), text, fill=(40,20,10), font=f)
        os.makedirs(os.path.dirname(sq), exist_ok=True)
        img.save(sq)
        print('Saved placeholder', sq)
    except Exception as e:
        print('Error saving square for', item_id, e)

    # full placeholder 600x400
    try:
        img = Image.new('RGBA', (600,400), (220,200,180))
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype(font_path, 32)
        except Exception:
            f = ImageFont.load_default()
        text = name
        bbox = d.textbbox((0,0), text, font=f)
        w = bbox[2]-bbox[0]
        h = bbox[3]-bbox[1]
        d.text(((600-w)//2, (400-h)//2), text, fill=(40,20,10), font=f)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        img.save(full)
        print('Saved placeholder', full)
    except Exception as e:
        print('Error saving full for', item_id, e)

# Null item
try:
    null_path = NULL_ITEM.get('photo_square', 'C:/BotKruz/ChatBotKruz/photo/inv/null.jpg')
    if not os.path.exists(null_path):
        img = Image.new('RGBA', (128,128), (240,240,240))
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype(font_path, 18)
        except Exception:
            f = ImageFont.load_default()
        d.text((32,56), 'Пусто', font=f, fill=(120,120,120))
        os.makedirs(os.path.dirname(null_path), exist_ok=True)
        img.save(null_path)
        print('Saved null placeholder', null_path)
except Exception as e:
    print('Error saving null placeholder', e)

print('Генерация заглушек завершена.')

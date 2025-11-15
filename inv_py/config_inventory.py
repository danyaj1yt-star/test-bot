ITEMS_CONFIG = {
    "01": {
        "name": "Сундук 1 уровня",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/01.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/01_full.jpg",
        "price": 2500,
        "stars_cost": 1,
        "usable": True,
        "use_command": "open_chest_level1",
        "chest_level": 1,
        "reward_min": 1000,
        "reward_max": 8000
    },
    "02": {
        "name": "Сундук 2 уровня",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/02.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/02_full.jpg",
        "price": 10000,
        "stars_cost": 5,
        "usable": True,
        "use_command": "open_chest_level2",
        "chest_level": 2,
        "reward_min": 5000,
        "reward_max": 25000
    },
    "03": {
        "name": "Сундук 3 уровня", 
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/03.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/03_full.jpg",
        "price": 50000,
        "stars_cost": 50,
        "usable": True,
        "use_command": "open_chest_level3",
        "chest_level": 3,
        "reward_min": 10000,
        "reward_max": 50000
    },
    "04": {
        "name": "Подарок в Telegram",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/04.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/04.jpg",
        "price": 150000,
        "usable": True,
        "use_command": "send_telegram_gift",
        "limited": True,
        "max_quantity": 1
    },
    "05": {
        "name": "Бесконечный склад",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/05.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/05.jpg",
        "price": 50000,
        "stars_cost": 7,
        "usable": True,
        "use_command": "activate_infinite_storage",
        "duration_days_min": 7,
        "duration_days_max": 14,
        "storage_type": "infinite"
    },
    "06": {
        "name": "Пшеница",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/bone.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/bone_full.jpg",
        "price": 500,
        "usable": False,
        "desc": "Пучок пшеницы — базовый сельхоз-ресурс для фермы и торговли.",
        "currency": "dan",
        "category": "material"
    },
    "07": {
        "name": "Кукуруза",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/meat.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/meat_full.jpg",
        "price": 800,
        "usable": False,
        "desc": "Початок кукурузы — востребованное зерно для фермы и торговли.",
        "currency": "dan",
        "category": "material"
    },
    "08": {
        "name": "🐔 Курица",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/chicken.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/chicken_full.jpg",
        "price": 5000,
        "usable": True,
        "use_command": "place_animal_on_farm",
        "desc": "Курица для фермы. Приносит 50 дань/час, если накормлена. Можно разместить на ферме (нужен свободный слот уровня 3+) или продать.",
        "currency": "dan",
        "category": "animal",
        "animal_type": "chicken",
        "income_per_hour": 50,
        "max_hungry_hours": 12
    },
    "09": {
        "name": "🐄 Корова",
        "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/cow.jpg",
        "photo_full": "C:/BotKruz/ChatBotKruz/photo/inv/cow_full.jpg",
        "price": 15000,
        "usable": True,
        "use_command": "place_animal_on_farm",
        "desc": "Корова для фермы. Приносит 100 дань/час, если накормлена. Можно разместить на ферме (нужен свободный слот уровня 3+) или продать.",
        "currency": "dan",
        "category": "animal",
        "animal_type": "cow",
        "income_per_hour": 100,
        "max_hungry_hours": 12
    },
}

NULL_ITEM = {
    "photo_square": "C:/BotKruz/ChatBotKruz/photo/inv/null.jpg",
    "name": "Пусто"
}

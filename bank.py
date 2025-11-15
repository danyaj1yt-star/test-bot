# === БАНКОВСКАЯ СИСТЕМА ===
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

# Путь к базе данных банка
BANK_DB_PATH = os.path.join(os.path.dirname(__file__), "database", "bank.db")

class BankSystem:
    def __init__(self):
        self.db_path = BANK_DB_PATH
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных банка"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица депозитов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    amount REAL NOT NULL,
                    deposit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_days INTEGER NOT NULL,
                    interest_rate REAL NOT NULL,
                    status TEXT DEFAULT 'active',
                    maturity_date TIMESTAMP
                )
            ''')
            
            # Таблица операций (история)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bank_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    operation_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT,
                    operation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def add_deposit(self, user_id: int, username: str, amount: float, duration_days: int, interest_rate: float) -> bool:
        """Добавить депозит с указанным сроком и процентной ставкой"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Вычисляем дату погашения
                maturity_date = datetime.now() + timedelta(days=duration_days)
                
                cursor.execute('''
                    INSERT INTO deposits (user_id, username, amount, duration_days, interest_rate, maturity_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, username, amount, duration_days, interest_rate, maturity_date.isoformat()))
                
                # Записываем операцию в историю
                cursor.execute('''
                    INSERT INTO bank_operations (user_id, operation_type, amount, description)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, "deposit", amount, f"Создан депозит на {amount} Дань на {duration_days} дней под {interest_rate*100}%"))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Ошибка добавления депозита: {e}")
            return False
    
    def get_user_deposits(self, user_id: int) -> List[Dict[str, Any]]:
        """Получить все депозиты пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, amount, deposit_date, duration_days, interest_rate, status, maturity_date
                    FROM deposits 
                    WHERE user_id = ? AND status != 'collected'
                    ORDER BY deposit_date DESC
                ''', (user_id,))
                
                deposits = []
                now = datetime.now()
                
                for row in cursor.fetchall():
                    deposit = {
                        'id': row[0],
                        'amount': row[1],
                        'deposit_date': row[2],
                        'duration_days': row[3],
                        'interest_rate': row[4],
                        'status': row[5],
                        'maturity_date': row[6]
                    }
                    
                    # Вычисляем оставшиеся дни для всех депозитов
                    if deposit['maturity_date']:
                        maturity = datetime.fromisoformat(deposit['maturity_date'])
                        if now < maturity:
                            remaining_days = (maturity - now).days + 1  # +1 чтобы показывать минимум 1 день
                            deposit['remaining_days'] = max(1, remaining_days)
                        else:
                            deposit['remaining_days'] = 0
                    else:
                        deposit['remaining_days'] = 0
                    
                    # Обновляем статус депозита если нужно
                    if deposit['status'] == 'active' and deposit['maturity_date']:
                        maturity = datetime.fromisoformat(deposit['maturity_date'])
                        if now >= maturity:
                            # Депозит созрел - обновляем статус
                            cursor.execute('''
                                UPDATE deposits SET status = 'matured' 
                                WHERE id = ?
                            ''', (deposit['id'],))
                            deposit['status'] = 'matured'
                    
                    deposits.append(deposit)
                
                conn.commit()
                return deposits
        except Exception as e:
            print(f"Ошибка получения депозитов: {e}")
            return []
    
    def get_user_total_deposits(self, user_id: int) -> float:
        """Получить общую сумму активных депозитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(amount) FROM deposits 
                    WHERE user_id = ? AND status IN ('active', 'matured')
                ''', (user_id,))
                
                result = cursor.fetchone()[0]
                return result if result else 0.0
        except Exception as e:
            print(f"Ошибка получения общей суммы депозитов: {e}")
            return 0.0
    
    def get_total_bank_deposits(self) -> float:
        """Получить общую сумму всех депозитов в банке"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(amount) FROM deposits WHERE status = 'active'
                ''')
                
                result = cursor.fetchone()[0]
                return result if result else 0.0
        except Exception as e:
            print(f"Ошибка получения общей суммы банка: {e}")
            return 0.0
    
    def get_user_deposits_count(self, user_id: int) -> int:
        """Получить количество активных депозитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM deposits 
                    WHERE user_id = ? AND status IN ('active', 'matured')
                ''', (user_id,))
                
                return cursor.fetchone()[0]
        except Exception as e:
            print(f"Ошибка получения количества депозитов: {e}")
            return 0
    
    def get_total_deposits_count(self) -> int:
        """Получить общее количество всех депозитов в мире"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM deposits 
                    WHERE status IN ('active', 'matured', 'completed')
                ''')
                
                return cursor.fetchone()[0]
        except Exception as e:
            print(f"Ошибка получения общего количества депозитов: {e}")
            return 0
    
    def withdraw_deposit(self, user_id: int, deposit_id: int) -> Tuple[bool, str, float]:
        """Снять депозит"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Получаем информацию о депозите
                cursor.execute('''
                    SELECT amount, deposit_date, duration_days, interest_rate, maturity_date FROM deposits 
                    WHERE id = ? AND user_id = ? AND status = 'active'
                ''', (deposit_id, user_id))
                
                result = cursor.fetchone()
                if not result:
                    return False, "Депозит не найден или уже снят", 0.0
                
                amount, deposit_date, duration_days, interest_rate, maturity_date = result
                
                # Проверяем, истек ли срок депозита
                now = datetime.now()
                maturity = datetime.fromisoformat(maturity_date) if maturity_date else now
                
                # Помечаем депозит как снятый
                if now >= maturity:
                    # Депозит завершился по сроку - начисляем проценты
                    status = 'completed'
                    profit = amount * interest_rate
                    total_return = amount + profit
                    cursor.execute('''
                        UPDATE deposits SET status = ? 
                        WHERE id = ? AND user_id = ?
                    ''', (status, deposit_id, user_id))
                    
                    cursor.execute('''
                        INSERT INTO bank_operations (user_id, operation_type, amount, description)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, "withdraw_completed", total_return, f"Снят завершенный депозит #{deposit_id} с процентами"))
                    
                    return True, f"Депозит завершен по сроку! Получено {total_return:.0f} Дань (включая {profit:.0f} прибыли)", total_return
                else:
                    # Досрочное снятие - без процентов
                    status = 'withdrawn_early'
                    cursor.execute('''
                        UPDATE deposits SET status = ? 
                        WHERE id = ? AND user_id = ?
                    ''', (status, deposit_id, user_id))
                    
                    cursor.execute('''
                        INSERT INTO bank_operations (user_id, operation_type, amount, description)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, "withdraw_early", amount, f"Досрочно снят депозит #{deposit_id} без процентов"))
                    
                    return True, f"Депозит снят досрочно. Получено {amount:.0f} Дань (без процентов)", amount
                
                conn.commit()
                
        except Exception as e:
            print(f"Ошибка снятия депозита: {e}")
            return False, f"Ошибка: {e}", 0.0

    def close_deposit_early(self, user_id: int, deposit_id: int) -> Tuple[bool, str]:
        """Досрочно закрыть депозит"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Получаем информацию о депозите
                cursor.execute('''
                    SELECT amount FROM deposits 
                    WHERE id = ? AND user_id = ? AND status = 'active'
                ''', (deposit_id, user_id))
                
                result = cursor.fetchone()
                if not result:
                    return False, "Депозит не найден или уже закрыт"
                
                amount = result[0]
                
                # Помечаем депозит как досрочно закрытый
                cursor.execute('''
                    UPDATE deposits SET status = 'closed_early' 
                    WHERE id = ? AND user_id = ?
                ''', (deposit_id, user_id))
                
                # Записываем операцию
                cursor.execute('''
                    INSERT INTO bank_operations (user_id, operation_type, amount, description)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, "close_early", amount, f"Досрочно закрыт депозит #{deposit_id}"))
                
                conn.commit()
                return True, f"Депозит закрыт досрочно. Сумма {amount:.0f} Дань возвращена на баланс."
                
        except Exception as e:
            print(f"Ошибка закрытия депозита: {e}")
            return False, f"Ошибка: {e}"

    def collect_completed_deposit(self, user_id: int, deposit_id: int) -> Tuple[bool, str, float]:
        """Забрать доходы с завершенного депозита"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Получаем информацию о депозите
                cursor.execute('''
                    SELECT amount, interest_rate, maturity_date FROM deposits 
                    WHERE id = ? AND user_id = ? AND status = 'matured'
                ''', (deposit_id, user_id))
                
                result = cursor.fetchone()
                if not result:
                    return False, "Депозит не найден или еще не созрел", 0.0
                
                amount, interest_rate, maturity_date = result
                profit = amount * interest_rate
                total_return = amount + profit
                
                # Помечаем как собранный
                cursor.execute('''
                    UPDATE deposits SET status = 'collected' 
                    WHERE id = ? AND user_id = ?
                ''', (deposit_id, user_id))
                
                # Записываем операцию
                cursor.execute('''
                    INSERT INTO bank_operations (user_id, operation_type, amount, description)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, "collect", total_return, f"Собран доход с депозита #{deposit_id}"))
                
                conn.commit()
                return True, f"Доходы собраны! +{total_return:.0f} Дань", total_return
                
        except Exception as e:
            print(f"Ошибка сбора депозита: {e}")
            return False, f"Ошибка: {e}", 0.0

    def get_deposit_info(self, user_id: int, deposit_id: int) -> Optional[Dict[str, Any]]:
        """Получить подробную информацию о депозите"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, amount, deposit_date, duration_days, interest_rate, status, maturity_date
                    FROM deposits 
                    WHERE id = ? AND user_id = ?
                ''', (deposit_id, user_id))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                deposit = {
                    'id': row[0],
                    'amount': row[1],
                    'deposit_date': row[2],
                    'duration_days': row[3],
                    'interest_rate': row[4],
                    'status': row[5],
                    'maturity_date': row[6]
                }
                
                # Вычисляем оставшиеся дни
                if deposit['maturity_date']:
                    maturity = datetime.fromisoformat(deposit['maturity_date'])
                    now = datetime.now()
                    if now < maturity:
                        remaining_days = (maturity - now).days
                        deposit['remaining_days'] = max(0, remaining_days)
                    else:
                        deposit['remaining_days'] = 0
                else:
                    deposit['remaining_days'] = 0
                
                return deposit
        except Exception as e:
            print(f"Ошибка получения информации о депозите: {e}")
            return None
    
    def get_user_operations(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить историю операций пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT operation_type, amount, description, operation_date
                    FROM bank_operations 
                    WHERE user_id = ?
                    ORDER BY operation_date DESC
                    LIMIT ?
                ''', (user_id, limit))
                
                operations = []
                for row in cursor.fetchall():
                    operations.append({
                        'type': row[0],
                        'amount': row[1],
                        'description': row[2],
                        'date': row[3]
                    })
                
                return operations
        except Exception as e:
            print(f"Ошибка получения операций: {e}")
            return []

# Глобальный экземпляр банковской системы
bank_system = BankSystem()

def format_amount(amount: float) -> str:
    """Форматирование суммы для отображения (краткий формат)"""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.0f}м"
    elif amount >= 1_000:
        return f"{amount / 1_000:.0f}к"
    else:
        return f"{amount:.0f}"

def format_full_amount(amount: float) -> str:
    """Полное форматирование суммы"""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}м"
    elif amount >= 1_000:
        return f"{amount / 1_000:.0f}к"
    else:
        return f"{amount:.0f}"

# Планы депозитов: (дни, процент)
DEPOSIT_PLANS = [
    (3, 0.04),    # 3 дня, 4%
    (7, 0.08),    # 7 дней, 8%
    (14, 0.13),   # 14 дней, 13%
    (31, 0.31)    # 31 день, 31%
]

def get_deposit_plan_text(days: int, rate: float) -> str:
    """Получить текст для плана депозита"""
    return f"{days}д/{int(rate*100)}%"

def get_rules_text() -> str:
    """Получить текст правил депозита"""
    return """
📋 ПРАВИЛА ДЕПОЗИТА:

1️⃣ Минимальная сумма депозита: 1,000 Дань
2️⃣ Сумма должна быть кратна 1,000 (только тысячами)
3️⃣ Депозит можно закрыть в любое время
4️⃣ При досрочном закрытии проценты не начисляются
5️⃣ По окончании срока проценты начисляются автоматически
6️⃣ Максимальная сумма одного депозита: 100,000 Дань

⚠️ Администрация не несет ответственности за технические сбои
💡 Рекомендуется диверсифицировать депозиты по срокам
    """.strip()

def get_deposit_status_emoji(status: str) -> str:
    """Получить эмодзи для статуса депозита"""
    status_emojis = {
        'active': '❓',        # Активный депозит
        'matured': '✅',       # Созревший, готов к сбору
        'completed': '📋',     # Завершенный по сроку
        'closed_early': '📋',  # Досрочно закрытый
        'withdrawn_early': '📋',  # Досрочно снятый
        'collected': '📋'      # Собранный
    }
    return status_emojis.get(status, '❓')

def get_deposit_action_emoji(status: str) -> str:
    """Получить эмодзи действия для депозита"""
    if status == 'active':
        return 'X'  # Можно закрыть
    elif status == 'matured':
        return '✅'  # Можно собрать доходы
    elif status in ['closed_early', 'withdrawn_early', 'completed']:
        return '❓'  # Закрытый депозит
    else:
        return '📋'  # Архивный депозит

def format_deposit_button_text(deposit: Dict[str, Any]) -> str:
    """Форматировать текст кнопки депозита"""
    amount = deposit['amount']
    status = deposit['status']
    interest_rate = deposit.get('interest_rate', 0)
    remaining_days = deposit.get('remaining_days', 0)
    
    amount_text = format_amount(amount)
    
    if status == 'active':
        # Активный: [100к Дань/23 дней]
        return f"{amount_text} Дань/{remaining_days} дней"
    elif status == 'matured':
        # Созревший: [12к +9413 💰]
        profit = amount * interest_rate
        return f"{amount_text} +{profit:.0f} 💰"
    elif status in ['completed', 'closed_early', 'withdrawn_early']:
        # Закрытый депозит: показываем дату создания и сумму
        deposit_date = deposit.get('deposit_date', '')
        if deposit_date:
            try:
                from datetime import datetime
                date_obj = datetime.fromisoformat(deposit_date)
                date_str = date_obj.strftime("%d.%m")
            except:
                date_str = "---"
        else:
            date_str = "---"
        return f"{amount_text} от {date_str}"
    else:
        return f"{amount_text} Дань"

def paginate_deposits(deposits: List[Dict[str, Any]], page: int = 1, per_page: int = 6) -> Tuple[List[Dict[str, Any]], int, int]:
    """Разбить депозиты на страницы"""
    total = len(deposits)
    max_page = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, max_page))
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    return deposits[start_idx:end_idx], page, max_page
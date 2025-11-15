"""
Игра "Крестики-нолики" для Telegram бота
Игроки могут вызывать друг друга на дуэль и играть за дань
"""

import time
import asyncio
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import types
import database as db

async def safe_edit_text(message, text, reply_markup=None, parse_mode=None):
    """Безопасное редактирование сообщения"""
    try:
        if hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        pass

# Активные игры крестики-нолики
active_tic_tac_toe_games = {}

class TicTacToeGame:
    def __init__(self, player1_id, player1_name, player2_id, player2_name, bet_amount, game_id):
        self.game_id = game_id
        self.player1_id = player1_id
        self.player1_name = player1_name
        self.player2_id = player2_id 
        self.player2_name = player2_name
        self.bet_amount = bet_amount
        self.current_player = player1_id  # Игрок 1 начинает (крестики)
        self.board = [[" " for _ in range(3)] for _ in range(3)]  # 3x3 поле
        self.player1_symbol = "❌"  # Крестики
        self.player2_symbol = "⭕"  # Нолики
        self.status = "playing"
        # Поле для запоминания кого вызвали (кто должен принимать)
        self.challenged_player_id = None
        self.winner = None
        self.created_at = int(time.time())
        
    def get_symbol(self, player_id):
        """Получить символ игрока"""
        return self.player1_symbol if player_id == self.player1_id else self.player2_symbol
        
    def make_move(self, player_id, row, col):
        """Сделать ход"""
        if self.status != "playing":
            return {"success": False, "error": "Игра завершена"}
            
        if player_id != self.current_player:
            return {"success": False, "error": "Не ваш ход"}
            
        if self.board[row][col] != " ":
            return {"success": False, "error": "Клетка занята"}
            
        # Делаем ход
        symbol = self.get_symbol(player_id)
        self.board[row][col] = symbol
        
        # Проверяем победу
        winner = self.check_winner()
        if winner:
            self.status = "finished"
            self.winner = winner
            return {"success": True, "game_over": True, "winner": winner}
            
        # Проверяем ничью
        if self.is_board_full():
            self.status = "finished"
            self.winner = "draw"
            return {"success": True, "game_over": True, "winner": "draw"}
            
        # Переходим к следующему игроку
        self.current_player = self.player2_id if self.current_player == self.player1_id else self.player1_id
        
        return {"success": True, "game_over": False}
        
    def check_winner(self):
        """Проверить победителя"""
        # Проверяем строки
        for row in self.board:
            if row[0] == row[1] == row[2] != " ":
                if row[0] == self.player1_symbol:
                    return self.player1_id
                else:
                    return self.player2_id
                    
        # Проверяем столбцы  
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] != " ":
                if self.board[0][col] == self.player1_symbol:
                    return self.player1_id
                else:
                    return self.player2_id
                    
        # Проверяем диагонали
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != " ":
            if self.board[0][0] == self.player1_symbol:
                return self.player1_id
            else:
                return self.player2_id
                
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != " ":
            if self.board[0][2] == self.player1_symbol:
                return self.player1_id
            else:
                return self.player2_id
                
        return None
        
    def is_board_full(self):
        """Проверить заполнено ли поле"""
        for row in self.board:
            for cell in row:
                if cell == " ":
                    return False
        return True
        
    def get_board_text(self):
        """Получить текстовое представление доски"""
        lines = []
        for i, row in enumerate(self.board):
            line = ""
            for j, cell in enumerate(row):
                if cell == " ":
                    line += "⬜"
                else:
                    line += cell
                if j < 2:
                    line += " "
            lines.append(line)
        return "\n".join(lines)
        
    def get_keyboard(self):
        """Получить клавиатуру для игры"""
        if self.status != "playing":
            return None
            
        keyboard = []
        for i in range(3):
            row = []
            for j in range(3):
                if self.board[i][j] == " ":
                    # Пустая клетка - можно сделать ход
                    row.append(InlineKeyboardButton(
                        text="⬜", 
                        callback_data=f"ttt_move:{self.game_id}:{i}:{j}"
                    ))
                else:
                    # Занятая клетка
                    row.append(InlineKeyboardButton(
                        text=self.board[i][j], 
                        callback_data="ttt_noop"
                    ))
            keyboard.append(row)
            
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
        
    def get_status_text(self):
        """Получить текст статуса игры"""
        if self.status == "playing":
            current_name = self.player1_name if self.current_player == self.player1_id else self.player2_name
            current_symbol = self.get_symbol(self.current_player)
            
            text = f"🎮 <b>Крестики-нолики</b>\n\n"
            text += f"❌ {self.player1_name} vs ⭕ {self.player2_name}\n"
            text += f"💰 Ставка: {self.bet_amount} дань каждый\n\n"
            text += f"{self.get_board_text()}\n\n"
            text += f"Ход: {current_symbol} <b>{current_name}</b>"
            
        else:
            text = f"🎮 <b>Игра завершена!</b>\n\n"
            text += f"❌ {self.player1_name} vs ⭕ {self.player2_name}\n"
            text += f"💰 Ставка была: {self.bet_amount} дань каждый\n\n"
            text += f"{self.get_board_text()}\n\n"
            
            if self.winner == "draw":
                text += "🤝 <b>Ничья!</b>\n"
                text += f"💸 Комиссия: {int(self.bet_amount * 0.1)} дань с каждого"
            elif self.winner == self.player1_id:
                text += f"🏆 <b>Победа: ❌ {self.player1_name}</b>\n"
                winnings = int(self.bet_amount * 2 * 0.9)  # 90% от общего банка
                text += f"💰 Выигрыш: {winnings} дань"
            else:
                text += f"🏆 <b>Победа: ⭕ {self.player2_name}</b>\n"
                winnings = int(self.bet_amount * 2 * 0.9)  # 90% от общего банка
                text += f"💰 Выигрыш: {winnings} дань"
                
        return text

def generate_unique_ttt_game_id():
    """Генерировать уникальный ID игры"""
    return f"ttt_{int(time.time_ns())}"

def start_tic_tac_toe_challenge(challenger_id, challenger_name, opponent_id, opponent_name, bet_amount):
    """Начать вызов на игру в крестики-нолики"""
    game_id = generate_unique_ttt_game_id()
    
    # Создаем игру в режиме ожидания
    game = TicTacToeGame(challenger_id, challenger_name, opponent_id, opponent_name, bet_amount, game_id)
    game.status = "waiting"
    # Запоминаем кого вызвали - это всегда opponent (второй игрок в параметрах)
    game.challenged_player_id = opponent_id
    
    active_tic_tac_toe_games[game_id] = game
    
    return game

def accept_tic_tac_toe_challenge(game_id, accepter_id):
    """Принять вызов на игру"""
    game = active_tic_tac_toe_games.get(game_id)
    if not game:
        return {"success": False, "error": "Игра не найдена"}
        
    if game.status != "waiting":
        return {"success": False, "error": "Игра уже началась или завершена"}
        
    # Принять вызов может только тот игрок, которого вызвали
    if accepter_id != game.challenged_player_id:
        return {"success": False, "error": "Это не ваш вызов"}
        
    # Списываем дань у обоих игроков
    player1_balance = db.get_user(game.player1_id)
    player2_balance = db.get_user(game.player2_id)
    
    if not player1_balance or player1_balance["dan"] < game.bet_amount:
        return {"success": False, "error": f"У {game.player1_name} недостаточно дани"}
        
    if not player2_balance or player2_balance["dan"] < game.bet_amount:
        return {"success": False, "error": f"У {game.player2_name} недостаточно дани"}
        
    # Списываем ставки
    if not db.withdraw_dan(game.player1_id, game.bet_amount):
        return {"success": False, "error": "Ошибка списания у игрока 1"}
        
    if not db.withdraw_dan(game.player2_id, game.bet_amount):
        # Возвращаем дань первому игроку если у второго ошибка
        db.add_dan(game.player1_id, game.bet_amount)
        return {"success": False, "error": "Ошибка списания у игрока 2"}
        
    # Начинаем игру
    game.status = "playing"
    
    return {"success": True, "game": game}

def decline_tic_tac_toe_challenge(game_id, decliner_id):
    """Отклонить вызов на игру"""
    game = active_tic_tac_toe_games.get(game_id)
    if not game:
        return {"success": False, "error": "Игра не найдена"}
        
    if game.status != "waiting":
        return {"success": False, "error": "Игра уже началась или завершена"}
        
    # Отклонить вызов может только тот игрок, которого вызвали
    if decliner_id != game.challenged_player_id:
        return {"success": False, "error": "Это не ваш вызов"}
        
    # Удаляем игру
    del active_tic_tac_toe_games[game_id]
    
    return {"success": True}

def make_tic_tac_toe_move(game_id, player_id, row, col):
    """Сделать ход в игре"""
    game = active_tic_tac_toe_games.get(game_id)
    if not game:
        return {"success": False, "error": "Игра не найдена"}
        
    result = game.make_move(player_id, row, col)
    
    if result["success"] and result.get("game_over"):
        # Игра завершена, выплачиваем награды
        if game.winner == "draw":
            # Ничья - возвращаем 90% каждому (10% комиссия)
            refund = int(game.bet_amount * 0.9)
            db.add_dan(game.player1_id, refund)
            db.add_dan(game.player2_id, refund)
        else:
            # Есть победитель - отдаем 90% от общего банка
            total_winnings = int(game.bet_amount * 2 * 0.9)
            db.add_dan(game.winner, total_winnings)
            
        # Обновляем статистику
        try:
            if game.winner != "draw":
                # У победителя - выигрыш, у проигравшего - проигрыш
                loser = game.player2_id if game.winner == game.player1_id else game.player1_id
                winnings = int(game.bet_amount * 2 * 0.9) - game.bet_amount  # Чистый выигрыш
                
                db.increment_dan_win(game.winner, winnings)
                db.increment_dan_lose(loser, game.bet_amount)
            else:
                # При ничьей оба теряют комиссию
                commission = int(game.bet_amount * 0.1)
                db.increment_dan_lose(game.player1_id, commission)
                db.increment_dan_lose(game.player2_id, commission)
        except Exception as e:
            print(f"Ошибка обновления статистики: {e}")
    
    return result

# Функция для очистки старых игр (вызывается периодически)
def cleanup_old_ttt_games():
    """Очистить старые игры (старше 10 минут)"""
    current_time = int(time.time())
    to_remove = []
    
    for game_id, game in active_tic_tac_toe_games.items():
        if current_time - game.created_at > 600:  # 10 минут
            to_remove.append(game_id)
            
    for game_id in to_remove:
        del active_tic_tac_toe_games[game_id]
        
    return len(to_remove)
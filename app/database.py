import sqlite3
import logging
from datetime import datetime, timedelta
from app.config import DB_FILE

logger = logging.getLogger(__name__)

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# Aliases to prevent any missing import errors across modules
get_db = get_db_connection

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # User Profiles Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            phone_number TEXT,
            target_exam TEXT,
            age INTEGER,
            gender TEXT,
            is_verified INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Quiz Attempts Log Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            questions_attempted INTEGER,
            correct_answers INTEGER,
            score REAL,
            attempt_date DATE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Extra Bonus Quota Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bonus_quota (
            user_id INTEGER PRIMARY KEY,
            boost_count INTEGER DEFAULT 0,
            extra_questions INTEGER DEFAULT 0,
            last_boost_date DATE
        )
    ''')
    
    conn.commit()
    conn.close()

def save_user_profile(user_id, full_name, username, phone, target_exam, age, gender):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, full_name, username, phone_number, target_exam, age, gender, is_verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            full_name=excluded.full_name,
            username=excluded.username,
            phone_number=excluded.phone_number,
            target_exam=excluded.target_exam,
            age=excluded.age,
            gender=excluded.gender,
            is_verified=1
    ''', (user_id, full_name, username, phone, target_exam, age, gender))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_attempts(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    cursor.execute('''
        SELECT SUM(questions_attempted) as total 
        FROM quiz_attempts 
        WHERE user_id = ? AND attempt_date = ?
    ''', (user_id, ist_today))
    row = cursor.fetchone()
    conn.close()
    return row['total'] if row and row['total'] else 0

def increment_today_attempts(user_id, count=1, correct=0, score=0.0):
    """Logs quiz attempts into the database to track daily quotas and scores."""
    conn = get_db_connection()
    cursor = conn.cursor()
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO quiz_attempts (user_id, questions_attempted, correct_answers, score, attempt_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, count, correct, score, ist_today))
    conn.commit()
    conn.close()

def reset_user_quiz_data(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM bonus_quota WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_bonus_quota(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bonus_quota WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"boost_count": 0, "extra_questions": 0}

def boost_user_daily_quota(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    cursor.execute("SELECT * FROM bonus_quota WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute('''
            INSERT INTO bonus_quota (user_id, boost_count, extra_questions, last_boost_date)
            VALUES (?, 1, 20, ?)
        ''', (user_id, ist_today))
        new_count, new_extra = 1, 20
    else:
        current_count = row['boost_count']
        if current_count >= 5:
            conn.close()
            return False, "MAX_LIMIT_REACHED", current_count, row['extra_questions']
        
        new_count = current_count + 1
        new_extra = row['extra_questions'] + 20
        cursor.execute('''
            UPDATE bonus_quota 
            SET boost_count = ?, extra_questions = ?, last_boost_date = ?
            WHERE user_id = ?
        ''', (new_count, new_extra, ist_today, user_id))
        
    conn.commit()
    conn.close()
    return True, "SUCCESS", new_count, new_extra
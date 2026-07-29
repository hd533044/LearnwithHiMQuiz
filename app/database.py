import sqlite3
import os
from datetime import date
from app.config import DB_FILE

def get_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # User details table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            phone_number TEXT,
            target_exam TEXT,
            age INTEGER DEFAULT 21,
            gender TEXT DEFAULT 'Not Specified',
            is_verified INTEGER DEFAULT 0,
            joined_date TEXT
        )
        """)
        
        # Table to track seen questions per user for non-repeating algorithm
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_seen_questions (
            user_id INTEGER,
            question_id INTEGER,
            PRIMARY KEY (user_id, question_id)
        )
        """)
        
        # Daily usage tracking table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id INTEGER,
            usage_date TEXT,
            questions_attempted INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )
        """)
        
        # Detailed quiz test results
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            quiz_id TEXT,
            score REAL,
            total_questions INTEGER,
            correct_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            time_taken_sec INTEGER DEFAULT 0,
            attempt_date TEXT
        )
        """)

        conn.commit()

def save_user_profile(user_id: int, full_name: str, username: str, phone: str, target_exam: str, age: int, gender: str):
    with get_db() as conn:
        conn.execute("""
        INSERT INTO users (user_id, full_name, username, phone_number, target_exam, age, gender, is_verified, joined_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            full_name=?, username=?, phone_number=?, target_exam=?, age=?, gender=?, is_verified=1
        """, (user_id, full_name, username, phone, target_exam, age, gender, str(date.today()),
              full_name, username, phone, target_exam, age, gender))
        conn.commit()

def get_user_profile(user_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    with get_db() as conn:
        return conn.execute("SELECT * FROM users ORDER BY joined_date DESC").fetchall()

def get_seen_question_ids(user_id: int) -> set:
    with get_db() as conn:
        rows = conn.execute("SELECT question_id FROM user_seen_questions WHERE user_id = ?", (user_id,)).fetchall()
        return {row["question_id"] for row in rows}

def mark_questions_as_seen(user_id: int, question_ids: list):
    with get_db() as conn:
        for q_id in question_ids:
            conn.execute("""
            INSERT OR IGNORE INTO user_seen_questions (user_id, question_id)
            VALUES (?, ?)
            """, (user_id, q_id))
        conn.commit()

def reset_user_seen_questions(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM user_seen_questions WHERE user_id = ?", (user_id,))
        conn.commit()

def get_today_attempts(user_id: int) -> int:
    today = str(date.today())
    with get_db() as conn:
        res = conn.execute(
            "SELECT questions_attempted FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today)
        ).fetchone()
        return res["questions_attempted"] if res else 0

def increment_today_attempts(user_id: int, count: int = 1):
    today = str(date.today())
    with get_db() as conn:
        conn.execute("""
        INSERT INTO daily_usage (user_id, usage_date, questions_attempted)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, usage_date) DO UPDATE SET questions_attempted = questions_attempted + ?
        """, (user_id, today, count, count))
        conn.commit()

def record_quiz_result(user_id: int, quiz_id: str, score: float, total_questions: int, correct_count: int, skipped_count: int, time_taken: int):
    with get_db() as conn:
        conn.execute("""
        INSERT INTO quiz_attempts (user_id, quiz_id, score, total_questions, correct_count, skipped_count, time_taken_sec, attempt_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, quiz_id, score, total_questions, correct_count, skipped_count, time_taken, str(date.today())))
        conn.commit()
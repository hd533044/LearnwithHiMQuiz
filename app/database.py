import sqlite3
import logging
from datetime import datetime, timedelta
from app.config import DB_FILE

logger = logging.getLogger(__name__)

def get_db_connection():
    """Establishes and returns an SQLite database connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

get_db = get_db_connection

def init_db():
    """Initializes all database tables required for the Quiz Bot."""
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
    
    # Quiz Attempts Log Table (Updated with full analytics support)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            quiz_id TEXT DEFAULT 'computer_awareness_mock',
            questions_attempted INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0,
            time_taken INTEGER DEFAULT 0,
            attempt_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

    # Non-Repeating Question Tracking Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question_id TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, question_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def save_user_profile(user_id, full_name, username, phone, target_exam, age, gender):
    """Saves or updates a student profile."""
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
    """Fetches user profile by user_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    """Fetches all registered users ordered by creation date."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_attempts(user_id):
    """Calculates total questions attempted today by user in IST time."""
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
    """Logs quiz attempts into database to track daily quotas and scores."""
    conn = get_db_connection()
    cursor = conn.cursor()
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO quiz_attempts (user_id, questions_attempted, total_questions, correct_answers, score, attempt_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, count, count, correct, score, ist_today))
    conn.commit()
    conn.close()

def record_quiz_result(user_id, quiz_id="computer_awareness_mock", score=0.0, total_questions=0, correct_count=0, skipped_count=0, time_taken=0, **kwargs):
    """Fully compatible helper function for logging quiz completions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO quiz_attempts (user_id, quiz_id, questions_attempted, total_questions, correct_answers, skipped_count, score, time_taken, attempt_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, quiz_id, total_questions, total_questions, correct_count, skipped_count, score, time_taken, ist_today))
    conn.commit()
    conn.close()

def save_quiz_result(user_id, questions_attempted, correct_answers, score, **kwargs):
    record_quiz_result(user_id=user_id, score=score, total_questions=questions_attempted, correct_count=correct_answers)

def get_user_test_history(user_id):
    """Retrieves full quiz performance statistics for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) as total_quizzes, 
               SUM(questions_attempted) as total_questions,
               SUM(correct_answers) as total_correct,
               AVG(score) as avg_score
        FROM quiz_attempts 
        WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"total_quizzes": 0, "total_questions": 0, "total_correct": 0, "avg_score": 0.0}

def get_seen_question_ids(user_id):
    """Returns a set of question IDs already attempted by the user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT question_id FROM seen_questions WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return {str(r['question_id']) for r in rows}

def save_seen_question_id(user_id, question_id):
    """Marks a single question ID as seen for the user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO seen_questions (user_id, question_id)
        VALUES (?, ?)
    ''', (user_id, str(question_id)))
    conn.commit()
    conn.close()

def save_seen_question_ids(user_id, question_ids):
    """Batch marks multiple question IDs as seen for the user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    for qid in question_ids:
        cursor.execute('''
            INSERT OR IGNORE INTO seen_questions (user_id, question_id)
            VALUES (?, ?)
        ''', (user_id, str(qid)))
    conn.commit()
    conn.close()

def mark_questions_as_seen(user_id, question_ids):
    """Marks question IDs as seen safely."""
    if isinstance(question_ids, (list, set, tuple)):
        save_seen_question_ids(user_id, question_ids)
    else:
        save_seen_question_id(user_id, question_ids)

def mark_question_as_seen(user_id, question_id):
    save_seen_question_id(user_id, question_id)

def reset_user_quiz_data(user_id):
    """Clears all quiz attempts, bonus limit logs, and seen questions history for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM bonus_quota WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM seen_questions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_bonus_quota(user_id):
    """Retrieves granted bonus quota for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bonus_quota WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"boost_count": 0, "extra_questions": 0}

def boost_user_daily_quota(user_id):
    """Grants +20 extra daily limit boost (Max 5 boosts total)."""
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
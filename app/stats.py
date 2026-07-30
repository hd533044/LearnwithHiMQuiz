from app.database import get_db

def get_quiz_toppers(quiz_id: str = None, limit: int = 10):
    with get_db() as conn:
        if quiz_id:
            query = """
            SELECT u.full_name, u.username, u.target_exam, u.user_id, MAX(q.score) as avg_score 
            FROM quiz_attempts q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.quiz_id = ?
            GROUP BY q.user_id
            ORDER BY avg_score DESC
            LIMIT ?
            """
            return conn.execute(query, (quiz_id, limit)).fetchall()
        else:
            query = """
            SELECT u.full_name, u.username, u.target_exam, u.user_id, AVG(q.score) as avg_score 
            FROM quiz_attempts q
            JOIN users u ON q.user_id = u.user_id
            GROUP BY q.user_id
            ORDER BY avg_score DESC
            LIMIT ?
            """
            return conn.execute(query, (limit,)).fetchall()

def calculate_user_rank(user_id: int):
    with get_db() as conn:
        query = """
        SELECT user_id, AVG(score) as avg_score,
               RANK() OVER (ORDER BY AVG(score) DESC) as user_rank
        FROM quiz_attempts
        GROUP BY user_id
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            if row["user_id"] == user_id:
                return row["user_rank"]
        return "N/A"

def calculate_overall_performance(user_id: int):
    with get_db() as conn:
        stats = conn.execute("""
        SELECT AVG(CASE WHEN COALESCE(total_questions, 0) > 0 THEN (score / total_questions) * 100 ELSE score * 5 END) as avg_pct, COUNT(*) as total_tests
        FROM quiz_attempts
        WHERE user_id = ?
        """, (user_id,)).fetchone()
        
        if not stats or stats["total_tests"] == 0 or stats["avg_pct"] is None:
            return 0.0, 0
        return round(stats["avg_pct"], 2), stats["total_tests"]
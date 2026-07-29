from app.config import DAILY_QUESTION_LIMIT
from app.database import (
    get_today_attempts, 
    increment_today_attempts, 
    record_quiz_result,
    get_seen_question_ids,
    mark_questions_as_seen
)
from app.pyq_fetcher import fetch_pyqs_for_quiz

ACTIVE_QUIZZES = {}

def start_quiz_session(user_id: int, requested_count: int = 20, timer_sec: int = 15):
    attempted_today = get_today_attempts(user_id)
    
    if attempted_today >= DAILY_QUESTION_LIMIT:
        return None, f"Brother, you have reached your daily practice limit of {DAILY_QUESTION_LIMIT} questions! Excellent practice. Please attempt again tomorrow!"
    
    remaining_quota = DAILY_QUESTION_LIMIT - attempted_today
    session_count = min(requested_count, remaining_quota)
    
    # Retrieve set of all question IDs previously seen by this user
    seen_ids = get_seen_question_ids(user_id)
    
    # Fetch completely unseen questions from all 21 connected batch files
    selected_questions = fetch_pyqs_for_quiz(needed_count=session_count, seen_ids=seen_ids)
    
    if not selected_questions:
        return None, "You have completed all available questions in the question bank! Outstanding achievement."

    # Lock these question IDs into SQLite permanently for this user
    selected_ids = [q["id"] for q in selected_questions if q.get("id") is not None]
    mark_questions_as_seen(user_id, selected_ids)
    
    session = {
        "user_id": user_id,
        "questions": selected_questions,
        "current_index": 0,
        "score": 0.0,
        "correct_count": 0,
        "skipped_count": 0,
        "total": len(selected_questions),
        "timer_sec": timer_sec,
        "is_paused": False,
        "active_poll_id": None
    }
    
    ACTIVE_QUIZZES[user_id] = session
    increment_today_attempts(user_id, len(selected_questions))
    
    remaining_after = remaining_quota - len(selected_questions)
    return session, f"Quiz Session Started! ({len(selected_questions)} Unique Questions selected from all batches). Remaining daily quota: {remaining_after}"

def get_active_session(user_id: int):
    return ACTIVE_QUIZZES.get(user_id)

def finish_quiz_session(user_id: int):
    session = ACTIVE_QUIZZES.pop(user_id, None)
    if session:
        record_quiz_result(
            user_id=user_id,
            quiz_id="computer_awareness_mock",
            score=session["score"],
            total_questions=session["total"],
            correct_count=session["correct_count"],
            skipped_count=session["skipped_count"],
            time_taken=0
        )
    return session
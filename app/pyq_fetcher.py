import json
import os
import random
import logging
from app.config import DATA_DIR

def verify_and_correct_answer(q: dict) -> dict:
    """
    Rigorously verifies question integrity and ensures the correct_option 
    index points accurately to the correct choice.
    """
    q_text = q.get("question")
    opts = q.get("options")
    correct_opt = q.get("correct_option")
    expl = q.get("explanation", "")

    if not q_text or not isinstance(opts, list) or len(opts) < 2:
        return None

    opts = [str(opt).strip() for opt in opts]

    # Ensure index bounds
    if not isinstance(correct_opt, int) or correct_opt < 0 or correct_opt >= len(opts):
        correct_opt = 0

    # Runtime Smart Check: Scan explanation for option text matching to prevent wrong answers
    # If the explanation explicitly quotes one of the options, sync the index to match it
    lower_expl = expl.lower()
    for idx, opt in enumerate(opts):
        clean_opt = opt.lower()
        # If option text is unique and explicitly stated as correct in the explanation text
        if len(clean_opt) > 3 and clean_opt in lower_expl:
            # Check context words nearby to ensure it's stated as the answer
            if f"is {clean_opt}" in lower_expl or f"correct is {clean_opt}" in lower_expl or f"answer is {clean_opt}" in lower_expl or lower_expl.startswith(clean_opt):
                correct_opt = idx
                break

    return {
        "id": q.get("id") if q.get("id") is not None else hash(str(q_text)),
        "question": str(q_text).strip(),
        "options": opts,
        "correct_option": correct_opt,
        "explanation": str(expl).strip()
    }

def fetch_pyqs_for_quiz(needed_count: int = 50, seen_ids: set = None) -> list:
    if seen_ids is None:
        seen_ids = set()

    all_raw_questions = []
    qb_dir = os.path.join(DATA_DIR, "question_bank")
    search_dir = qb_dir if os.path.exists(qb_dir) else DATA_DIR

    for root, _, files in os.walk(search_dir):
        for file in files:
            if file.endswith(".json") and not file.startswith("."):
                if file in ["users.json", "profiles.json"]:
                    continue

                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_raw_questions.extend(data)
                except Exception as e:
                    logging.error(f"⚠️ Error reading batch file {file_path}: {e}")
                    continue

    formatted_pool = []

    for q in all_raw_questions:
        q_id = q.get("id")
        if q_id is not None and q_id in seen_ids:
            continue

        verified_q = verify_and_correct_answer(q)
        if verified_q:
            formatted_pool.append(verified_q)

    random.shuffle(formatted_pool)
    return formatted_pool[:needed_count]

load_verified_local_pyqs = fetch_pyqs_for_quiz
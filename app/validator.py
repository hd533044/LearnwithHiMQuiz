def validate_question(q: dict) -> bool:
    """Validates the schema of a question dictionary."""
    required_keys = ["id", "question", "options", "correct_option"]
    if not all(key in q for key in required_keys):
        return False
    if not isinstance(q["options"], list) or len(q["options"]) < 2:
        return False
    if not isinstance(q["correct_option"], int) or q["correct_option"] < 0 or q["correct_option"] >= len(q["options"]):
        return False
    return True
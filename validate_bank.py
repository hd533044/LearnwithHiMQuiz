import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Target question_bank directory directly to ignore system/user DB files
DATA_DIR = os.path.join(BASE_DIR, "data", "question_bank")

def validate_question_bank():
    total_valid = 0
    total_errors = 0

    print("🔍 Scanning data/question_bank/ directory for batch files...\n")

    if not os.path.exists(DATA_DIR):
        print("❌ data/question_bank/ folder not found!")
        return

    for root, _, files in os.walk(DATA_DIR):
        for file in files:
            if file.endswith(".json") and not file.startswith("."):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            for idx, q in enumerate(data):
                                if not all(k in q for k in ["id", "question", "options", "correct_option"]):
                                    print(f"❌ [{file}] Item {idx}: Missing required keys")
                                    total_errors += 1
                                    continue
                                
                                options = q["options"]
                                correct_idx = q["correct_option"]

                                if not isinstance(options, list) or len(options) < 2:
                                    print(f"❌ [{file}] ID {q.get('id')}: Options must be a list with at least 2 choices")
                                    total_errors += 1
                                    continue

                                if not isinstance(correct_idx, int) or correct_idx < 0 or correct_idx >= len(options):
                                    print(f"❌ CRITICAL ERROR in [{file}] ID {q.get('id')}: correct_option index '{correct_idx}' is out of bounds for options count {len(options)}")
                                    total_errors += 1
                                    continue

                                total_valid += 1
                except Exception as e:
                    print(f"❌ Failed to parse {file}: {e}")

    print("=" * 60)
    print(f"✅ Total Valid Questions Verified & Ready: {total_valid}")
    print(f"❌ Total Errors Detected: {total_errors}")
    print("=" * 60)

if __name__ == "__main__":
    validate_question_bank()
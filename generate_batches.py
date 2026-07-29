import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "question_bank")
os.makedirs(DATA_DIR, exist_ok=True)

def save_batch(batch_number: int, questions: list):
    filename = os.path.join(DATA_DIR, f"batch_{batch_number:03d}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved Batch {batch_number} with {len(questions)} questions -> {filename}")

if __name__ == "__main__":
    print("Batch Generator initialized. Save JSON batches directly into data/question_bank/.")
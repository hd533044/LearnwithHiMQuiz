import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "question_bank")

def verify_all_batches():
    print("🔍 Starting Deep Verification of Question Bank...\n")
    
    if not os.path.exists(DATA_DIR):
        print(f"❌ Directory not found: {DATA_DIR}")
        return

    total_files = 0
    total_questions = 0
    total_errors = 0

    for root, _, files in os.walk(DATA_DIR):
        for file in sorted(files):
            if file.endswith(".json") and not file.startswith("."):
                file_path = os.path.join(root, file)
                total_files += 1
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        questions = json.load(f)

                    if not isinstance(questions, list):
                        print(f"❌ [{file}] Must contain a JSON array/list of questions.")
                        total_errors += 1
                        continue

                    file_errors = 0

                    for idx, q in enumerate(questions):
                        total_questions += 1
                        q_id = q.get("id", f"Index {idx}")

                        # 1. Check Question Text
                        q_text = q.get("question")
                        if not q_text or not isinstance(q_text, str) or len(q_text.strip()) == 0:
                            print(f"❌ [{file} | ID: {q_id}] Question text is missing or empty.")
                            file_errors += 1

                        # 2. Check Options List
                        options = q.get("options")
                        if not isinstance(options, list) or len(options) < 2:
                            print(f"❌ [{file} | ID: {q_id}] Must have at least 2 options (found {len(options) if isinstance(options, list) else 0}).")
                            file_errors += 1
                            continue

                        # Check for empty options
                        for opt_idx, opt in enumerate(options):
                            if not str(opt).strip():
                                print(f"❌ [{file} | ID: {q_id}] Option {opt_idx} is empty.")
                                file_errors += 1

                        # Check for duplicate options in the same question
                        if len(set([str(o).strip().lower() for o in options])) != len(options):
                            print(f"⚠️ [{file} | ID: {q_id}] Duplicate option values detected: {options}")

                        # 3. Check Correct Option Index & Match
                        correct_opt = q.get("correct_option")
                        
                        if not isinstance(correct_opt, int):
                            print(f"❌ [{file} | ID: {q_id}] 'correct_option' must be an integer index (found {type(correct_opt).__name__}: {correct_opt}).")
                            file_errors += 1
                        elif correct_opt < 0 or correct_opt >= len(options):
                            print(f"❌ [{file} | ID: {q_id}] 'correct_option' index ({correct_opt}) is OUT OF BOUNDS for {len(options)} options.")
                            file_errors += 1

                    total_errors += file_errors
                    if file_errors == 0:
                        print(f"✅ [{file}] Verifed {len(questions)} questions successfully.")

                except Exception as e:
                    print(f"❌ [{file}] JSON Syntax Error: {e}")
                    total_errors += 1

    print("\n" + "=" * 60)
    print(f"📊 SUMMARY:")
    print(f"• Total Files Scanned: {total_files}")
    print(f"• Total Questions Verified: {total_questions}")
    print(f"• Total Integrity Errors: {total_errors}")
    print("=" * 60)

    if total_errors > 0:
        print("\n⚠️ Please fix the reported errors above to guarantee 100% accurate answer marking.")
    else:
        print("\n🎉 ALL QUESTIONS PASSED INTEGRITY VERIFICATION! Safe to run.")

if __name__ == "__main__":
    verify_all_batches()
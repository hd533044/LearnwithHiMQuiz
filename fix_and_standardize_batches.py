import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def fix_and_standardize():
    fixed_files_count = 0
    total_fixed_questions = 0

    print("🛠️ Starting automated batch repair and key standardization...\n")

    for root, _, files in os.walk(DATA_DIR):
        for file in files:
            if file.endswith(".json") and not file.startswith("."):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    if not isinstance(data, list):
                        continue

                    fixed_list = []
                    file_modified = False

                    for idx, item in enumerate(data):
                        if not isinstance(item, dict):
                            continue

                        # Extract ID or assign a fallback sequential ID
                        q_id = item.get("id")
                        if q_id is None:
                            q_id = 100000 + (fixed_files_count * 1000) + idx
                            file_modified = True

                        # Extract question text from all possible key variations
                        q_text = (
                            item.get("question") or 
                            item.get("question_en") or 
                            item.get("question_text") or 
                            item.get("q_text")
                        )

                        # Extract options list from all possible key variations
                        opts = (
                            item.get("options") or 
                            item.get("options_en") or 
                            item.get("choices")
                        )

                        # Extract correct option index from all possible key variations
                        correct_opt = (
                            item.get("correct_option") if "correct_option" in item else
                            item.get("correct_idx") if "correct_idx" in item else
                            item.get("answer") if "answer" in item else 0
                        )

                        # Extract explanation
                        expl = (
                            item.get("explanation") or 
                            item.get("explanation_en") or 
                            "Practice computer awareness daily!"
                        )

                        # Verify & Fix structure
                        if q_text and isinstance(opts, list) and len(opts) >= 2:
                            # If correct_option is text, find its index in options
                            if isinstance(correct_opt, str):
                                try:
                                    correct_opt = opts.index(correct_opt)
                                except ValueError:
                                    correct_opt = 0
                                file_modified = True

                            # Boundary guard
                            if not isinstance(correct_opt, int) or correct_opt < 0 or correct_opt >= len(opts):
                                correct_opt = 0
                                file_modified = True

                            standardized_item = {
                                "id": int(q_id),
                                "question": str(q_text).strip(),
                                "options": [str(opt).strip() for opt in opts],
                                "correct_option": int(correct_opt),
                                "explanation": str(expl).strip()
                            }
                            fixed_list.append(standardized_item)
                            total_fixed_questions += 1
                        else:
                            print(f"⚠️ Skipped invalid item {idx} in {file}: text or options missing.")

                    # Overwrite file with standardized clean format
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(fixed_list, f, ensure_ascii=False, indent=2)

                    fixed_files_count += 1
                    print(f"✅ Fixed & Standardized: {file} ({len(fixed_list)} questions)")

                except Exception as e:
                    print(f"❌ Failed to process {file}: {e}")

    print("\n" + "=" * 60)
    print(f"🎉 Complete! Processed {fixed_files_count} files and standardized {total_fixed_questions} questions.")
    print("=" * 60)

if __name__ == "__main__":
    fix_and_standardize()
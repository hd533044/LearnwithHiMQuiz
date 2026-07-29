import json
from groq import Groq
from app.config import GROQ_API_KEY

def generate_questions_from_text(text_content: str, num_questions: int = 5) -> list:
    """Uses Groq API to convert raw text/PDF data into structured question JSON objects."""
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not defined in your .env file.")

    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""
    Generate {num_questions} multiple choice questions based on the provided text.
    Return ONLY a valid raw JSON array of objects with these exact keys:
    "id" (integer), "question" (string), "options" (list of 4 strings), "correct_option" (index integer 0-3).

    Source Text:
    {text_content[:4000]}
    """

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are an exam generator outputting raw JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    try:
        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        return json.loads(raw_text.strip())
    except Exception as e:
        print(f"Error parsing Groq response: {e}")
        return []
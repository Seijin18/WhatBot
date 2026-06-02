import os
from google import genai

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("Defina GEMINI_API_KEY no ambiente (veja .env.example).")

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Escreva um haiku sobre testes de API.",
)
print(response.text)

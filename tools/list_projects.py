import os
import sys
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import YOUGILE_API_KEY

url = "https://yougile.com/api-v2/projects"
headers = {
    "Authorization": f"Bearer {YOUGILE_API_KEY}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()
    print("DEBUG ответ API:", data)  # ← временно для проверки структуры
    if isinstance(data, list):
        print("Список проектов:")
        for p in data:
            print(f"{p.get('id')} - {p.get('name')}")
    elif isinstance(data, dict):
        # иногда API возвращает словарь с ключом "projects" или "items"
        projects = data.get("projects") or data.get("items") or []
        print("Список проектов:")
        for p in projects:
            print(f"{p.get('id')} - {p.get('name')}")
    else:
        print("Неожиданный формат ответа:", type(data))
else:
    print("Ошибка:", response.status_code, response.text)

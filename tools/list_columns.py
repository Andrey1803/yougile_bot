import os
import sys
import requests
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import YOUGILE_API_KEY

url = "https://yougile.com/api-v2/columns"
headers = {
    "Authorization": f"Bearer {YOUGILE_API_KEY}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    try:
        data = response.json()
    except Exception:
        print("Ответ не JSON:", response.text)
        sys.exit(1)

    print("DEBUG ответ API:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    if isinstance(data, list):
        print("\nСписок колонок:")
        for col in data:
            if isinstance(col, dict):
                print(f"{col.get('id')} - {col.get('title')} (projectId={col.get('projectId')})")
            else:
                print("Элемент не dict:", col)
    elif isinstance(data, dict):
        print("Пришёл словарь, ключи:", data.keys())
    else:
        print("Неожиданный тип:", type(data))
else:
    print("Ошибка:", response.status_code, response.text)

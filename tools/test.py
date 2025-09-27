import os
import sys
import requests

# Добавляем корень проекта в sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import YOUGILE_API_KEY, PROJECT_ID

url = f"https://yougile.com/api-v2/projects/{PROJECT_ID}"
headers = {
    "Authorization": f"Bearer {YOUGILE_API_KEY}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    project = response.json()
    print(f"Проект: {project.get('title')}")
    print("Список колонок:")
    for col in project.get("columns", []):
        print(f"{col['id']} - {col['title']}")
else:
    print("Ошибка:", response.status_code, response.text)

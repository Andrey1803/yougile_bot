import requests
from config import YOUGILE_API_KEY, COLUMN_ID

API_URL = "https://yougile.com/api-v2"

def create_task(title: str, description: str = ""):
    """
    Создаёт задачу в YouGile в указанной колонке.
    """
    url = f"{API_URL}/tasks"
    headers = {
        "Authorization": f"Bearer {YOUGILE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title.strip() or "Новый заказ",
        "description": description or "",
        "columnId": COLUMN_ID
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code in (200, 201):   # ✅ учитываем оба варианта
        return response.json()
    else:
        raise Exception(f"{response.status_code} {response.text}")

import re, json, os
from datetime import datetime

DATA_DIR = "data"
USER_FILE_DATA = os.path.join(DATA_DIR, "users.json")
ORDER_FILE_DATA = os.path.join(DATA_DIR, "orders.log")

# Загружаем текущих пользователей
users = {}
if os.path.exists(USER_FILE_DATA):
    with open(USER_FILE_DATA, "r", encoding="utf-8", errors="ignore") as f:
        try:
            users = json.load(f)
        except:
            users = {}

# Читаем заказы
with open(ORDER_FILE_DATA, "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()

# Ищем клиентов вида "Клиент: Имя (id: 123456789)"
matches = re.findall(r"Клиент:\s*(.+?)\s*\(id:\s*(\d+)\)", text)

added = 0
for full_name, uid in matches:
    if uid not in users:
        users[uid] = {
            "joined": datetime.now().isoformat(),
            "username": None,
            "full_name": full_name.strip()
        }
        added += 1

# Сохраняем обновлённый список
os.makedirs(DATA_DIR, exist_ok=True)
with open(USER_FILE_DATA, "w", encoding="utf-8") as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

print(f"✅ Восстановлено пользователей: {len(users)} (новых добавлено: {added})")

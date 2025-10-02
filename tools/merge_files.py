import json
import os

# Пути
DATA_DIR = "data"
USER_FILE_DATA = os.path.join(DATA_DIR, "users.json")
ORDER_FILE_DATA = os.path.join(DATA_DIR, "orders.log")

USER_FILE_ROOT = "users.json"
ORDER_FILE_ROOT = "orders.log"

def safe_read(path):
    """Пробуем открыть файл в разных кодировках"""
    for enc in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""

# --- USERS.JSON ---
users = {}

# Загружаем из data/users.json
if os.path.exists(USER_FILE_DATA):
    with open(USER_FILE_DATA, "r", encoding="utf-8", errors="ignore") as f:
        try:
            users.update(json.load(f))
        except:
            pass

# Загружаем из корня users.json
if os.path.exists(USER_FILE_ROOT):
    with open(USER_FILE_ROOT, "r", encoding="utf-8", errors="ignore") as f:
        try:
            for uid, data in json.load(f).items():
                if uid not in users:
                    users[uid] = data
        except:
            pass

# Сохраняем объединённый результат в data/users.json
os.makedirs(DATA_DIR, exist_ok=True)
with open(USER_FILE_DATA, "w", encoding="utf-8") as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

print(f"✅ Объединено пользователей: {len(users)}")

# --- ORDERS.LOG ---
orders = []

if os.path.exists(ORDER_FILE_DATA):
    orders.append(safe_read(ORDER_FILE_DATA))

if os.path.exists(ORDER_FILE_ROOT):
    orders.append(safe_read(ORDER_FILE_ROOT))

with open(ORDER_FILE_DATA, "w", encoding="utf-8") as f:
    f.write("\n\n".join([o.strip() for o in orders if o.strip()]))

print("✅ Заказы объединены в data/orders.log")

# --- Удаляем лишние файлы из корня ---
for file in [USER_FILE_ROOT, ORDER_FILE_ROOT]:
    if os.path.exists(file):
        os.remove(file)
        print(f"🗑 Удалён лишний файл: {file}")

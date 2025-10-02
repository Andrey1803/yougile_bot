import json
import os

DATA_DIR = "data"
USER_FILE_DATA = os.path.join(DATA_DIR, "users.json")

# Снимок пользователей (можно дополнять вручную)
snapshot = [
    {"id": "5630959281", "username": None, "joined": "2025-09-25T18:14:32.904821"},
    {"id": "5630959286", "username": "Emelyanau", "joined": "2025-09-28T09:50:49.865362"},
    {"id": "5185981742", "username": "Natalli18asd", "joined": "2025-09-28T09:54:11.998403"},
    {"id": "5612879733", "username": None, "joined": "2025-09-28T10:33:08.379015"},
    {"id": "514845836", "username": "kris_tina_one", "joined": "2025-09-30T17:53:06.999509"},
    {"id": "1369730816", "username": None, "joined": "2025-10-01T10:42:52.547194"},
    {"id": "957991913", "username": None, "joined": "2025-10-01T16:46:25.208781"},
]

# Загружаем текущих пользователей
users = {}
if os.path.exists(USER_FILE_DATA):
    with open(USER_FILE_DATA, "r", encoding="utf-8", errors="ignore") as f:
        try:
            users = json.load(f)
        except:
            users = {}

# Сливаем данные
added = 0
for u in snapshot:
    uid = u["id"]
    if uid not in users:
        users[uid] = {
            "joined": u["joined"],
            "username": u["username"],
            "full_name": None
        }
        added += 1

# Сохраняем результат
os.makedirs(DATA_DIR, exist_ok=True)
with open(USER_FILE_DATA, "w", encoding="utf-8") as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

print(f"✅ Всего пользователей: {len(users)} (новых добавлено: {added})")

"""
HTTP-клиент YouGile API v2.

Синхронные функции (requests) — вызываются из async-хендлеров через
`asyncio.to_thread()` в main.py, чтобы не блокировать event loop.
"""
import time
import logging
import requests
from config import YOUGILE_API_KEY, COLUMN_ID

logger = logging.getLogger(__name__)

API_URL = "https://yougile.com/api-v2"
TIMEOUT = 15  # секунд
MAX_RETRIES = 3


def _headers() -> dict:
    """Заголовки для запросов к YouGile API."""
    return {
        "Authorization": f"Bearer {YOUGILE_API_KEY}",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, **kwargs) -> requests.Response:
    """
    Обёртка над requests с таймаутом и retry при 429/5xx.
    """
    url = f"{API_URL}{path}"
    kwargs.setdefault("timeout", TIMEOUT)

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=_headers(), **kwargs)
            # Retry на 429 и 5xx
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(
                        f"YouGile {resp.status_code} на {method} {path}, "
                        f"retry {attempt}/{MAX_RETRIES} через {wait}с"
                    )
                    time.sleep(wait)
                    continue
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    f"Сетевая ошибка на {method} {path}: {e}, "
                    f"retry {attempt}/{MAX_RETRIES} через {wait}с"
                )
                time.sleep(wait)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Не удалось выполнить {method} {path} после {MAX_RETRIES} попыток")


# ─── Публичный API ──────────────────────────────────────────────────────────

def create_task(title: str, description: str = "") -> dict:
    """Создаёт задачу в YouGile в указанной колонке."""
    payload = {
        "title": (title or "Новый заказ").strip(),
        "description": description or "",
        "columnId": COLUMN_ID,
    }
    resp = _request("POST", "/tasks", json=payload)
    if resp.status_code in (200, 201):
        return resp.json()
    raise Exception(f"YouGile create_task: {resp.status_code} {resp.text}")


def search_tasks_by_user(user_id: str, limit: int = 10) -> list:
    """
    Ищет задачи по ID пользователя.

    ВАЖНО: GET /tasks в YouGile НЕ возвращает description.
    Поэтому фильтрация идёт по title, куда мы кладём маркер [uid:<id>]
    при создании задачи (см. create_task_with_user).
    Фоллбэк: если в title нет маркера — возвращаем последние `limit` задач.
    """
    resp = _request("GET", "/tasks", params={"limit": limit})
    if resp.status_code not in (200, 201):
        raise Exception(f"YouGile search_tasks_by_user: {resp.status_code} {resp.text}")

    data = resp.json()
    tasks = data if isinstance(data, list) else data.get("tasks", [])

    marker = f"[uid:{user_id}]"
    matched = [t for t in tasks if marker in (t.get("title") or "")]
    if matched:
        return matched

    # Фоллбэк — возвращаем последние задачи (для /status без маркера)
    return tasks


def get_task_status(task_id: str) -> dict:
    """Получает информацию о задаче (статус, колонка и т.д.)."""
    resp = _request("GET", f"/tasks/{task_id}")
    if resp.status_code in (200, 201):
        return resp.json()
    raise Exception(f"YouGile get_task_status: {resp.status_code} {resp.text}")


def get_tasks_for_stats(days: int = 30) -> list:
    """
    Получает задачи за последние N дней (фильтрация по дате создания).
    """
    from datetime import datetime, timedelta, timezone

    resp = _request("GET", "/tasks", params={"limit": 500})
    if resp.status_code not in (200, 201):
        raise Exception(f"YouGile get_tasks_for_stats: {resp.status_code} {resp.text}")

    data = resp.json()
    tasks = data if isinstance(data, list) else data.get("tasks", [])

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    for t in tasks:
        created = t.get("created") or t.get("createdAt")
        if not created:
            result.append(t)
            continue
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if dt >= cutoff:
                result.append(t)
        except (ValueError, TypeError):
            result.append(t)
    return result


# ─── Кэш названий колонок ───────────────────────────────────────────────────
_columns_cache: dict[str, str] = {}


def get_column_name(column_id: str) -> str:
    """
    Получает название колонки по ID. Кэширует результат в памяти.
    """
    if not column_id:
        return "—"
    if column_id in _columns_cache:
        return _columns_cache[column_id]

    resp = _request("GET", f"/columns/{column_id}")
    if resp.status_code in (200, 201):
        name = resp.json().get("title", column_id)
        _columns_cache[column_id] = name
        return name
    return column_id
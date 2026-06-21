import calendar
import hashlib
import logging
import re
from datetime import date
from typing import Any

import requests

from config import (
    DISPATCHER_API_URL,
    DISPATCHER_COMPANY_NAME,
    DISPATCHER_EXTERNAL_REF_PER_ADDRESS,
    DISPATCHER_GROUP_ID,
    DISPATCHER_GROUP_NAME,
    DISPATCHER_INBOUND_API_KEY,
    DISPATCHER_INBOUND_INITIAL_STATUS,
    DISPATCHER_MAINTENANCE_INTERVAL_MONTHS,
    DISPATCHER_MAINTENANCE_NEXT_DUE_YMD,
    DISPATCHER_MAINTENANCE_NOTE,
    DISPATCHER_MAINTENANCE_PLAN,
    DISPATCHER_MAINTENANCE_PRELIMINARY_DAYS,
)

logger = logging.getLogger(__name__)

_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _local_today_ymd() -> str:
    t = date.today()
    return f"{t.year:04d}-{t.month:02d}-{t.day:02d}"


def _add_months_from_date(d: date, months: int) -> date:
    month0 = d.month - 1 + months
    year = d.year + month0 // 12
    month = month0 % 12 + 1
    last = calendar.monthrange(year, month)[1]
    day = min(d.day, last)
    return date(year, month, day)


def _add_months_ymd(ymd: str, months: int) -> str:
    raw = ymd.strip()
    m = _YMD_RE.match(raw)
    if not m:
        return ymd
    y, mo, da = int(raw[0:4]), int(raw[5:7]), int(raw[8:10])
    out = _add_months_from_date(date(y, mo, da), months)
    return f"{out.year:04d}-{out.month:02d}-{out.day:02d}"


def _normalize_address_key(addr: str) -> str:
    s = (addr or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s[:400]


def _external_ref(*, telegram_user_id: str, address: str) -> str:
    if DISPATCHER_EXTERNAL_REF_PER_ADDRESS:
        norm = _normalize_address_key(address)
        if norm and norm not in ("—", "-", "none", "нет"):
            h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
            return f"tg:{telegram_user_id}|{h}"
    return f"tg:{telegram_user_id}"


def build_external_ref(telegram_user_id: str, address: str) -> str:
    """Стабильный externalRef для inbound-order (как в send_order_to_dispatcher)."""
    return _external_ref(telegram_user_id=telegram_user_id, address=address)


def _enabled() -> bool:
    return bool(DISPATCHER_API_URL and DISPATCHER_INBOUND_API_KEY)


def dispatcher_inbound_ready() -> bool:
    """URL, ключ и маршрут (группа или компания) заданы."""
    if not _enabled():
        return False
    return bool(DISPATCHER_GROUP_ID or DISPATCHER_COMPANY_NAME)


def describe_dispatcher_config() -> str:
    """Краткий статус интеграции для логов и /dispatcher_ping."""
    parts: list[str] = []
    if not DISPATCHER_API_URL:
        parts.append("DISPATCHER_API_URL не задан")
    else:
        parts.append(f"URL={DISPATCHER_API_URL}")
    if not DISPATCHER_INBOUND_API_KEY:
        parts.append("DISPATCHER_INBOUND_API_KEY не задан")
    elif len(DISPATCHER_INBOUND_API_KEY) < 16:
        parts.append("ключ API < 16 символов (диспетчер отклонит)")
    else:
        parts.append("ключ API задан")
    if DISPATCHER_GROUP_ID:
        parts.append(f"groupId={DISPATCHER_GROUP_ID[:12]}…")
    elif DISPATCHER_COMPANY_NAME:
        gn = DISPATCHER_GROUP_NAME or "Заявки Telegram"
        parts.append(f"company={DISPATCHER_COMPANY_NAME!r}, group={gn!r}")
    else:
        parts.append("нет DISPATCHER_GROUP_ID и DISPATCHER_COMPANY_NAME")
    if DISPATCHER_MAINTENANCE_PLAN:
        parts.append("MAINTENANCE_PLAN=on")
    return "; ".join(parts)


def dispatcher_inbound_record_id(disp: dict[str, Any]) -> str | None:
    """ID созданной записи в диспетчере: заявка (leadId) или задача (taskId)."""
    lid = disp.get("leadId")
    if lid:
        return str(lid)
    tid = disp.get("taskId")
    return str(tid) if tid else None


def format_dispatcher_result_for_admin(disp: dict[str, Any]) -> str:
    """Текст для уведомления админа о результате send_order_to_dispatcher."""
    if disp.get("skipped"):
        reason = disp.get("reason") or "unknown"
        hints = {
            "dispatcher_env_missing": "задайте DISPATCHER_API_URL и DISPATCHER_INBOUND_API_KEY на Railway (бот)",
            "no_group_or_company": "задайте DISPATCHER_GROUP_ID или DISPATCHER_COMPANY_NAME",
        }
        hint = hints.get(str(reason), describe_dispatcher_config())
        return f"⚠️ Диспетчер пропущен ({reason}): {hint}"
    if disp.get("ok") and dispatcher_inbound_record_id(disp):
        gid = disp.get("groupId")
        extra = f"\n📂 groupId: <code>{gid}</code>" if gid else ""
        if disp.get("reused"):
            return f"♻️ Диспетчер: повторный заказ → заявка <code>{disp.get('leadId')}</code>{extra}"
        if disp.get("leadId"):
            return f"✅ Диспетчер: заявка <code>{disp['leadId']}</code>{extra}"
        return f"✅ Диспетчер: задача <code>{disp['taskId']}</code>{extra}"
    err = disp.get("error") or "неизвестная ошибка"
    return f"⚠️ Диспетчер не записал задачу: <code>{err}</code>"


def ping_dispatcher_integration(*, timeout_sec: float = 15) -> dict[str, Any]:
    """Тестовый POST inbound-order (заголовок TEST, не путать с реальным заказом)."""
    if not dispatcher_inbound_ready():
        return {
            "ok": False,
            "skipped": True,
            "reason": "not_configured",
            "error": describe_dispatcher_config(),
        }
    payload: dict[str, Any] = {
        "title": "Тест интеграции Telegram→Диспетчер",
        "contactName": "Тест",
        "customerPhone": "+70000000000",
        "objectAddress": "тест",
        "externalSource": "telegram",
        "externalRef": f"tg:ping:{int(__import__('time').time())}",
        "note": "Автотест /dispatcher_ping",
        "initialStatus": "PRELIMINARY",
    }
    if DISPATCHER_GROUP_ID:
        payload["groupId"] = DISPATCHER_GROUP_ID
    else:
        payload["companyName"] = DISPATCHER_COMPANY_NAME
        if DISPATCHER_GROUP_NAME:
            payload["groupName"] = DISPATCHER_GROUP_NAME
    return post_inbound_order_payload(payload, timeout_sec=timeout_sec)


def _days_until_ymd(due_ymd: str) -> int | None:
    """(дата ТО − сегодня) в днях; отрицательно = просрочено. None если формат неверен."""
    raw = (due_ymd or "").strip()
    if not _YMD_RE.match(raw):
        return None
    y, mo, da = int(raw[0:4]), int(raw[5:7]), int(raw[8:10])
    try:
        due = date(y, mo, da)
    except ValueError:
        return None
    return (due - date.today()).days


def initial_status_for_maintenance_next_due(due_ymd: str) -> str:
    """
    Колонка «Предварительно» только если до следующего ТО осталось не больше
    DISPATCHER_MAINTENANCE_PRELIMINARY_DAYS дней (включая уже просроченные).
    Иначе — «К выполнению» (OPEN).
    """
    d = _days_until_ymd(due_ymd)
    if d is None:
        return "OPEN"
    if d <= DISPATCHER_MAINTENANCE_PRELIMINARY_DAYS:
        return "PRELIMINARY"
    return "OPEN"


def post_inbound_order_payload(payload: dict[str, Any], *, timeout_sec: float = 25) -> dict[str, Any]:
    """
    POST готового тела к /v1/integration/inbound-order.
    Не бросает исключения; ответ как у send_order_to_dispatcher.
    """
    if not _enabled():
        return {"ok": False, "skipped": True, "reason": "dispatcher_env_missing", "taskId": None, "leadId": None, "error": None}

    url = f"{DISPATCHER_API_URL}/v1/integration/inbound-order"
    headers = {
        "Authorization": f"Bearer {DISPATCHER_INBOUND_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        logger.info("Dispatcher: POST inbound-order → %s", url)
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
        if resp.status_code in (200, 201):
            data = resp.json()
            if isinstance(data, dict):
                lid = data.get("leadId")
                tid = data.get("taskId")
                logger.info("Dispatcher inbound created: leadId=%s taskId=%s", lid, tid)
                return {
                    "ok": True,
                    "skipped": False,
                    "leadId": lid,
                    "taskId": tid,
                    "groupId": data.get("groupId"),
                    "stage": data.get("stage"),
                    "error": None,
                    "raw": data,
                }
            logger.error("Dispatcher API: unexpected JSON shape: %s", str(data)[:300])
            return {"ok": False, "skipped": False, "taskId": None, "error": "invalid_json_shape"}
        err_text = (resp.text or "")[:800]
        err_msg = err_text
        try:
            j = resp.json()
            if isinstance(j, dict) and j.get("error"):
                err_msg = str(j["error"])
        except Exception:
            pass
        logger.error("Dispatcher API error: %s %s url=%s", resp.status_code, err_msg, url)
        return {
            "ok": False,
            "skipped": False,
            "taskId": None,
            "error": f"HTTP {resp.status_code}: {err_msg}",
            "status_code": resp.status_code,
        }
    except requests.RequestException as err:
        logger.error(
            "Dispatcher RequestException %s: %s url=%s",
            type(err).__name__,
            err,
            url,
            exc_info=True,
        )
        return {"ok": False, "skipped": False, "taskId": None, "error": f"{type(err).__name__}: {err}"}
    except Exception as err:
        logger.error(
            "Dispatcher unexpected %s: %s url=%s",
            type(err).__name__,
            err,
            url,
            exc_info=True,
        )
        return {"ok": False, "skipped": False, "taskId": None, "error": str(err)}


def send_order_to_dispatcher(
    *,
    category: str,
    name: str,
    phone: str,
    address: str,
    comment: str,
    telegram_user_id: str,
    telegram_full_name: str,
) -> dict[str, Any]:
    """
    Отправляет заказ в API «Диспетчер задач».
    Не бросает исключения наружу для пользовательского флоу.
    Возвращает словарь с ключами ok, skipped, taskId, error (для логов и уведомления админа).
    """
    if not _enabled():
        return {"ok": False, "skipped": True, "reason": "dispatcher_env_missing", "taskId": None, "leadId": None, "error": None}

    title = f"Заказ: {category} — {name}".strip()[:500] or "Новый заказ из Telegram"
    note = (
        f"Клиент: {telegram_full_name} (tg id: {telegram_user_id})\n"
        f"Комментарий: {comment or '—'}\n"
        f"Источник: Telegram bot"
    )
    payload: dict[str, Any] = {
        "title": title,
        "contactName": name or "",
        "customerPhone": phone or "",
        "objectAddress": address or "",
        "externalSource": "telegram",
        "externalRef": _external_ref(telegram_user_id=telegram_user_id, address=address),
        "note": note,
    }
    if DISPATCHER_GROUP_ID:
        payload["groupId"] = DISPATCHER_GROUP_ID
    elif DISPATCHER_COMPANY_NAME:
        payload["companyName"] = DISPATCHER_COMPANY_NAME
        if DISPATCHER_GROUP_NAME:
            payload["groupName"] = DISPATCHER_GROUP_NAME
    else:
        logger.warning(
            "Dispatcher integration enabled but route is undefined: set DISPATCHER_GROUP_ID or DISPATCHER_COMPANY_NAME",
        )
        return {"ok": False, "skipped": True, "reason": "no_group_or_company", "taskId": None, "error": None}

    if DISPATCHER_MAINTENANCE_PLAN:
        im = DISPATCHER_MAINTENANCE_INTERVAL_MONTHS
        payload["maintenanceEnabled"] = True
        payload["maintenanceIntervalMonths"] = im
        next_due = DISPATCHER_MAINTENANCE_NEXT_DUE_YMD
        if next_due and _YMD_RE.match(next_due):
            next_ymd = next_due
        else:
            next_ymd = _add_months_ymd(_local_today_ymd(), im)
        payload["maintenanceNextDueYmd"] = next_ymd
        if DISPATCHER_MAINTENANCE_NOTE:
            payload["maintenanceNote"] = DISPATCHER_MAINTENANCE_NOTE
        payload["initialStatus"] = initial_status_for_maintenance_next_due(next_ymd)
    else:
        st0 = DISPATCHER_INBOUND_INITIAL_STATUS.upper()
        if st0 in ("PRELIMINARY", "OPEN"):
            payload["initialStatus"] = st0

    return post_inbound_order_payload(payload, timeout_sec=20)


def fetch_customer_order_status(phone: str, *, group_id: str | None = None, timeout_sec: float = 12) -> dict[str, Any]:
    """Статус заявки/задачи в диспетчере по телефону клиента."""
    if not _enabled():
        return {"ok": False, "skipped": True, "reason": "dispatcher_env_missing", "found": False}
    base = (DISPATCHER_API_URL or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "skipped": True, "reason": "no_url", "found": False}
    params: dict[str, str] = {"phone": (phone or "").strip()}
    if group_id:
        params["groupId"] = group_id.strip()
    url = f"{base}/v1/integration/customer-order-status"
    headers = {
        "Authorization": f"Bearer {DISPATCHER_INBOUND_API_KEY}",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout_sec)
        if resp.status_code >= 400:
            logger.warning("Dispatcher customer-order-status HTTP %s: %s", resp.status_code, resp.text[:200])
            return {"ok": False, "error": f"HTTP {resp.status_code}", "found": False}
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"ok": False, "error": "bad_json", "found": False}
    except Exception as e:
        logger.exception("Dispatcher customer-order-status failed")
        return {"ok": False, "error": str(e), "found": False}

#!/usr/bin/env python3
"""Read-only диагностика OAuth-токенов аккаунтов (scripts/oauth_status_check.py).

Для всех аккаунтов из data/accounts.json строит таблицу:
    resume_hash | mode | oauth_present | oauth_expires_in | recommended_action

Источники данных — только локальные файлы: accounts.json, config.json и кэш
OAuth-токенов, который app.oauth читает при импорте. Скрипт ничего не пишет
на диск и не ходит в сеть.

Коды возврата:
    0 — успех (включая отсутствие data/accounts.json);
    1 — data/accounts.json не читается или имеет неверный формат.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Код бота использует относительные пути (app.config: DATA_DIR = Path("data")),
# поэтому прибиваем рабочую директорию к корню репо и добавляем его в импорты.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.config import CONFIG, load_config  # noqa: E402
from app import oauth as app_oauth  # noqa: E402

ACCOUNTS_FILE = Path("data") / "accounts.json"

# Порог (в часах), ниже которого живой токен рекомендуется ротировать.
ROTATE_THRESHOLD_HOURS = 48

# Тексты рекомендуемых действий (используются и в таблице, и в --json выводе).
ACTION_NO_HASH = "указать resume_hash"
ACTION_NO_TOKEN = "пройти OAuth-flow"
ACTION_EXPIRED_NO_REFRESH = "повторная авторизация"
ACTION_ROTATE = "запустить rotate_oauth_tokens.py --apply"
ACTION_OK = "ок"

TABLE_HEADERS = ("resume_hash", "mode", "oauth_present", "oauth_expires_in", "recommended_action")


def parse_args() -> argparse.Namespace:
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Read-only диагностика OAuth-токенов аккаунтов из data/accounts.json: "
        "показывает статус каждого токена и рекомендуемое действие.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="вывести машиночитаемый JSON вместо таблицы",
    )
    return parser.parse_args()


def load_accounts() -> list:
    """Загрузить список аккаунтов из data/accounts.json.

    Возвращает None, если файла нет (нормальная ситуация для первого запуска).
    Читает файл напрямую, а не через app.config.load_accounts(), потому что
    та функция при отсутствии файла создаёт его, а этот скрипт read-only.
    """
    if not ACCOUNTS_FILE.exists():
        return None
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Ошибка чтения {ACCOUNTS_FILE}: {e}")
        sys.exit(1)
    if not isinstance(data, list):
        print(f"Ошибка: в {ACCOUNTS_FILE} ожидался JSON-список аккаунтов, "
              f"получен {type(data).__name__}")
        sys.exit(1)
    return data


def has_cached_entry(resume_hash: str) -> bool:
    """Есть ли запись OAuth-токена в кэше (живая или истёкшая).

    Повторяет логику поиска app.oauth.get_oauth_status: сначала точный ключ
    resume_hash, затем composite-ключи вида 'resume_hash::account_key'.
    Нужно, чтобы отличать «токен истёк» (EXPIRED) от «токена никогда не было» (-).
    """
    tokens = getattr(app_oauth, "_oauth_tokens", None)
    if not isinstance(tokens, dict) or not resume_hash:
        return False
    if resume_hash in tokens:
        return True
    prefix = f"{resume_hash}::"
    return any(k.startswith(prefix) for k in tokens)


def format_expires(status: dict, entry_exists: bool) -> str:
    """Человекочитаемый срок жизни токена: '312h', 'EXPIRED' или '-'."""
    if status["has_token"]:
        return f"{status['expires_hours']}h"
    return "EXPIRED" if entry_exists else "-"


def recommend_action(resume_hash: str, status: dict, entry_exists: bool) -> str:
    """Эвристика рекомендуемого действия по OAuth-токену аккаунта."""
    if not resume_hash:
        return ACTION_NO_HASH
    has_token = status["has_token"]
    expires_hours = status["expires_hours"]
    has_refresh = status["has_refresh"]
    if has_token:
        # Токен жив: если до истечения мало времени и есть refresh — ротируем.
        if expires_hours < ROTATE_THRESHOLD_HOURS and has_refresh:
            return ACTION_ROTATE
        return ACTION_OK
    # Живого токена нет.
    if entry_exists and has_refresh:
        # Токен истёк, но есть refresh_token: ротация его обновит
        # (refresh_oauth_tokens_proactive обновляет в т.ч. истёкшие токены).
        return ACTION_ROTATE
    if entry_exists:
        # Токен истёк и refresh_token отсутствует.
        return ACTION_EXPIRED_NO_REFRESH
    # Записи токена нет вовсе.
    return ACTION_NO_TOKEN


def collect_rows(accounts: list) -> list:
    """Собрать диагностические строки по всем аккаунтам."""
    rows = []
    for acc in accounts:
        if not isinstance(acc, dict):
            acc = {}  # битый элемент списка показываем как аккаунт без resume_hash
        resume_hash = str(acc.get("resume_hash") or "").strip()
        mode = str(acc.get("mode") or CONFIG.default_client_mode)
        if resume_hash:
            status = app_oauth.get_oauth_status(resume_hash)
            entry_exists = has_cached_entry(resume_hash)
        else:
            status = {"has_token": False, "expires_hours": 0, "has_refresh": False}
            entry_exists = False
        rows.append({
            "resume_hash": resume_hash,
            "mode": mode,
            "oauth_present": status["has_token"],
            "oauth_expires_in": format_expires(status, entry_exists),
            "expires_hours": status["expires_hours"],
            "has_refresh": status["has_refresh"],
            "recommended_action": recommend_action(resume_hash, status, entry_exists),
        })
    return rows


def render_table(rows: list) -> str:
    """Выровненная таблица по заголовкам TABLE_HEADERS."""
    lines = []
    for r in rows:
        lines.append((
            r["resume_hash"] or "-",
            r["mode"],
            "yes" if r["oauth_present"] else "no",
            r["oauth_expires_in"],
            r["recommended_action"],
        ))
    widths = []
    for i, header in enumerate(TABLE_HEADERS):
        width = len(header)
        for line in lines:
            width = max(width, len(line[i]))
        widths.append(width)
    out = [" | ".join(h.ljust(w) for h, w in zip(TABLE_HEADERS, widths))]
    out.append("-+-".join("-" * w for w in widths))
    for line in lines:
        out.append(" | ".join(cell.ljust(w) for cell, w in zip(line, widths)))
    return "\n".join(out)


def main() -> int:
    args = parse_args()

    load_config()  # подтягивает CONFIG.default_client_mode из data/config.json
    accounts = load_accounts()

    if accounts is None:
        # Файла аккаунтов нет: в --json режиме отдаём валидный пустой результат.
        if args.json:
            print(json.dumps({
                "total_accounts": 0,
                "live_tokens": 0,
                "need_action": 0,
                "default_client_mode": CONFIG.default_client_mode,
                "accounts": [],
            }, ensure_ascii=False, indent=2))
        else:
            print(f"{ACCOUNTS_FILE} не найден — аккаунты не настроены, проверять нечего.")
        return 0

    rows = collect_rows(accounts)
    total = len(rows)
    live = sum(1 for r in rows if r["oauth_present"])
    need_action = sum(1 for r in rows if r["recommended_action"] != ACTION_OK)

    if args.json:
        print(json.dumps({
            "total_accounts": total,
            "live_tokens": live,
            "need_action": need_action,
            "default_client_mode": CONFIG.default_client_mode,
            "accounts": rows,
        }, ensure_ascii=False, indent=2))
        return 0

    print(render_table(rows))
    print()
    print(f"Всего аккаунтов:   {total}")
    print(f"Живые OAuth-токены: {live}")
    print(f"Требуют действий:  {need_action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

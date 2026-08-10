#!/usr/bin/env python3
"""Ротация OAuth-токенов HH.ru (dry-run по умолчанию).

Пробегает все токены из data/oauth_tokens.json и для каждого определяет
вердикт: expires_at < now + --threshold-hours → нужен refresh.

По умолчанию — DRY-RUN: файл читается напрямую через json.load (без импорта
app.oauth), ничего не записывается и никаких сетевых запросов не делается.
Печатается таблица `key | expires_at | осталось | refresh_token? | вердикт`
и сводка.

С флагом --apply поверх dry-run-списка выполняется реальный refresh через
штатный механизм бота.

ВАЖНО: в брифе упоминался `oauth._refresh_token()`, но такой функции в
app/oauth.py НЕТ (проверено). Вместо неё используется
`app.oauth.refresh_oauth_tokens_proactive(min_ttl_hours=N)` — это штатный
механизм ротации: пробегает все сохранённые токены, держит per-resume_hash
locks (чтобы не было параллельного refresh одного refresh_token), делает
fallback на второй client_id, сам пишет результат на диск и дедуплицирует
записи по refresh_token.

Про дубликаты: ключ в файле — либо `<resume_hash>` (plain), либо composite
`<resume_hash>::<account_key>`. Plain-ключ — backward-compat копия composite
с тем же refresh_token, поэтому при подсчётах он НЕ дублируется: сводка
считается по уникальным refresh_token'ам, а копии в таблице помечаются "(dup)".

Exit codes: 0 — успех (в т.ч. файла нет или ротировать нечего; при --apply
failed > 0 тоже exit 0, но с warning), 1 — скрипт сам упал (нечитаемый файл,
ошибка импорта/refresh).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Все пути в коде бота относительные — работаем из корня репо.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

OAUTH_FILE = Path("data/oauth_tokens.json")
DEFAULT_THRESHOLD_HOURS = 24.0

EPILOG = """\
Примеры:
  python3 scripts/rotate_oauth_tokens.py                        # dry-run: таблица и сводка
  python3 scripts/rotate_oauth_tokens.py --threshold-hours 48   # порог "скоро истекут" = 48ч
  python3 scripts/rotate_oauth_tokens.py --apply                # реальный refresh (HTTP к hh.ru!)
"""


def _is_number(v):
    """True для int/float, но не bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _format_duration(seconds: float) -> str:
    """Секунды → '2д 3ч' / '5ч 07м' / '45м'."""
    total_min = int(max(0.0, seconds) // 60)
    days, rem = divmod(total_min, 60 * 24)
    hours, minutes = divmod(rem, 60)
    if days:
        return f"{days}д {hours}ч"
    if hours:
        return f"{hours}ч {minutes:02d}м"
    return f"{minutes}м"


def _format_remaining(seconds: float) -> str:
    """Секунды до истечения → человекочитаемое 'осталось' (отрицательные → 'истёк ... назад')."""
    if seconds < 0:
        return f"истёк {_format_duration(-seconds)} назад"
    return _format_duration(seconds)


def _verdict(expires_at, now: float, threshold_ts: float) -> str:
    """Вердикт для записи: expired / needs refresh / ok / битая запись."""
    if not _is_number(expires_at):
        return "битая запись"
    if expires_at <= now:
        return "expired"
    if expires_at < threshold_ts:
        return "needs refresh"
    return "ok"


def load_tokens():
    """Читает data/oauth_tokens.json напрямую (json.load), без импорта app.oauth.

    Returns: (data: dict|None, status: 'ok'|'missing'|'error', message: str|None)
    """
    if not OAUTH_FILE.exists():
        return None, "missing", f"Файл {OAUTH_FILE} не найден — сохранённых токенов нет, ротировать нечего."
    try:
        with open(OAUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, "error", f"Не удалось прочитать {OAUTH_FILE}: {e}"
    if not isinstance(data, dict):
        return None, "error", f"Неожиданный формат {OAUTH_FILE}: ожидался объект dict, получено {type(data).__name__}"
    return data, "ok", None


def dry_run(tokens: dict, threshold_hours: float) -> dict:
    """Печатает таблицу вердиктов и сводку. Возвращает счётчики.

    Сводка считается по УНИКАЛЬНЫМ refresh_token'ам: composite-ключи
    (<hash>::<account>) идут первыми и становятся «представителями»,
    plain-копии (<hash>) с тем же refresh_token помечаются "(dup)".
    """
    now = time.time()
    threshold_ts = now + threshold_hours * 3600

    # composite-ключи первыми: они канонические, plain <hash> — backward-compat копия
    keys = sorted((str(k) for k in tokens.keys()), key=lambda k: (0 if "::" in k else 1, k))

    seen_refresh = set()
    rows = []
    counts = {"ok": 0, "needs refresh": 0, "expired": 0}
    no_refresh = 0  # валидные записи без refresh_token (refresh невозможен)
    broken = 0      # не-dict записи или без числового expires_at
    dup_count = 0   # дубликаты refresh_token (plain-копии composite-ключей)

    for key in keys:
        rec = tokens.get(key)
        valid = isinstance(rec, dict)
        rec = rec if valid else {}

        expires_at = rec.get("expires_at")
        refresh = rec.get("refresh_token") or ""

        dup = False
        if refresh:
            if refresh in seen_refresh:
                dup = True
                dup_count += 1
            else:
                seen_refresh.add(refresh)

        verdict = _verdict(expires_at, now, threshold_ts)
        if not valid or verdict == "битая запись":
            broken += 1
        elif not refresh:
            no_refresh += 1
        elif not dup:
            # счётчики ok/needs/expired — строго по уникальным refresh_token'ам
            counts[verdict] += 1

        if _is_number(expires_at):
            exp_str = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M:%S")
            rem_str = _format_remaining(expires_at - now)
        else:
            exp_str, rem_str = "—", "—"

        verdict_str = verdict + (" (dup)" if dup else "")
        if valid and verdict != "битая запись" and not refresh:
            verdict_str += " (нет refresh_token)"
        rows.append((
            key,
            exp_str,
            rem_str,
            "да" if refresh else "нет",
            verdict_str,
        ))

    # Таблица
    headers = ("key", "expires_at", "осталось", "refresh_token?", "вердикт")
    if rows:
        widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(5)]
    else:
        widths = [len(h) for h in headers]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(r[i].ljust(widths[i]) for i in range(5)))

    candidates = counts["needs refresh"] + counts["expired"]
    print()
    print("Сводка (ok/needs refresh/expired считаются по уникальным refresh_token'ам):")
    print(f"  Всего записей:            {len(rows)}")
    print(f"  Уникальных refresh_token: {len(seen_refresh)} (дубликатов-копий: {dup_count})")
    print(f"  ok:                       {counts['ok']}")
    print(f"  needs refresh:            {counts['needs refresh']}")
    print(f"  expired:                  {counts['expired']}")
    print(f"  без refresh_token:        {no_refresh}")
    if broken:
        print(f"  битых записей:            {broken}")
    print(f"  Порог: refresh нужен при expires_at < now + {threshold_hours:g}ч")

    return {"candidates": candidates, "counts": counts, "no_refresh": no_refresh}


def apply_refresh(threshold_hours: float, candidates: int) -> int:
    """Реальный refresh через штатный механизм app.oauth. Возвращает exit code."""
    # Ленивый импорт только при --apply: dry-run не должен трогать app.oauth.
    try:
        from app.oauth import refresh_oauth_tokens_proactive
    except Exception as e:
        print(f"Ошибка импорта app.oauth: {e}")
        return 1

    # refresh_oauth_tokens_proactive(min_ttl_hours) пробегает ВСЕ токены и
    # обновляет те, у кого expires_at < now + min_ttl_hours (тот же порог,
    # что в dry-run выше); per-key locks, fallback client и запись на диск — внутри.
    ttl = int(threshold_hours) if float(threshold_hours).is_integer() else threshold_hours
    try:
        stats = refresh_oauth_tokens_proactive(min_ttl_hours=ttl)
    except Exception as e:
        print(f"Ошибка при выполнении refresh: {e}")
        return 1

    refreshed = int(stats.get("refreshed", 0))
    failed = int(stats.get("failed", 0))
    checked = int(stats.get("checked", 0))
    unchanged = max(0, candidates - refreshed - failed)

    print()
    print("== Результат refresh_oauth_tokens_proactive ==")
    print(f"  checked:   {checked}")
    print(f"  refreshed: {refreshed}")
    print(f"  failed:    {failed}")
    print()
    print("== Итог ротации ==")
    print(f"  refreshed:     {refreshed}")
    print(f"  failed:        {failed}")
    print(f"  без изменений: {unchanged}")

    if failed > 0:
        print(f"WARNING: {failed} refresh(es) завершились с ошибкой — проверьте логи бота "
              f"(возможно, refresh_token отозван или истёк).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ротация OAuth-токенов HH.ru: dry-run по умолчанию, --apply для реального refresh.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="выполнить реальный refresh (по умолчанию — только dry-run чтение файла)")
    parser.add_argument("--threshold-hours", type=float, default=DEFAULT_THRESHOLD_HOURS,
                        metavar="N",
                        help=f'порог "скоро истекут" в часах (default: {DEFAULT_THRESHOLD_HOURS:g})')
    args = parser.parse_args(argv)

    if args.threshold_hours < 0:
        print("--threshold-hours не может быть отрицательным")
        return 1

    tokens, status, msg = load_tokens()
    if status == "missing":
        print(msg)
        return 0
    if status == "error":
        print(msg)
        return 1

    print(f"Токены: {OAUTH_FILE} (записей: {len(tokens)})")
    print()
    summary = dry_run(tokens, args.threshold_hours)

    if not args.apply:
        print()
        print("Dry-run: файл не изменён. Запустите с --apply для реального refresh.")
        return 0

    if summary["candidates"] == 0:
        print()
        print("Все токены свежие — ротация не требуется.")
        return 0

    print()
    print(f"Запуск refresh для {summary['candidates']} уникальных refresh_token(ов)...")
    return apply_refresh(args.threshold_hours, summary["candidates"])


if __name__ == "__main__":
    sys.exit(main())

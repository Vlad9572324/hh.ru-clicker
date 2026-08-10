#!/usr/bin/env python3
"""Миграция: добавляет поле "mode" в записи data/accounts.json и data/browser_sessions.json.

Для каждого dict'а в списках, у которого ещё нет ключа "mode", добавляет
"mode" со значением из флага --mode (по умолчанию "auto"). Записи, у которых
"mode" уже есть, не трогаем. Ключи с префиксом "_" — runtime-состояние,
скрипт их не читает и не изменяет.

По умолчанию скрипт работает в режиме dry-run: печатает план и ничего не
записывает. Реальная запись выполняется только с флагом --apply. Перед любой
записью оригиналы файлов копируются в data/backup/YYYY-MM-DD/ (при повторном
запуске в тот же день к имени файла в backup добавляется суффикс _HHMMSS).

Exit codes: 0 — успех или нечего делать, 1 — ошибка.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Пути в коде бота относительные (DATA_DIR = Path("data")), поэтому
# переходим в корень репозитория и делаем его видимым для импорта.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = Path("data")
BACKUP_ROOT = DATA_DIR / "backup"
TARGET_FILES = ("accounts.json", "browser_sessions.json")
VALID_MODES = ("web", "mobile", "auto")

log = logging.getLogger("migrate_accounts_add_mode")


def _setup_logging() -> None:
    """Логи идут в stdout — единый поток с print'ами плана."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stdout,
    )


def _load_list(path: Path):
    """Прочитать JSON-список. Возвращает (данные, ошибка); ошибка == "missing",
    если файла нет."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (json.JSONDecodeError, OSError) as e:
        return None, str(e)
    if not isinstance(data, list):
        return None, f"ожидался список объектов, а не {type(data).__name__}"
    return data, None


def _atomic_write_json(path: Path, data) -> None:
    """Атомарная запись JSON (tmp + replace) с chmod 0o600 — в файлах PII."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)  # chmod до replace: цель никогда не бывает 0o644
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _atomic_copy(src: Path, dst: Path) -> None:
    """Атомарно скопировать файл байт-в-байт (для rollback) + chmod 0o600."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copy2(src, tmp)  # copy2 сохраняет mtime оригинала
        os.chmod(tmp, 0o600)
        tmp.replace(dst)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _backup_files(paths: list) -> list:
    """Backup оригиналов в data/backup/YYYY-MM-DD/ с сохранением имён файлов.

    Если файл с таким именем в backup этого дня уже есть (повторный запуск),
    к имени добавляется суффикс _HHMMSS: accounts.json -> accounts.json_153012
    (суффикс в конце, чтобы glob 'accounts.json*' при rollback его находил).
    Возвращает список созданных backup-файлов."""
    backup_dir = BACKUP_ROOT / datetime.now().strftime("%Y-%m-%d")
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_dir.chmod(0o700)  # внутри PII (cookies)
    except OSError:
        pass
    created = []
    for src in paths:
        if not src.exists():
            continue
        dst = backup_dir / src.name
        if dst.exists():
            dst = backup_dir / f"{src.name}_{datetime.now().strftime('%H%M%S')}"
        shutil.copy2(src, dst)
        try:
            dst.chmod(0o600)
        except OSError:
            pass
        created.append(dst)
    return created


def _migration_stats(records: list):
    """План по одному файлу: сколько записей получат mode, у скольких он уже
    есть (разбивка по значениям), сколько записей не-dict (пропускаем)."""
    will_add = 0
    already = {}
    non_dict = 0
    for rec in records:
        if not isinstance(rec, dict):
            non_dict += 1
            continue
        if "mode" in rec:
            value = rec["mode"]
            key = value if isinstance(value, str) else repr(value)
            already[key] = already.get(key, 0) + 1
        else:
            will_add += 1
    return will_add, already, non_dict


def cmd_migrate(args) -> int:
    """Добавить отсутствующий "mode" в записи (dry-run / --apply)."""
    mode = args.mode
    statuses = {}       # имя файла -> "missing" | "error" | "ok"
    records_by_name = {}

    for name in TARGET_FILES:
        data, err = _load_list(DATA_DIR / name)
        if err == "missing":
            statuses[name] = "missing"
        elif err is not None:
            statuses[name] = "error"
            log.error("%s: %s", DATA_DIR / name, err)
        else:
            statuses[name] = "ok"
            records_by_name[name] = data

    if all(s == "missing" for s in statuses.values()):
        print("Файлы accounts.json и browser_sessions.json в data/ не найдены — мигрировать нечего.")
        return 0
    if any(s == "error" for s in statuses.values()):
        return 1

    # План
    print(f"План миграции {'(dry-run — записи не будет)' if not args.apply else '(--apply)'}:")
    changed = {}
    for name in TARGET_FILES:
        path = DATA_DIR / name
        if statuses[name] == "missing":
            print(f"  {path}: файла нет — пропускаю")
            continue
        records = records_by_name[name]
        will_add, already, non_dict = _migration_stats(records)
        already_str = ", ".join(f"{k}={v}" for k, v in sorted(already.items())) or "—"
        print(
            f"  {path}: записей {len(records)} — получат mode='{mode}': {will_add}, "
            f"уже имеют mode: {sum(already.values())} ({already_str})"
        )
        if non_dict:
            log.warning("%s: %d записей не являются объектами — они не трогаются", path, non_dict)
        if will_add:
            changed[name] = (records, will_add)

    if not changed:
        print("Все записи уже имеют поле 'mode' — нечего делать.")
        return 0
    if not args.apply:
        print("Dry-run: изменения не применены. Повторите с --apply, чтобы записать.")
        return 0

    # Перед записью — backup оригиналов обоих существующих файлов
    originals = [DATA_DIR / n for n in TARGET_FILES if (DATA_DIR / n).exists()]
    for b in _backup_files(originals):
        log.info("backup создан: %s", b)

    for name, (records, will_add) in changed.items():
        for rec in records:
            if isinstance(rec, dict) and "mode" not in rec:
                rec["mode"] = mode  # ключи с префиксом "_" не трогаем
        path = DATA_DIR / name
        _atomic_write_json(path, records)
        log.info("записано: %s (mode='%s' добавлен в %d записей)", path, mode, will_add)

    print("Миграция завершена.")
    return 0


def cmd_rollback(args) -> int:
    """Восстановить файлы из data/backup/<дата>/ (dry-run / --apply).

    Берёт самые свежие по mtime файлы accounts.json* и browser_sessions.json*
    в указанной backup-директории. Перед записью делает backup текущего
    состояния."""
    date_str = args.rollback
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        log.error("неверный формат даты %r — ожидался YYYY-MM-DD", date_str)
        return 1

    backup_dir = BACKUP_ROOT / date_str
    if not backup_dir.is_dir():
        log.error("backup не найден: %s", backup_dir)
        return 1

    restore_plan = []  # (backup-файл, живой файл)
    for name in TARGET_FILES:
        candidates = [p for p in backup_dir.glob(name + "*") if p.is_file()]
        if not candidates:
            log.warning("в %s нет backup-копии %s", backup_dir, name)
            continue
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        restore_plan.append((newest, DATA_DIR / name))

    if not restore_plan:
        log.error("в %s нет backup-файлов для восстановления", backup_dir)
        return 1

    # Сначала проверяем, что все backup-копии читаются, потом пишем
    validated = []
    for src, dst in restore_plan:
        data, err = _load_list(src)
        if err is not None:
            log.error("backup-копия повреждена (%s): %s", src, err)
            return 1
        validated.append((src, dst, data))

    print(f"План rollback из {backup_dir} {'(dry-run — записи не будет)' if not args.apply else '(--apply)'}:")
    for src, dst, data in validated:
        mtime = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {dst} <- {src.name} (mtime {mtime}, записей: {len(data)})")

    if not args.apply:
        print("Dry-run: изменения не применены. Повторите с --apply, чтобы восстановить.")
        return 0

    # Backup текущего состояния перед откатом
    current = [dst for _, dst, _ in validated if dst.exists()]
    for b in _backup_files(current):
        log.info("backup текущего состояния создан: %s", b)

    for src, dst, _data in validated:
        _atomic_copy(src, dst)
        log.info("восстановлено: %s <- %s", dst, src)

    print("Rollback завершён.")
    return 0


class _Parser(argparse.ArgumentParser):
    """argparse, который при ошибке аргументов выходит с кодом 1, а не 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: ошибка: {message}", file=sys.stderr)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        description=(
            "Добавляет отсутствующее поле 'mode' в записи data/accounts.json и "
            "data/browser_sessions.json. По умолчанию — dry-run, запись по --apply."
        ),
        epilog="""примеры:
  python3 scripts/migrate_accounts_add_mode.py                     # dry-run: план миграции
  python3 scripts/migrate_accounts_add_mode.py --apply             # добавить mode=auto
  python3 scripts/migrate_accounts_add_mode.py --mode mobile --apply
  python3 scripts/migrate_accounts_add_mode.py --rollback 2026-08-10          # dry-run план отката
  python3 scripts/migrate_accounts_add_mode.py --rollback 2026-08-10 --apply  # восстановить из backup
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default="auto",
        help="значение, которым дополнять отсутствующее поле 'mode' (по умолчанию: auto)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="реально записывать файлы (по умолчанию — dry-run)",
    )
    parser.add_argument(
        "--rollback",
        metavar="YYYY-MM-DD",
        help="восстановить файлы из data/backup/<дата>/ вместо миграции",
    )
    return parser


def main(argv=None) -> int:
    _setup_logging()
    args = build_parser().parse_args(argv)
    if args.rollback is not None:
        return cmd_rollback(args)
    return cmd_migrate(args)


if __name__ == "__main__":
    sys.exit(main())

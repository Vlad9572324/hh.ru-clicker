#!/usr/bin/env python3
"""Бэкап и восстановление директории data/.

Backup: создаёт tarball ``backup_YYYYMMDD_HHMMSS.tar.gz`` со всем содержимым
data/. По умолчанию в архив НЕ попадают:
  - логи (``*.log``);
  - вложенные директории ``data/backup/`` и ``data/cache/``
    (кэш восстанавливается отдельно через import_dumps_to_cache.py,
    а backup внутри backup не нужен).

Restore (``--restore TARBALL``): разворачивает tarball обратно в data/.
Перед реальным восстановлением (с ``--apply``) автоматически делает бэкап
текущей data/ тем же механизмом и печатает его путь — чтобы было куда
откатиться.

По умолчанию ЛЮБАЯ операция выполняется в режиме DRY-RUN: скрипт только
печатает список файлов и итоговые пути, ничего не записывая. Реальная запись
происходит только с флагом ``--apply``.

Exit codes: 0 — успех (или нечего делать), 1 — ошибка (нет архива, битый
архив, небезопасные пути внутри архива и т.п.).
"""

import argparse
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path

# Код бота использует относительные пути, поэтому работаем из корня репо.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUT_DIR = REPO_ROOT / "backups"

# Директории внутри data/, исключаемые из бэкапа (на любом уровне вложенности)
EXCLUDE_DIR_NAMES = {"backup", "cache"}


def collect_files(include_logs: bool) -> list[Path]:
    """Собирает файлы data/, которые войдут в бэкап-tarball."""
    if not DATA_DIR.is_dir():
        return []
    result: list[Path] = []
    for path in sorted(DATA_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(DATA_DIR)
        # пропускаем вложенные backup/ и cache/ на любой глубине
        if EXCLUDE_DIR_NAMES.intersection(rel.parts[:-1]):
            continue
        # пропускаем логи, если не задан --include-logs
        if not include_logs and path.suffix.lower() == ".log":
            continue
        result.append(path)
    return result


def create_backup(out_dir: Path, include_logs: bool) -> Path | None:
    """Реально создаёт бэкап. Возвращает путь к tarball или None, если файлов нет."""
    files = collect_files(include_logs)
    if not files:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tarball_path = out_dir / f"backup_{timestamp}.tar.gz"
    with tarfile.open(tarball_path, "w:gz") as tf:
        for file_path in files:
            # arcname — путь относительно data/, чтобы restore разворачивался
            # ровно в data/
            tf.add(file_path, arcname=str(file_path.relative_to(DATA_DIR)))
    return tarball_path


def check_out_dir(out_dir: Path) -> str | None:
    """Возвращает текст ошибки, если out-директория непригодна, иначе None."""
    resolved = out_dir.resolve()
    data_resolved = DATA_DIR.resolve()
    if resolved == data_resolved or data_resolved in resolved.parents:
        return (
            f"out-директория {out_dir} находится внутри data/ — "
            "это приведёт к рекурсии бэкапов. Укажите другой путь."
        )
    return None


def do_backup(out_dir: Path, include_logs: bool, apply: bool) -> int:
    """Режим бэкапа: dry-run (по умолчанию) или реальная запись с --apply."""
    error = check_out_dir(out_dir)
    if error:
        print(f"Ошибка: {error}")
        return 1

    files = collect_files(include_logs)
    if not files:
        print("Нет файлов для бэкапа (data/ пуста или отсутствует). Нечего делать.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tarball_path = out_dir / f"backup_{timestamp}.tar.gz"

    print(f"Файлы, которые войдут в бэкап ({len(files)}):")
    for file_path in files:
        print(f"  {file_path.relative_to(DATA_DIR)}")
    print(f"Итоговый tarball: {tarball_path}")

    if not apply:
        print("DRY-RUN: ничего не записано. Запустите с --apply, чтобы создать бэкап.")
        return 0

    created = create_backup(out_dir, include_logs)
    if created is None:
        print("Нет файлов для бэкапа. Нечего делать.")
        return 0
    print(f"Бэкап создан: {created}")
    return 0


def check_members(members: list[tarfile.TarInfo]) -> list[str]:
    """Возвращает список нарушений в содержимом архива (пусто = всё безопасно)."""
    problems: list[str] = []
    for member in members:
        # принимаем только обычные файлы и директории (без symlink/dev и т.п.)
        if not (member.isreg() or member.isdir()):
            problems.append(f"{member.name}: не обычный файл и не директория")
            continue
        if not member.name:
            problems.append("(пустое имя): недопустимое имя записи")
            continue
        # защита от path traversal: имя не должно быть абсолютным и не
        # должно содержать ".."
        pure = Path(member.name)
        if pure.is_absolute() or ".." in pure.parts:
            problems.append(f"{member.name}: путь выходит за пределы data/ (path traversal)")
    return problems


def do_restore(tarball_arg: str, out_dir: Path, include_logs: bool, apply: bool) -> int:
    """Режим восстановления: dry-run (по умолчанию) или развёртывание с --apply."""
    tarball = Path(tarball_arg)
    if not tarball.is_file():
        print(f"Ошибка: архив не найден: {tarball}")
        return 1

    try:
        with tarfile.open(tarball, "r:*") as tf:
            members = tf.getmembers()
    except (tarfile.TarError, OSError, EOFError) as exc:
        print(f"Ошибка: не удалось прочитать архив {tarball}: {exc}")
        return 1

    problems = check_members(members)
    if problems:
        print(f"Ошибка: небезопасное содержимое архива {tarball}:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(f"Содержимое архива {tarball} ({len(members)} записей):")
    for member in members:
        kind = "dir " if member.isdir() else "file"
        size = f" ({member.size} байт)" if member.isreg() else ""
        print(f"  [{kind}] {member.name}{size}")

    overwritten = [
        member.name
        for member in members
        if member.isreg() and (DATA_DIR / member.name).exists()
    ]
    if overwritten:
        print(f"Существующие файлы в data/, которые будут ПЕРЕЗАПИСАНЫ ({len(overwritten)}):")
        for name in overwritten:
            print(f"  {name}")
    else:
        print("Существующие файлы в data/ перезаписаны не будут.")

    if not apply:
        print("DRY-RUN: архив не развёрнут. Запустите с --apply, чтобы восстановить.")
        return 0

    # Перед восстановлением автоматически бэкапим текущую data/, чтобы было
    # куда откатиться
    print("Создаю автобэкап текущей data/ перед восстановлением...")
    error = check_out_dir(out_dir)
    if error:
        print(f"Ошибка: {error}")
        return 1
    auto_backup = create_backup(out_dir, include_logs)
    if auto_backup is not None:
        print(f"Автобэкап создан: {auto_backup}")
    else:
        print("Автобэкап: в data/ нет файлов — бэкап не создавался.")

    try:
        with tarfile.open(tarball, "r:*") as tf:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            try:
                # Python 3.12+: встроенный безопасный фильтр
                tf.extractall(path=DATA_DIR, filter="data")
            except TypeError:
                # Python < 3.12 без фильтра 'data' — имена уже проверены
                # вручную в check_members()
                tf.extractall(path=DATA_DIR)
    except (tarfile.TarError, OSError, EOFError) as exc:
        print(f"Ошибка: не удалось развернуть архив {tarball}: {exc}")
        return 1

    print(f"Данные восстановлены из {tarball} в {DATA_DIR}/")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Бэкап и восстановление директории data/ (dry-run по умолчанию).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Примеры:
  python3 scripts/backup_data.py                       # dry-run: что войдёт в бэкап
  python3 scripts/backup_data.py --apply               # реальный бэкап в backups/
  python3 scripts/backup_data.py --apply --out /tmp/bk # бэкап в другую директорию
  python3 scripts/backup_data.py --include-logs --apply  # бэкап вместе с логами
  python3 scripts/backup_data.py --restore backups/backup_20260810_120000.tar.gz         # dry-run восстановления
  python3 scripts/backup_data.py --restore backups/backup_20260810_120000.tar.gz --apply # восстановление (с автобэкапом текущей data/)
""",
    )
    parser.add_argument(
        "--restore",
        metavar="TARBALL",
        help="восстановить data/ из указанного tarball вместо создания бэкапа",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"директория для tarball (по умолчанию: {DEFAULT_OUT_DIR}; не должна быть внутри data/)",
    )
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="не исключать логи (*.log) из бэкапа",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="реально записать (без флага — dry-run: только печать плана)",
    )
    return parser


def main() -> int:
    """Точка входа: разбирает аргументы и запускает нужный режим."""
    args = build_parser().parse_args()
    if args.restore:
        return do_restore(args.restore, args.out, args.include_logs, args.apply)
    return do_backup(args.out, args.include_logs, args.apply)


if __name__ == "__main__":
    sys.exit(main())

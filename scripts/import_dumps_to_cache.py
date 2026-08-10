#!/usr/bin/env python3
"""Импорт дампов справочников HH mobile API в оффлайн-кэш бота.

Копирует JSON-дампы справочников (areas, metro, dictionaries, suggests,
professional_roles и т.д.) из каталога с дампами в data/cache/dictionaries/,
считает sha256 и размер каждого файла и ведёт TTL-метаданные в
data/cache/dictionaries/_meta.json.

Режимы работы:
  * по умолчанию — DRY-RUN: скрипт только печатает план (copy / skipped: fresh /
    invalid + пути назначения) и ничего не записывает;
  * --apply — реальная запись (атомарное копирование: tmp-файл + os.replace).

Повторный импорт не копирует заново файл, который уже есть в кэше, чей sha256
совпадает и чей TTL ещё не истёк — для него печатается "skipped: fresh".
Флаг --force-refresh принудительно перезаписывает весь кэш.

Невалидные или пустые файлы пропускаются с предупреждением и не роняют
остальной импорт. Файлы кроме *.json (например, dumps_INDEX.md) игнорируются.

Только stdlib, Python 3.10+.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Все пути в коде бота относительные, поэтому переходим в корень репозитория
# и добавляем его в sys.path.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

# Каталог оффлайн-кэша справочников (относительно корня репозитория)
CACHE_DIR = Path("data") / "cache" / "dictionaries"
META_NAME = "_meta.json"

# Кандидаты для авто-поиска источника дампов: берётся первый существующий.
SOURCE_CANDIDATES = [
    REPO_ROOT / "scratchpad" / "dumps",
    Path(
        "/tmp/claude-1000/-home-user-clicker/"
        "17e4ae0c-68cb-4493-a781-b19299a7c758/scratchpad/dumps"
    ),
]

EPILOG = """\
примеры:
  python3 scripts/import_dumps_to_cache.py
      сухой прогон (по умолчанию): печатает план copy/skip/invalid без записи

  python3 scripts/import_dumps_to_cache.py --apply
      реальный импорт в data/cache/dictionaries/ (TTL по умолчанию 30 дней)

  python3 scripts/import_dumps_to_cache.py --apply --ttl-days 7 --force-refresh
      принудительно перезаписать весь кэш со сроком жизни 7 дней

  python3 scripts/import_dumps_to_cache.py --apply --source /path/to/dumps
      импорт из указанного каталога вместо авто-поиска
"""


def find_source(explicit: str | None) -> Path | None:
    """Определяет каталог с дампами: явный --source или авто-поиск.

    Возвращает None (с печатью ошибки), если источник не найден.
    """
    if explicit:
        source = Path(explicit)
        if not source.is_dir():
            print(f"[ОШИБКА] --source: каталог не найден: {source}")
            return None
        return source
    for candidate in SOURCE_CANDIDATES:
        if candidate.is_dir():
            return candidate
    print("[ОШИБКА] не найдена директория с дампами. Проверены кандидаты:")
    for candidate in SOURCE_CANDIDATES:
        print(f"  - {candidate}")
    print("Укажите каталог вручную через --source DIR.")
    return None


def inspect_dump(path: Path) -> tuple[dict | None, str | None]:
    """Проверяет дамп: размер > 0 и валидный JSON; считает sha256 и размер.

    Возвращает ({"sha256": ..., "size": ...}, None) при успехе
    либо (None, "причина") для пустого/невалидного файла.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"ошибка чтения: {exc}"
    if size <= 0:
        return None, "пустой файл (0 байт)"
    try:
        raw = path.read_bytes()
        json.loads(raw)  # валидация JSON до попадания в кэш
    except (OSError, ValueError) as exc:
        return None, f"невалидный JSON: {exc}"
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size": size}, None


def parse_iso(value) -> datetime | None:
    """Безопасно парсит ISO-8601 дату; naive-даты считает UTC."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_fresh(entry, sha256_hex: str, now: datetime) -> bool:
    """Свежая ли запись в _meta.json: sha256 совпадает и TTL не истёк."""
    if not isinstance(entry, dict):
        return False
    if entry.get("sha256") != sha256_hex:
        return False
    expires_at = parse_iso(entry.get("expires_at"))
    return expires_at is not None and now < expires_at


def atomic_copy(src: Path, dest: Path) -> None:
    """Атомарно копирует src в dest: tmp-файл в каталоге dest + os.replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(dest.parent), prefix=f".{dest.name}.", suffix=".tmp"
    )
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)  # mkstemp создаёт файл с правами 0600
        os.replace(tmp, dest)
    except BaseException:
        # при любой ошибке убираем за собой временный файл
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj) -> None:
    """Атомарно пишет JSON: tmp-файл в каталоге path + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def parse_args(argv=None) -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        prog="import_dumps_to_cache.py",
        description=(
            "Импорт дампов справочников HH mobile API в оффлайн-кэш бота: "
            "копирует scratchpad/dumps/*.json в data/cache/dictionaries/ "
            "и ведёт TTL-метаданные в _meta.json. По умолчанию — сухой прогон "
            "(только план, без записи)."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        metavar="DIR",
        default=None,
        help=(
            "каталог с дампами (default: авто-поиск — <repo>/scratchpad/dumps, "
            "затем /tmp/claude-1000/-home-user-clicker/"
            "17e4ae0c-68cb-4493-a781-b19299a7c758/scratchpad/dumps)"
        ),
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=30,
        metavar="N",
        help="срок жизни кэша в днях для TTL-метаданных (default: 30)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="принудительно перезаписать все файлы кэша, игнорируя свежесть",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="выполнить реальную запись (без флага — только сухой прогон)",
    )
    args = parser.parse_args(argv)
    if args.ttl_days < 0:
        parser.error("--ttl-days не может быть отрицательным")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    now = datetime.now(timezone.utc)

    source = find_source(args.source)
    if source is None:
        return 1

    dump_files = sorted(p for p in source.glob("*.json") if p.is_file())
    if not dump_files:
        print(f"[ОШИБКА] в каталоге {source} нет ни одного файла *.json")
        return 1

    print(f"[INFO] источник: {source}")
    print(f"[INFO] каталог кэша: {CACHE_DIR}")
    print(f"[INFO] файлов *.json в источнике: {len(dump_files)}")
    print(f"[INFO] TTL: {args.ttl_days} дн.")
    if args.force_refresh:
        print("[INFO] --force-refresh: кэш будет перезаписан полностью")
    if not args.apply:
        print("[DRY-RUN] запись отключена; добавьте --apply для реального импорта")

    # Читаем существующую мету, чтобы знать sha256/TTL уже импортированных файлов
    meta_path = CACHE_DIR / META_NAME
    meta: dict = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
            else:
                print("[WARN] _meta.json повреждён (ожидался объект) — будет создан заново")
        except (OSError, ValueError) as exc:
            print(f"[WARN] _meta.json повреждён ({exc}) — будет создан заново")

    # --- План: классифицируем каждый файл как copy / skipped: fresh / invalid ---
    to_copy: list[tuple[Path, dict]] = []
    skipped_count = 0
    invalid_count = 0
    copied_bytes = 0
    source_bytes = 0
    prefix = "" if args.apply else "[DRY-RUN] "

    for path in dump_files:
        info, reason = inspect_dump(path)
        if info is None:
            invalid_count += 1
            print(f"[WARN] {prefix}invalid: {path.name} — {reason}; пропуск")
            continue
        source_bytes += info["size"]
        entry = meta.get(path.name)
        if not args.force_refresh and is_fresh(entry, info["sha256"], now):
            skipped_count += 1
            expires_at = entry.get("expires_at", "?")
            print(
                f"{prefix}skipped: fresh: {path.name} "
                f"(sha256 совпадает, TTL до {expires_at})"
            )
            continue
        to_copy.append((path, info))
        copied_bytes += info["size"]
        print(
            f"{prefix}copy: {path.name} ({info['size']} байт, "
            f"sha256={info['sha256'][:12]}…) -> {CACHE_DIR / path.name}"
        )

    copied_count = len(to_copy)
    if not args.apply:
        print()
        print(
            f"[DRY-RUN] итог: copied={copied_count} (план), "
            f"skipped={skipped_count}, invalid={invalid_count}; "
            f"к копированию {copied_bytes} байт (в источнике {source_bytes} байт)"
        )
        return 0

    # --- Реальный импорт ---
    expires_iso = (now + timedelta(days=args.ttl_days)).isoformat(timespec="seconds")
    imported_iso = now.isoformat(timespec="seconds")
    errors = 0
    for path, info in to_copy:
        dest = CACHE_DIR / path.name
        try:
            atomic_copy(path, dest)
        except OSError as exc:
            errors += 1
            print(f"[ОШИБКА] не удалось скопировать {path.name}: {exc}")
            continue
        meta[path.name] = {
            "sha256": info["sha256"],
            "size": info["size"],
            "source": str(path),
            "imported_at": imported_iso,
            "expires_at": expires_iso,
        }
        print(f"copied: {path.name} -> {dest}")

    # Мета перезаписывается только если что-то действительно скопировано
    if copied_count - errors > 0:
        try:
            atomic_write_json(meta_path, meta)
            print(f"[OK] мета записана: {meta_path} (записей: {len(meta)})")
        except OSError as exc:
            errors += 1
            print(f"[ОШИБКА] не удалось записать {meta_path}: {exc}")

    print()
    print(
        f"[ИТОГ] copied={copied_count - errors}, skipped={skipped_count}, "
        f"invalid={invalid_count}, errors={errors}; "
        f"скопировано {copied_bytes} байт (в источнике {source_bytes} байт)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
#
# run_e2e_local.sh — локальный/CI прогон e2e-тестов бота.
#
# Что делает:
#   1. поднимает FastAPI-приложение бота через uvicorn на 127.0.0.1 в background;
#   2. ждёт готовности публичного эндпоинта GET /healthz (не требует авторизации);
#   3. запускает pytest tests/e2e/;
#   4. останавливает сервер (cleanup через trap) и возвращает exit code pytest.
#
# Примечание: --reload намеренно НЕ используется — для e2e важна стабильность.
#
set -euo pipefail

# ---------- Значения по умолчанию ----------
PORT="${E2E_PORT:-8000}"
STRICT=0
KEEP_SERVER=0
SERVER_PID=""
SERVER_LOG="${TMPDIR:-/tmp}/hh_e2e_server_$$.log"
USE_SETSID=0
PYTEST_EXIT=0

usage() {
    cat <<'USAGE'
Использование: scripts/run_e2e_local.sh [опции]

Поднимает бота (uvicorn) на 127.0.0.1, ждёт готовности GET /healthz,
запускает pytest tests/e2e/ и останавливает сервер.
Exit code скрипта = exit code pytest.

Опции:
  -h, --help        показать эту справку и выйти (сервер не запускается)
      --strict      отсутствие директории tests/e2e/ — ошибка (exit 1), а не skip
      --keep-server не убивать бота после тестов (для отладки); в конце
                    печатаются PID сервера и путь к логу

Env-переменные:
  APP_MODULE          ASGI-приложение для uvicorn. Авто-выбор: app.main:app,
                      если существует app/main.py, иначе app.routes:app
  E2E_PORT            порт сервера на 127.0.0.1 (по умолчанию 8000)
  UVICORN_EXTRA_ARGS  дополнительные аргументы uvicorn одной строкой, например
                      UVICORN_EXTRA_ARGS="--log-level debug" (--reload не нужен)
  PYTHON_BIN          интерпретатор Python (по умолчанию python, fallback python3)

Связанные настройки бота: HH_BOT_HOST/HH_BOT_PORT (по умолчанию 127.0.0.1:8000;
нелокальный bind разрешён только при HH_BOT_UNSAFE_EXPOSE=1).
USAGE
}

# ---------- Разбор аргументов ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --strict)
            STRICT=1
            shift
            ;;
        --keep-server)
            KEEP_SERVER=1
            shift
            ;;
        *)
            echo "Неизвестный аргумент: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# ---------- Корень репозитория ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# ---------- Инструменты ----------
if [[ -z "${PYTHON_BIN:-}" ]]; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        PYTHON_BIN="python3"
    fi
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ОШИБКА: интерпретатор '$PYTHON_BIN' не найден — задайте PYTHON_BIN" >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "ОШИБКА: curl не найден (нужен для проверки готовности /healthz)" >&2
    exit 1
fi

# ---------- Наличие e2e-тестов ----------
# Проверяем ДО старта сервера: при запуске бот поднимает фоновые потоки и ходит
# в сеть, поэтому гонять его без тестов нет смысла.
if [[ ! -d tests/e2e ]]; then
    if [[ "$STRICT" == "1" ]]; then
        echo "ОШИБКА: задан --strict, но директория tests/e2e/ не существует" >&2
        exit 1
    fi
    echo "SKIP: tests/e2e/ не существует"
    exit 0
fi

# ---------- Порт ----------
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "ОШИБКА: E2E_PORT='$PORT' должен быть числом" >&2
    exit 1
fi

port_is_free() {
    # Пытаемся занять порт: если bind не удался — порт уже используется.
    "$PYTHON_BIN" - "$1" <<'PYEOF'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PYEOF
}

if ! port_is_free "$PORT"; then
    echo "ОШИБКА: порт $PORT на 127.0.0.1 уже занят." >&2
    echo "Освободите его (например: ss -ltnp | grep :$PORT) или задайте другой E2E_PORT." >&2
    exit 1
fi

# ---------- Модуль приложения ----------
if [[ -z "${APP_MODULE:-}" ]]; then
    if [[ -f app/main.py ]]; then
        APP_MODULE="app.main:app"
    else
        APP_MODULE="app.routes:app"
    fi
fi

# Консистентность с настройками бота: приложение читает HH_BOT_HOST/HH_BOT_PORT.
export HH_BOT_HOST="${HH_BOT_HOST:-127.0.0.1}"
export HH_BOT_PORT="${HH_BOT_PORT:-$PORT}"

# ---------- Cleanup ----------
cleanup() {
    local pid="${SERVER_PID:-}"
    if [[ "$KEEP_SERVER" == "1" ]]; then
        # Режим отладки: сервер и его лог оставляем жить.
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "--keep-server: бот продолжает работать"
            echo "  PID сервера: $pid"
            echo "  Лог сервера: $SERVER_LOG"
        fi
        return 0
    fi
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Останавливаю сервер (PID $pid)..."
        if [[ "$USE_SETSID" == "1" ]]; then
            # setsid создал новую сессию: PGID == PID сервера, убиваем всю группу.
            kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
        else
            kill -TERM "$pid" 2>/dev/null || true
        fi
        # До 10 секунд на graceful shutdown.
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "Сервер не завершился за 10s — принудительный kill -9" >&2
            if [[ "$USE_SETSID" == "1" ]]; then
                kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
            else
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        wait "$pid" 2>/dev/null || true
    fi
    # Всегда удаляем временный лог (в режиме --keep-server выше был early return).
    rm -f "$SERVER_LOG"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------- Запуск сервера ----------
# Дополнительные аргументы uvicorn строкой -> массив (намеренный word splitting).
read -r -a EXTRA_ARGS <<< "${UVICORN_EXTRA_ARGS:-}"

UVICORN_CMD=("$PYTHON_BIN" -m uvicorn "$APP_MODULE" --host 127.0.0.1 --port "$PORT")
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    UVICORN_CMD+=("${EXTRA_ARGS[@]}")
fi

if command -v setsid >/dev/null 2>&1; then
    USE_SETSID=1
fi

echo "Запускаю сервер: ${UVICORN_CMD[*]}"
if [[ "$USE_SETSID" == "1" ]]; then
    setsid "${UVICORN_CMD[@]}" >"$SERVER_LOG" 2>&1 &
else
    "${UVICORN_CMD[@]}" >"$SERVER_LOG" 2>&1 &
fi
SERVER_PID=$!
echo "PID сервера: $SERVER_PID, лог: $SERVER_LOG"

# ---------- Ожидание готовности ----------
echo "Ожидаю readiness GET /healthz (до 30s)..."
READY=0
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
        READY=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "ОШИБКА: процесс сервера (PID $SERVER_PID) завершился до готовности" >&2
        echo "--- хвост лога сервера ($SERVER_LOG) ---" >&2
        tail -n 50 "$SERVER_LOG" >&2 || true
        exit 1
    fi
    sleep 0.5
done
if [[ "$READY" != "1" ]]; then
    echo "ОШИБКА: сервер не ответил на /healthz за 30s" >&2
    echo "--- хвост лога сервера ($SERVER_LOG) ---" >&2
    tail -n 50 "$SERVER_LOG" >&2 || true
    exit 1
fi
echo "Сервер готов."

# ---------- Тесты ----------
echo "Запускаю: $PYTHON_BIN -m pytest tests/e2e/ -v"
PYTEST_EXIT=0
"$PYTHON_BIN" -m pytest tests/e2e/ -v || PYTEST_EXIT=$?

# ---------- Итоговая сводка ----------
echo ""
echo "==================== E2E сводка ===================="
echo "Лог сервера:      $SERVER_LOG (удаляется при выходе; --keep-server сохраняет)"
echo "pytest exit code: $PYTEST_EXIT"
echo "===================================================="
exit "$PYTEST_EXIT"

"""Регрессия CRITICAL #4 (security-аудит): один mobile refresh_token,
разделённый несколькими resume-записями (import_mobile_tokens), не должен
создавать split-brain при конкурентном refresh.

До фикса `_get_refresh_lock(resume_hash)` создавал отдельный lock на каждый
resume_hash: потоки разных резюме одного пользователя одновременно предъявляли
HH общий refresh_token, второй получал invalid_grant (токен уже ротирован)
и семья токенов ветвилась.

Фикс: refresh_lock keyed по ВЛАДЕЛЬЦУ refresh_token (mobile_user_id, для
legacy mobile_otp без user_id — общий fallback-ключ family) + CAS: после
захвата lock'а запись перечитывается и в сеть никогда не уходит предъявленный
до lock'а (уже ротированный другим потоком) refresh_token.
"""
import json
import threading
import time
from types import SimpleNamespace

import pytest

import app.oauth as oauth_mod


class _Resp:
    """Минимальный fake HTTP-ответ для HH.post."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def family_store(tmp_data_dir, monkeypatch):
    """Изолированный token-store: файл в tmp dir, пустой in-memory dict.

    tmp_data_dir (conftest) chdir'ит в tmp, чтобы служебные файлы config/data
    не писались в реальный data/ проекта.
    """
    monkeypatch.setattr(oauth_mod, "_OAUTH_FILE", tmp_data_dir / "oauth_tokens.json")
    original = oauth_mod._oauth_tokens
    oauth_mod._oauth_tokens = {}
    try:
        yield tmp_data_dir
    finally:
        oauth_mod._oauth_tokens = original


def _install_fake_hh(monkeypatch):
    """Подменяет сетевой слой HH в app.oauth.

    Контракт как у реального HH: ПЕРВОЕ предъявление refresh_token R1 ротирует
    его и возвращает новую пару (R2/access2); ЛЮБОЕ повторное предъявление R1
    → 400 invalid_grant (токен уже ротирован первым запросом).

    Возвращает список предъявленных сети refresh_token'ов (в порядке вызовов).
    """
    calls = []
    calls_lock = threading.Lock()

    def fake_post(url, **kwargs):
        data = kwargs.get("data") or {}
        assert data.get("grant_type") == "refresh_token", f"неожиданный вызов {url}: {data}"
        rt = data.get("refresh_token")
        with calls_lock:
            calls.append(rt)
            is_first_r1 = rt == "R1" and calls.count("R1") == 1
        if rt == "R1" and is_first_r1:
            return _Resp(200, {"access_token": "access2", "refresh_token": "R2", "expires_in": 1209599})
        if rt == "R2":
            # сюда не должно дойти при корректной сериализации, но поведение
            # определено на случай законного повторного refresh.
            return _Resp(200, {"access_token": "access3", "refresh_token": "R3", "expires_in": 1209599})
        return _Resp(400, {"error": "invalid_grant"})

    def fake_get(url, **kwargs):
        # Если хоть один поток свалился в cookie authorize-flow (ложный auth
        # failure), тест упадёт здесь, а не тихой пустой строкой.
        raise AssertionError("authorize-ветка не должна вызываться при успешном refresh")

    monkeypatch.setattr(oauth_mod, "HH", SimpleNamespace(post=fake_post, get=fake_get))
    return calls


def _seed_expired_family(me=None, expires_shift=-100):
    """Импортирует ОДИН mobile refresh_token R1 под два резюме (как в проде)."""
    now = int(time.time())
    return oauth_mod.import_mobile_tokens(
        {
            "access_token": "access1",
            "refresh_token": "R1",
            "expires_at": now + expires_shift,  # просрочен → lazy refresh обязан сработать
            "expires_in": 0,
        },
        [{"id": "r1"}, {"id": "r2"}],
        me,
    )


def _run_threads(worker, n_threads):
    """Запустить `worker(i)` в n_threads потоках, синхронизировав старт barrier'ом."""
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads
    errors = [None] * n_threads

    def _wrap(i):
        try:
            barrier.wait(timeout=10)
            results[i] = worker(i)
        except Exception as exc:  # noqa: BLE001 — фиксируем любой сбой потока
            errors[i] = exc

    threads = [threading.Thread(target=_wrap, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "поток завис (deadlock?)"
    return results, errors


def test_refresh_lock_key_identity_semantics():
    """Ключ refresh_lock'а — владелец refresh_token, а не resume."""
    mob = {"source": "mobile_otp", "mobile_user_id": "u1"}
    # Один владелец → один lock независимо от resume.
    assert oauth_mod._refresh_lock_key(mob, "r1") == oauth_mod._refresh_lock_key(mob, "r2")
    # Разные владельцы → разные lock'и.
    mob2 = {"source": "mobile_otp", "mobile_user_id": "u2"}
    assert oauth_mod._refresh_lock_key(mob2, "r1") != oauth_mod._refresh_lock_key(mob, "r1")
    # mobile_otp без user_id (legacy) → общий fallback-ключ всей family.
    legacy = {"source": "mobile_otp"}
    assert (
        oauth_mod._refresh_lock_key(legacy, "r1")
        == oauth_mod._refresh_lock_key(legacy, "r2")
        == oauth_mod._MOBILE_OTP_FAMILY_LOCK_KEY
    )
    assert oauth_mod._refresh_lock_key(legacy, "r1") != oauth_mod._refresh_lock_key(mob, "r1")
    # Браузерные токены не разделяются между резюме → per-resume ключ.
    browser = {"access_token": "x"}
    assert oauth_mod._refresh_lock_key(browser, "r1") != oauth_mod._refresh_lock_key(browser, "r2")
    assert oauth_mod._refresh_lock_key(browser, "r1") != oauth_mod._refresh_lock_key(legacy, "r1")
    # Пустая запись (токена нет, впереди authorize-flow) — тоже per-resume.
    assert oauth_mod._refresh_lock_key({}, "r1") == oauth_mod._refresh_lock_key(None, "r1")
    # _get_refresh_lock стабилен: один объект на один ключ.
    assert oauth_mod._get_refresh_lock("user:u1") is oauth_mod._get_refresh_lock("user:u1")


def test_concurrent_lazy_refresh_no_split_brain(family_store, monkeypatch):
    """10 потоков одновременно lazy-refresh'ят два резюме с общим R1.

    (a) R1 уходит в сеть ровно один раз; (b) все записи family сходятся к R2;
    (c) ни один поток не получает необработанный invalid_grant / ложный auth
    failure; (d) состояние на диске консистентно с памятью.
    """
    calls = _install_fake_hh(monkeypatch)

    assert _seed_expired_family(me={"id": "u1"}) == 2
    # import_mobile_tokens сохранил владельца family в каждую запись.
    assert oauth_mod._oauth_tokens["r1"]["mobile_user_id"] == "u1"
    assert oauth_mod._oauth_tokens["r2"]["mobile_user_id"] == "u1"
    # Одна token family → один общий refresh_lock на все резюме владельца.
    assert (
        oauth_mod._refresh_lock_key(oauth_mod._oauth_tokens["r1"], "r1")
        == oauth_mod._refresh_lock_key(oauth_mod._oauth_tokens["r2"], "r2")
    )

    def worker(i):
        # Каждый поток — отдельный account (уникальный hhtoken → composite-ключ),
        # резюме чередуются: половина давит r1, половина r2.
        acc = {
            "resume_hash": "r1" if i % 2 == 0 else "r2",
            "cookies": {"hhtoken": f"ht-{i}"},
        }
        return oauth_mod._obtain_oauth_token(acc)

    results, errors = _run_threads(worker, 10)

    # (c) ни один поток не упал и не получил ложный auth failure («» от authorize).
    assert errors == [None] * 10, errors
    assert all(r == "access2" for r in results), results

    # (a) старый R1 предъявлен сети РОВНО ОДИН раз — и refresh-вызов был один.
    assert calls == ["R1"], calls

    # (b) все записи family (plain + мигрированные composite) сошлись к одному
    # новому refresh_token R2 — одна token family, split-brain нет.
    tokens = oauth_mod._oauth_tokens
    assert tokens
    assert {"r1", "r2"} <= set(tokens)
    for k, v in tokens.items():
        assert v.get("refresh_token") == "R2", f"запись {k} осталась с {v.get('refresh_token')!r}"
        assert v.get("access_token") == "access2", f"запись {k}"
        assert v.get("mobile_user_id") == "u1", f"запись {k} потеряла владельца family"

    # (d) состояние на диске консистентно с памятью. Явный save после join:
    # в ходе гонки composite-ключи, мигрированные ПОСЛЕ последнего save
    # победившего потока, есть в памяти, но ещё не на диске (они легитимно
    # ремигрируют с plain-ключей при старте) — фиксируем итоговое состояние.
    assert oauth_mod._save_oauth_tokens() is True
    saved = json.loads((family_store / "oauth_tokens.json").read_text(encoding="utf-8"))
    assert set(saved) == set(tokens)
    for k, v in saved.items():
        assert v.get("refresh_token") == "R2", f"на диске {k} остался с {v.get('refresh_token')!r}"
        assert v.get("access_token") == "access2"


def test_concurrent_lazy_refresh_legacy_mobile_records(family_store, monkeypatch):
    """Legacy-импорт без me (записи без mobile_user_id) тоже сериализуется:
    все mobile_otp-записи без user_id делят один общий fallback-lock."""
    calls = _install_fake_hh(monkeypatch)

    assert _seed_expired_family(me=None) == 2
    assert "mobile_user_id" not in oauth_mod._oauth_tokens["r1"]
    assert (
        oauth_mod._refresh_lock_key(oauth_mod._oauth_tokens["r1"], "r1")
        == oauth_mod._refresh_lock_key(oauth_mod._oauth_tokens["r2"], "r2")
        == oauth_mod._MOBILE_OTP_FAMILY_LOCK_KEY
    )

    def worker(i):
        acc = {
            "resume_hash": "r1" if i % 2 == 0 else "r2",
            "cookies": {"hhtoken": f"ht-{i}"},
        }
        return oauth_mod._obtain_oauth_token(acc)

    results, errors = _run_threads(worker, 10)

    assert errors == [None] * 10, errors
    assert all(r == "access2" for r in results), results
    assert calls == ["R1"], calls
    tokens = oauth_mod._oauth_tokens
    assert tokens
    for k, v in tokens.items():
        assert v.get("refresh_token") == "R2", f"запись {k} осталась с {v.get('refresh_token')!r}"


def test_concurrent_proactive_refresh_single_network_call(family_store, monkeypatch):
    """Гонка двух одновременных proactive-циклов: ровно один сетевой refresh.

    seen_refresh — локальная set одного вызова, поэтому межпоточную гонку
    закрывает только family-lock + CAS-перечитывание под lock'ом.
    """
    calls = _install_fake_hh(monkeypatch)
    assert _seed_expired_family(me={"id": "u1"}) == 2

    results, errors = _run_threads(
        lambda i: oauth_mod.refresh_oauth_tokens_proactive(min_ttl_hours=48), 2
    )

    assert errors == [None, None], errors
    stats = results
    # Ровно один refresh на всю family, ни одного ложного invalid_grant.
    assert sum(s["refreshed"] for s in stats) == 1, stats
    assert sum(s["failed"] for s in stats) == 0, stats
    assert calls == ["R1"], calls
    # Обе записи сошлись к R2.
    tokens = oauth_mod._oauth_tokens
    for k, v in tokens.items():
        assert v.get("refresh_token") == "R2", f"запись {k} осталась с {v.get('refresh_token')!r}"
        assert v.get("mobile_user_id") == "u1"

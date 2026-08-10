"""Mobile-версия поднятия резюме в поиске (touch) через api.hh.ru (Phase 3).

POST https://api.hh.ru/resumes/{resume_id}/publish?with_professional_roles=true
— контракт APK (zy/InterfaceC10767c.java:
@u9.o("/resumes/{resume_id}/publish?with_professional_roles=true")).
Тела нет; 2xx = резюме поднято. Существующий app/oauth.py::_oauth_touch_resume
ходит в тот же /publish, но без with_professional_roles и через другой
транспорт (curl_cffi HH) — здесь mobile-версия через общий транспорт
app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access).

Fallback-политика: статусы 0 (сеть) / 401 / 403 / 5xx НЕ глотаются —
MobileAPIError перекидывается наверх. Прочие 4xx (кроме 429), например 400 —
publish может требовать HHPro или заполненные поля резюме, — поднимают
NotImplementedError: FallbackHHClient ловит NotImplementedError и прозрачно
повторяет операцию через web hh_apply.touch_resume (механизм Phase 2).
"""

from urllib.parse import quote

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def touch_resume(acc: dict, resume_id: str) -> tuple:
    """Поднять резюме в поиске через mobile-контракт api.hh.ru.

    acc — словарь аккаунта (токен добывает mobile_request сам);
    resume_id — hash резюме (в URL-path кодируется quote(..., safe=""),
    как в app/oauth.py::_oauth_touch_resume).

    Возвращает (success: bool, message: str):
    - 2xx → (True, "Резюме поднято (mobile)");
    - 429 → (False, "Слишком часто (429)") — паритет с web
      hh_apply.touch_resume;
    - пустой resume_id → (False, "Нет resume_hash") без HTTP-вызова.

    На fallback-статусах (0 сеть / 401 / 403 / 5xx) перекидывает
    MobileAPIError наверх; на прочих 4xx поднимает NotImplementedError —
    FallbackHHClient ловит его и прозрачно повторяет поднятие через web
    hh_apply.touch_resume (механизм Phase 2).
    """
    if not resume_id:
        return False, "Нет resume_hash"
    try:
        mobile_request(acc, "POST",
                       f"/resumes/{quote(resume_id, safe='')}/publish",
                       params={"with_professional_roles": "true"})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # Не глотим: fallback-обёртка повторит вызов через web-flow.
            raise
        if e.status_code == 429:
            log_debug(f"mobile touch_resume {resume_id}: 429 cooldown")
            return False, "Слишком часто (429)"
        # Прочие 4xx (например 400): publish может требовать HHPro или
        # заполненные поля — web-flow умеет это лучше, падаем в fallback.
        raise NotImplementedError(
            f"mobile touch_resume: HTTP {e.status_code} — fallback на web-flow"
        ) from e
    log_debug(f"mobile touch_resume {resume_id}: резюме поднято")
    return True, "Резюме поднято (mobile)"

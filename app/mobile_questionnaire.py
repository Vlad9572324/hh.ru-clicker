"""Mobile-версия заполнения анкеты при отклике (Phase 3).

Решение Phase 3 (факт из разбора APK ru.hh.android v26.28.1, декомпилят
/tmp/hh-apk/src2/sources): нативного Retrofit-endpoint'а для анкет/опросов
в mobile-приложении НЕТ (grep по @u9-аннотациям с
test/questionnaire/survey/answer нашёл только /survey_user_targeting/
banner_info и /contests/* — не то). При error_type=test_required приложение
показывает alert и открывает WEB-страницу анкеты (applicant/vacancy_response)
в webview. То есть официальное mobile-приложение заполняет анкеты через
web-flow — повторяем эту семантику: делегируем в
hh_apply.fill_and_submit_questionnaire. Cookies hh.ru в acc те же, что
использует web-flow; FallbackHHClient для web-аккаунтов и так ходит в эту
же функцию, так что поведение mobile и web совпадает.
"""

from app import hh_apply


async def fill_questionnaire(acc: dict, vid: str,
                             vacancy_title: str = "", company: str = "") -> tuple:
    """Заполнить анкету при отклике: делегирование в web-flow.

    Нативного mobile-endpoint'а для анкет нет (см. docstring модуля:
    официальное приложение открывает web-анкету в webview), поэтому
    вызываем hh_apply.fill_and_submit_questionnaire как есть —
    аргументы пробрасываются позиционно, результат возвращается
    без преобразования.

    Возвращает (result, info) web-функции:
    result = sent | limit | test | error | auth_error.
    """
    return await hh_apply.fill_and_submit_questionnaire(
        acc, vid, vacancy_title, company)

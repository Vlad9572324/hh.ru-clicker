import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
import time
import random
from datetime import datetime, timedelta
from glom import glom
import json
import urllib.parse

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich import box
from rich.style import Style
from rich.columns import Columns

console = Console()

# ============================================================
# АККАУНТЫ
# ============================================================

accounts = [
    {
        "name": "Имя Фамилия (оператор)",  # Название для логов

        "resume_hash": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # Hash из URL резюме

        "letter": (
            "Здравствуйте!\n\n"
            "Я выражаю искренний интерес к возможности присоединиться к вашей компании. "
            "Ознакомившись с деятельностью вашей организации, уверена, что мой опыт и навыки могут быть полезны вашей команде.\n\n"
            "Я всегда стремлюсь к профессиональному развитию и готова осваивать новое. "
            "Уверена, что ваша компания предоставляет отличные возможности для роста, обучения и самореализации. "
            "Буду рада стать частью вашей команды и внести свой вклад в достижение общих целей.\n\n"
            "С уважением,\n"
            "Имя Фамилия\n"
            "t.me: @username\n"
            "📞 8XXXXXXXXXX\n"
            "📧 email@example.com"
        ),

        "urls": [
            # Рекомендации (замените resume= на ваш hash)
            "https://hh.ru/search/vacancy?excluded_text=&items_on_page=20&ored_clusters=true&resume=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx&order_by=publication_time",
            # QA
            "https://hh.ru/search/vacancy?text=QA&area=1&experience=doesNotMatter&order_by=relevance&items_on_page=20",
            # Тестировщик
            "https://hh.ru/search/vacancy?text=%D1%82%D0%B5%D1%81%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D1%89%D0%B8%D0%BA&area=1&experience=doesNotMatter&items_on_page=20",
            # Technical Writer
            "https://hh.ru/search/vacancy?text=Technical+Writer&area=1&items_on_page=20&order_by=publication_time",
            #...

        ],

        "cookies": {
            "hhtoken": "XXXXXXXXXXXXXXXXXXXXXXXX",  # Из браузера
            "hhul": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
            "crypted_id": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
            "_xsrf": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        },

        # Служебные поля — НЕ ИЗМЕНЯТЬ
        "limit_exceeded": False,
        "limit_reset_time": None,
        "stats": {"sent": 0, "skipped": 0, "errors": 0}
    },

    # Второй аккаунт (скопируйте блок выше и заполните)
    # {
    #     "name": "Второй аккаунт",
    #     ...
    # },
]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_headers(xsrf: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://hh.ru/vacancy/118797963?from=applicant_recommended&hhtmFrom=main",
        "Origin": "https://hh.ru",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "X-Requested-With": "XMLHttpRequest",
        "X-HHTMFrom": "main",
        "X-HHTMSource": "vacancy",
        "X-XsrfToken": xsrf
    }


def get_active_account():
    now = datetime.now()
    for account in accounts:
        if account["limit_exceeded"] and account["limit_reset_time"]:
            if now >= account["limit_reset_time"]:
                account["limit_exceeded"] = False
                account["limit_reset_time"] = None
                console.print(f"[green]✅ Лимит аккаунта '{account['name']}' сброшен![/green]")
        if not account["limit_exceeded"]:
            return account
    return None


def get_next_reset_time():
    reset_times = [acc["limit_reset_time"] for acc in accounts if acc["limit_reset_time"]]
    if reset_times:
        return min(reset_times)
    now = datetime.now()
    return now.replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)


def mark_limit_exceeded(account: dict):
    account["limit_exceeded"] = True
    now = datetime.now()
    account["limit_reset_time"] = now.replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)

    console.print(Panel(
        f"[bold red]ЛИМИТ ИСЧЕРПАН[/bold red]\n\n"
        f"👤 Аккаунт: [yellow]{account['name']}[/yellow]\n"
        f"⏰ Сброс: [cyan]{account['limit_reset_time'].strftime('%d.%m.%Y %H:%M')}[/cyan]",
        title="🚫 Внимание",
        border_style="red"
    ))


def extract_search_query(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    if 'text' in params:
        return urllib.parse.unquote(params['text'][0])
    elif 'resume' in params:
        return "📋 Рекомендации"
    return "Поиск"


def print_welcome():
    """Выводит приветственный баннер."""
    console.print()
    console.print(Panel(
        "[bold cyan]🚀 АВТОМАТИЗАЦИЯ ОТКЛИКОВ HH.RU[/bold cyan]\n"
        "[dim]Multi-Account Version with Rich UI[/dim]",
        box=box.DOUBLE,
        border_style="cyan"
    ))

    # Таблица аккаунтов
    table = Table(title="👥 Аккаунты", box=box.ROUNDED, border_style="blue")
    table.add_column("Имя", style="cyan")
    table.add_column("Ссылок", justify="center", style="green")
    table.add_column("Статус", justify="center")

    for acc in accounts:
        status = "[red]🔴 Лимит[/red]" if acc["limit_exceeded"] else "[green]🟢 Активен[/green]"
        table.add_row(acc["name"], str(len(acc["urls"])), status)

    console.print(table)
    console.print()


def print_summary():
    """Выводит итоговую статистику."""
    now = datetime.now()
    next_reset = get_next_reset_time()
    next_account = get_active_account()

    # Основная таблица статистики
    table = Table(title="📊 Итоговая статистика", box=box.ROUNDED, border_style="cyan")
    table.add_column("Аккаунт", style="cyan")
    table.add_column("Статус", justify="center")
    table.add_column("Сброс лимита", justify="center")
    table.add_column("✉️ Отправлено", justify="center", style="green")
    table.add_column("⏩ Пропущено", justify="center", style="yellow")
    table.add_column("❌ Ошибки", justify="center", style="red")

    total_sent = 0
    total_skipped = 0
    total_errors = 0

    for acc in accounts:
        status = "[red]🔴 ЛИМИТ[/red]" if acc["limit_exceeded"] else "[green]🟢 АКТИВЕН[/green]"
        reset_str = acc["limit_reset_time"].strftime("%d.%m %H:%M") if acc["limit_reset_time"] else "—"
        stats = acc.get("stats", {"sent": 0, "skipped": 0, "errors": 0})

        total_sent += stats["sent"]
        total_skipped += stats["skipped"]
        total_errors += stats["errors"]

        table.add_row(
            acc["name"],
            status,
            reset_str,
            str(stats["sent"]),
            str(stats["skipped"]),
            str(stats["errors"])
        )

    # Итоговая строка
    table.add_row(
        "[bold]ИТОГО[/bold]",
        "",
        "",
        f"[bold green]{total_sent}[/bold green]",
        f"[bold yellow]{total_skipped}[/bold yellow]",
        f"[bold red]{total_errors}[/bold red]"
    )

    console.print()
    console.print(table)

    # Детальная информация о следующих действиях
    console.print()

    if next_account:
        # Есть активный аккаунт
        next_cycle = now + vacancy_response_interval
        time_to_next = vacancy_response_interval.total_seconds() / 60

        info_panel = Panel(
            f"[bold green]🟢 СИСТЕМА АКТИВНА[/bold green]\n\n"
            f"[cyan]🔜 Следующий аккаунт:[/cyan] {next_account['name']}\n"
            f"[cyan]🔄 Следующий цикл:[/cyan] {next_cycle.strftime('%d.%m.%Y %H:%M')} (через {time_to_next:.0f} мин)\n"
            f"[cyan]📊 Активных аккаунтов:[/cyan] {sum(1 for a in accounts if not a['limit_exceeded'])}/{len(accounts)}",
            title="📍 Статус системы",
            border_style="green"
        )
    else:
        # Все аккаунты исчерпали лимит
        wait_seconds = (next_reset - now).total_seconds()
        wait_hours = wait_seconds / 3600
        wait_minutes = (wait_seconds % 3600) / 60

        # Список аккаунтов с временем сброса
        accounts_info = ""
        for acc in accounts:
            if acc["limit_reset_time"]:
                time_left = (acc["limit_reset_time"] - now).total_seconds()
                hours_left = int(time_left // 3600)
                mins_left = int((time_left % 3600) // 60)
                accounts_info += f"   • {acc['name']}: сброс в {acc['limit_reset_time'].strftime('%H:%M')} (через {hours_left}ч {mins_left}мин)\n"

        info_panel = Panel(
            f"[bold red]😴 ВСЕ АККАУНТЫ ИСЧЕРПАЛИ ЛИМИТ[/bold red]\n\n"
            f"[yellow]Аккаунты и время сброса:[/yellow]\n{accounts_info}\n"
            f"[cyan]⏳ Ближайший сброс:[/cyan] {next_reset.strftime('%d.%m.%Y %H:%M')}\n"
            f"[cyan]⏱️ Осталось ждать:[/cyan] {int(wait_hours)}ч {int(wait_minutes)}мин\n\n"
            f"[dim]💤 Система проверяет статус каждый час...[/dim]",
            title="📍 Статус системы",
            border_style="red"
        )

    console.print(info_panel)
    console.print()


def print_vacancy_result(info: dict, success: bool):
    """Выводит результат отклика на вакансию."""
    if success:
        title = info.get('📌 Название', 'N/A')
        company = info.get('🏢 Компания', 'N/A')
        salary_from = info.get('💰 Зарплата от')
        salary_to = info.get('💰 Зарплата до')
        currency = info.get('💱 Валюта', '')

        salary_str = ""
        if salary_from or salary_to:
            salary_str = f"\n💰 {salary_from or '?'} - {salary_to or '?'} {currency}"

        console.print(f"   [green]✅ {title}[/green] @ [cyan]{company}[/cyan]{salary_str}")


# ============================================================
# ОСНОВНЫЕ ФУНКЦИИ
# ============================================================

def touch_resume(resume_hash: str, headers: dict, cookies: dict, account_name: str) -> int:
    import requests
    url_touch = "https://hh.ru/applicant/resumes/touch"
    touch_files = {"resume": (None, resume_hash), "undirectable": (None, "true")}
    response = requests.post(url_touch, headers=headers, cookies=cookies, files=touch_files)

    status_style = "green" if response.status_code == 200 else "red"
    console.print(f"   [{status_style}][{account_name}] Поднятие резюме — {response.status_code}[/{status_style}]")
    return response.status_code


def send_vacancy_response(resume_hash: str, vacancy_id: str, my_letter: str,
                          headers: dict, cookies: dict) -> tuple:
    import requests
    url_response = "https://hh.ru/applicant/vacancy_response/popup"

    files = {
        "resume_hash": (None, resume_hash),
        "vacancy_id": (None, vacancy_id),
        "letterRequired": (None, "true"),
        "letter": (None, my_letter),
        "lux": (None, "true"),
        "ignore_postponed": (None, "true"),
        "mark_applicant_visible_in_vacancy_country": (None, "false")
    }

    response = requests.post(url_response, headers=headers, cookies=cookies, files=files)

    if response.status_code != 200:
        return response.status_code, response.text, {}

    try:
        parsed = response.json()
    except json.JSONDecodeError:
        return response.status_code, response.text, {}

    info = {
        "📌 Название": glom(parsed, "responseStatus.shortVacancy.name", default=None),
        "🏢 Компания": glom(parsed, "responseStatus.shortVacancy.company.name", default=None),
        "💰 Зарплата от": glom(parsed, "responseStatus.shortVacancy.compensation.from", default=None),
        "💰 Зарплата до": glom(parsed, "responseStatus.shortVacancy.compensation.to", default=None),
        "💱 Валюта": glom(parsed, "responseStatus.shortVacancy.compensation.currencyCode", default=None),
    }
    info = {k: v for k, v in info.items() if v not in [None, "", []]}

    return response.status_code, response.text, info


def parse_vacancy_ids(html: str) -> set:
    soup = BeautifulSoup(html, "html.parser")
    vacancy_links = soup.find_all("a", href=re.compile(r"/vacancy/\d+"))
    vacancy_ids = set()
    for link in vacancy_links:
        match = re.search(r"/vacancy/(\d+)", link["href"])
        if match:
            vacancy_ids.add(match.group(1))
    return vacancy_ids


async def fetch_page(session: aiohttp.ClientSession, url: str,
                     semaphore: asyncio.Semaphore, delay: float = 0.2, retries: int = 3) -> str:
    async with semaphore:
        for attempt in range(retries + 1):
            try:
                await asyncio.sleep(delay + attempt * 0.3)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    html = await response.text()
                    if "vacancy" in html or len(html) > 5000:
                        return html
                    elif attempt < retries:
                        await asyncio.sleep(1.0)
                        continue
                    return html
            except (asyncio.TimeoutError, aiohttp.ClientPayloadError, aiohttp.ClientResponseError, Exception):
                if attempt < retries:
                    await asyncio.sleep(1.0)
                    continue
                return ""
        return ""


async def fetch_vacancies_from_url(session: aiohttp.ClientSession, base_url: str, pages: int,
                                   semaphore: asyncio.Semaphore, progress, task_id) -> tuple:
    """Загружает вакансии с одного URL и возвращает статистику."""
    separator = "&" if "?" in base_url else "?"
    page_urls = [f"{base_url}{separator}page={page}" for page in range(pages)]

    tasks = [fetch_page(session, url, semaphore) for url in page_urls]
    html_pages = await asyncio.gather(*tasks)

    all_ids = set()
    page_stats = []

    for page_num, html in enumerate(html_pages):
        if html:
            ids = parse_vacancy_ids(html)
            all_ids.update(ids)
            page_stats.append({"page": page_num, "count": len(ids), "success": len(ids) > 0})
        else:
            page_stats.append({"page": page_num, "count": 0, "success": False, "error": True})

        progress.advance(task_id)

    return all_ids, page_stats


async def collect_vacancies_async(urls: list, pages_per_url: int, headers: dict,
                                  cookies: dict, max_concurrent: int = 5) -> tuple:
    """Собирает вакансии со всех URL с прогресс-баром."""
    all_vacancies = set()
    all_stats = []
    semaphore = asyncio.Semaphore(max_concurrent)

    total_pages = len(urls) * pages_per_url

    with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console
    ) as progress:
        overall_task = progress.add_task("[cyan]Загрузка страниц...", total=total_pages)

        async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
            for url_idx, url in enumerate(urls, 1):
                query_name = extract_search_query(url)
                progress.update(overall_task, description=f"[cyan]{url_idx}/{len(urls)} {query_name}")

                vacancies, page_stats = await fetch_vacancies_from_url(
                    session, url, pages_per_url, semaphore, progress, overall_task
                )
                all_vacancies.update(vacancies)
                all_stats.append({
                    "url": url,
                    "query": query_name,
                    "vacancies": len(vacancies),
                    "pages": page_stats
                })

    return all_vacancies, all_stats


def print_collection_results(stats: list, total_vacancies: int, elapsed: float):
    """Выводит красивую таблицу результатов сбора вакансий."""

    # Таблица по каждому поисковому запросу
    table = Table(title="🔍 Результаты поиска", box=box.ROUNDED, border_style="blue")
    table.add_column("#", style="dim", width=3)
    table.add_column("Запрос", style="cyan", max_width=30)
    table.add_column("Страницы", justify="center")
    table.add_column("Вакансий", justify="center", style="green")

    for idx, stat in enumerate(stats, 1):
        # Формируем строку со статусом страниц
        pages_str = ""
        for p in stat["pages"]:
            if p.get("error"):
                pages_str += "[red]✗[/red]"
            elif p["count"] > 0:
                pages_str += "[green]✓[/green]"
            else:
                pages_str += "[yellow]○[/yellow]"

        table.add_row(
            str(idx),
            stat["query"][:30],
            pages_str,
            str(stat["vacancies"])
        )

    console.print(table)

    # Итоговая панель
    console.print(Panel(
        f"[bold green]🚩 Всего уникальных вакансий: {total_vacancies}[/bold green]\n"
        f"[dim]⏱️ Время сбора: {elapsed:.1f} сек | 🔀 Вакансии перемешаны[/dim]",
        border_style="green"
    ))


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

pages_per_url = 5
max_concurrent_requests = 5

resume_lift_interval = timedelta(hours=4, minutes=10)
vacancy_response_interval = timedelta(hours=2)

last_resume_lift = datetime.min
last_response_attempt = datetime.min

# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

if __name__ == "__main__":
    print_welcome()

    # Таблица конфигурации
    config_table = Table(box=box.SIMPLE, show_header=False)
    config_table.add_column("Param", style="dim")
    config_table.add_column("Value", style="cyan")
    config_table.add_row("📄 Страниц на ссылку:", str(pages_per_url))
    config_table.add_row("⏰ Интервал откликов:", str(vacancy_response_interval))
    config_table.add_row("⏰ Поднятие резюме:", str(resume_lift_interval))
    console.print(config_table)
    console.print()

    while True:
        now = datetime.now()
        account = get_active_account()

        if account is None:
            next_reset = get_next_reset_time()
            wait_seconds = (next_reset - now).total_seconds()

            if wait_seconds > 0:
                print_summary()
                console.print(f"[dim]💤 Ожидание... (проверка каждый час)[/dim]")
                time.sleep(min(wait_seconds, 3600))
                continue

        headers = get_headers(account["cookies"]["_xsrf"])
        cookies = account["cookies"]

        # Поднятие резюме
        if now - last_resume_lift >= resume_lift_interval:
            console.print(Panel(
                f"[bold]🕓 {now.strftime('%H:%M:%S')} — ПОДНЯТИЕ РЕЗЮМЕ[/bold]",
                border_style="yellow"
            ))
            for acc in accounts:
                h = get_headers(acc["cookies"]["_xsrf"])
                touch_resume(acc["resume_hash"], h, acc["cookies"], acc["name"])
            last_resume_lift = now
            console.print()

        # Отклики
        if now - last_response_attempt >= vacancy_response_interval:
            console.print(Panel(
                f"[bold cyan]🕑 {now.strftime('%H:%M:%S')} — НАЧАЛО ЦИКЛА ОТКЛИКОВ[/bold cyan]",
                border_style="cyan",
                box=box.DOUBLE
            ))

            # Сброс статистики
            for acc in accounts:
                acc["stats"] = {"sent": 0, "skipped": 0, "errors": 0}

            # Обработка аккаунтов
            for acc_idx, account in enumerate(accounts, 1):
                if account["limit_exceeded"]:
                    console.print(f"[yellow]⏩ [{account['name']}] Лимит исчерпан — пропускаю[/yellow]")
                    continue

                console.print()
                console.print(Panel(
                    f"[bold]👤 АККАУНТ {acc_idx}/{len(accounts)}[/bold]\n"
                    f"[cyan]{account['name']}[/cyan]\n"
                    f"[dim]🔗 {len(account['urls'])} ссылок для поиска[/dim]",
                    border_style="blue"
                ))

                headers = get_headers(account["cookies"]["_xsrf"])
                cookies = account["cookies"]

                # Сбор вакансий
                console.print("\n[bold]📥 СБОР ВАКАНСИЙ[/bold]")
                start_time = time.time()

                all_vacancies, collection_stats = asyncio.run(
                    collect_vacancies_async(
                        account["urls"], pages_per_url, headers, cookies, max_concurrent_requests
                    )
                )
                elapsed = time.time() - start_time

                all_vacancies = list(all_vacancies)
                random.shuffle(all_vacancies)

                print_collection_results(collection_stats, len(all_vacancies), elapsed)

                # Отправка откликов
                console.print("\n[bold]📤 ОТПРАВКА ОТКЛИКОВ[/bold]")

                with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(bar_width=40),
                        TaskProgressColumn(),
                        TimeElapsedColumn(),
                        console=console
                ) as progress:

                    task = progress.add_task(
                        f"[cyan]Отклики {account['name']}",
                        total=len(all_vacancies)
                    )

                    for idx, vacancy_id in enumerate(all_vacancies, 1):
                        if account["limit_exceeded"]:
                            console.print("\n[red]🚫 Лимит исчерпан — переход к следующему аккаунту[/red]")
                            break

                        progress.update(task, description=f"[cyan]{idx}/{len(all_vacancies)} ID: {vacancy_id}")

                        status_code, response_text, info = send_vacancy_response(
                            account["resume_hash"], vacancy_id, account["letter"], headers, cookies
                        )

                        if status_code != 200:
                            if "test-required" in response_text or "unknown" in response_text:
                                account["stats"]["skipped"] += 1
                            elif "alreadyApplied" in response_text:
                                account["stats"]["skipped"] += 1
                            elif "negotiations-limit-exceeded" in response_text:
                                mark_limit_exceeded(account)
                                break
                            else:
                                account["stats"]["errors"] += 1
                        else:
                            account["stats"]["sent"] += 1
                            print_vacancy_result(info, True)

                        progress.advance(task)
                        time.sleep(3)

                # Итог по аккаунту
                stats = account["stats"]
                console.print(Panel(
                    f"[bold green]✅ {account['name']} — ЗАВЕРШЕНО[/bold green]\n\n"
                    f"✉️ Отправлено: [green]{stats['sent']}[/green]  |  "
                    f"⏩ Пропущено: [yellow]{stats['skipped']}[/yellow]  |  "
                    f"❌ Ошибок: [red]{stats['errors']}[/red]",
                    border_style="green"
                ))

            # Итоговая статистика
            print_summary()
            last_response_attempt = now

        time.sleep(60)
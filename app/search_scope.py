"""Explicit remote/IT and country-ID vacancy scopes."""
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

IT_ROLES = frozenset('156 160 10 12 150 25 165 34 36 73 155 96 164 104 157 107 112 113 148 114 116 121 124 125 126'.split())
REMOTE_MARKERS = ('remote', 'удалён', 'удален', 'дистанцион', 'work from home')


def remote_it_filters(filters):
    return {**filters, 'professional_role': sorted(IT_ROLES, key=int), 'schedule': 'remote', 'work_format': 'REMOTE'}


def remote_it_url(url):
    parts = urlsplit(url)
    query = remote_it_filters(parse_qs(parts.query, keep_blank_values=True))
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def scope_metadata(item):
    area = item.get('area')
    address = item.get('address')
    return {key: item.get(key) for key in ('professional_roles', 'work_format', 'schedule')} | {
        'area_id': str(area.get('id') or '') if isinstance(area, dict) else '',
        'location': area.get('name', '') if isinstance(area, dict) else str(area or ''),
        'address': address.get('raw', '') if isinstance(address, dict) else str(address or ''),
    }


def is_remote_vacancy(meta):
    meta = meta if isinstance(meta, dict) else {}
    formats = meta.get('work_format')
    if isinstance(formats, list) and any(isinstance(item, dict) and item.get('id') == 'REMOTE' for item in formats):
        return True
    schedule = meta.get('schedule')
    if isinstance(schedule, dict) and schedule.get('id') == 'remote':
        return True
    if 'remote' in (meta.get('work_schedules') or []):
        return True
    text = ' '.join(str(meta.get(key) or '') for key in ('location', 'address', 'card_text')).lower()
    return any(marker in text for marker in REMOTE_MARKERS)


def remote_it_rejection(meta):
    roles = meta.get('professional_roles')
    if not isinstance(roles, list) or not roles:
        return 'scope_unknown'
    ids = {str(role.get('id')) for role in roles if isinstance(role, dict)}
    if not ids & IT_ROLES:
        return 'not_it'
    formats = meta.get('work_format')
    if isinstance(formats, list) and formats:
        return None if any(isinstance(item, dict) and item.get('id') == 'REMOTE' for item in formats) else 'not_remote'
    schedule = meta.get('schedule')
    if isinstance(schedule, dict) and schedule.get('id'):
        return None if schedule['id'] == 'remote' else 'not_remote'
    return 'scope_unknown'


def vacancy_scope_rejection(meta, *, remote_it_only=False, local_country_only=False,
                            local_country_id='', relocation_country_only=False,
                            relocation_country_ids=()):
    """Return None when a candidate satisfies at least one enabled scope."""
    meta = meta if isinstance(meta, dict) else {}
    country_id = str(meta.get('country_id') or '')
    if remote_it_only and remote_it_rejection(meta) is None:
        return None
    if local_country_only and local_country_id and country_id == str(local_country_id):
        return None
    if relocation_country_only and not is_remote_vacancy(meta) and country_id in {str(x) for x in relocation_country_ids}:
        return None
    return 'vacancy_outside_scope'

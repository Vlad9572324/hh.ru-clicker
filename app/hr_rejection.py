"""Detect HR rejection texts; HH sends them through the same workflow as invitations."""
import re

_REJECTION_RE = re.compile(
    r"к\s+сожален|не\s+готов[ыа]?\s+(пригласить|предложить|рассмотрет)"
    r"|не\s+смож(ем|ет)\s+пригласи"
    r"|не\s+сможем\s+продолж"
    r"|не\s+подход(ите|ит)"
    r"|не\s+соответству(ете|ет)"
    r"|поиск(ем|а)?\s+специалист[аов]+\s+другого"
    r"|ищем\s+специалист[аов]+\s+(другого|иного)"
    r"|сохран(им|яем)\s+(ваше\s+)?резюме"
    r"|приняли\s+решени[ея]\s+остановит"
    r"|решили\s+не\s+продолж"
    r"|отказ(ать|ываем)"
    r"|ценим\s+ваш[еиу]?\s+\w+[^.!?]{0,80}?,\s*но\b"
    r"|not\s+moving\s+forward|unfortunately\s+we|regret\s+to\s+inform",
    re.I)


def is_rejection(text) -> bool:
    """HR rejection text (HH sends these via the same workflow as invitations)."""
    return bool(_REJECTION_RE.search(str(text or "")))


_STOP_RE = re.compile(
    r"\b(хватит|перестаньте|прекратите|отстаньте|не\s+пишите|не\s+(надо|нужно)\s+(мне\s+)?писать"
    r"|please\s+stop|stop\s+(messaging|writing))\b",
    re.I)


def is_stop_request(text) -> bool:
    """HR explicitly asks to stop writing; an auto-reply here only makes it worse."""
    return bool(_STOP_RE.search(str(text or "")))

import math
import re

SPECIAL_CHARS = set(';/^{}\\[~]|€\'"')


def count_segments(message: str) -> int:
    """Termii: 160 chars/segment normally, 70 chars/segment if the message
    contains certain special characters (their own docs list these)."""
    if not message:
        return 1
    page_size = 70 if any(ch in SPECIAL_CHARS for ch in message) else 160
    return max(1, math.ceil(len(message) / page_size))


MERGE_FIELD_RE = re.compile(r'\{(name|fullname|phone)\}', re.IGNORECASE)


def has_merge_fields(message: str) -> bool:
    return bool(MERGE_FIELD_RE.search(message or ''))


def render_message(message: str, *, first_name: str = '', last_name: str = '', phone: str = '') -> str:
    """Fills {name} (first name), {fullname} and {phone}. A contact with no
    name reads as "there", so "Hi {name}" becomes "Hi there"."""
    first, last = (first_name or '').strip(), (last_name or '').strip()
    values = {'name': first or 'there', 'fullname': f'{first} {last}'.strip() or 'there', 'phone': phone}
    return MERGE_FIELD_RE.sub(lambda m: values[m.group(1).lower()], message)

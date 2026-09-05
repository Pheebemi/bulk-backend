import math

SPECIAL_CHARS = set(';/^{}\\[~]|€\'"')


def count_segments(message: str) -> int:
    """Termii: 160 chars/segment normally, 70 chars/segment if the message
    contains certain special characters (their own docs list these)."""
    if not message:
        return 1
    page_size = 70 if any(ch in SPECIAL_CHARS for ch in message) else 160
    return max(1, math.ceil(len(message) / page_size))

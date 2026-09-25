"""Date handling for filters. ManageBac often shows a due month and day without a year."""
import re
from datetime import date, datetime, timezone

MONTHS = {name: number for number, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), start=1)}
ISO_DATE = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'


def today() -> date:
    return datetime.now(timezone.utc).date()


def month_day(value: str, reference: date | None = None) -> str | None:
    """'Sep 17' → the ISO date in the year closest to today (the year is not displayed)."""
    match = re.fullmatch(r'\s*([A-Za-z]{3})[a-z]*\.?\s+([0-9]{1,2})\s*', value or '')
    month = MONTHS.get(match[1].casefold()) if match else None
    if not month: return None
    reference = reference or today()
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try: candidates.append(date(year, month, int(match[2])))
        except ValueError: pass
    return min(candidates, key=lambda d: abs(d - reference)).isoformat() if candidates else None


def shown_date(value: str) -> str | None:
    """A full date shown in text, e.g. 'Posted 1 file on Sep 16, 2026 at 9:48 PM' → '2026-09-16'."""
    match = re.search(r'\b([A-Za-z]{3})[a-z]*\.? ([0-9]{1,2}), ([0-9]{4})\b', value or '')
    month = MONTHS.get(match[1].casefold()) if match else None
    try: return date(int(match[3]), month, int(match[2])).isoformat() if month else None
    except ValueError: return None


def iso_day(value: str) -> str | None:
    """'2026-09-12T10:00:00Z' → '2026-09-12'."""
    return value[:10] if isinstance(value, str) and re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) else None


def valid_range(start: str, end: str):
    for value in (start, end):
        if value: date.fromisoformat(value)
    if start and end and start > end:
        raise ValueError('date_from must not be after date_to.')


def within(value: str | None, start: str, end: str) -> bool:
    return value is not None and (not start or value >= start) and (not end or value <= end)

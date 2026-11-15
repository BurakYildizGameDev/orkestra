import calendar
from datetime import date, timedelta


def add_months(day, months):
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def business_days_between(start, end):
    if end < start:
        return -business_days_between(end, start)
    count = 0
    current = start
    while current < end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count

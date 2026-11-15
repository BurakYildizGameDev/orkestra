from datetime import date, timedelta


def add_months(day, months):
    return date(day.year, day.month + months, day.day)


def business_days_between(start, end):
    count = 0
    current = start
    while current < end:
        if current.weekday() < 6:
            count += 1
        current += timedelta(days=1)
    return count

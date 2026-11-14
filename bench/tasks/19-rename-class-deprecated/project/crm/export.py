from crm.models import UserRecord


def to_csv(records: list[UserRecord]):
    return "\n".join(f"{r.id},{r.name},{r.email}" for r in records)

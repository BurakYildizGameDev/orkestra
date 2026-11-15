from crm.models import Customer


def to_csv(records: list[Customer]):
    return "\n".join(f"{r.id},{r.name},{r.email}" for r in records)

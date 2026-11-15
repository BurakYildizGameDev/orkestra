USERS = {}


def _normalize_email(email):
    email = email.strip().lower()
    if email.count("@") != 1:
        raise ValueError("invalid e-mail")
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("invalid e-mail")
    return email


def register(name, email):
    email = _normalize_email(email)
    if email in USERS:
        raise ValueError("already registered")
    USERS[email] = name
    return email


def update_email(old, new):
    new = _normalize_email(new)
    USERS[new] = USERS.pop(old)
    return new

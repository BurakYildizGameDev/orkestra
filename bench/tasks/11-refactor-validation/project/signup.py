USERS = {}


def register(name, email):
    email = email.strip().lower()
    if email.count("@") != 1:
        raise ValueError("invalid e-mail")
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("invalid e-mail")
    if email in USERS:
        raise ValueError("already registered")
    USERS[email] = name
    return email


def update_email(old, new):
    new = new.strip().lower()
    if new.count("@") != 1:
        raise ValueError("invalid e-mail")
    local, domain = new.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("invalid e-mail")
    USERS[new] = USERS.pop(old)
    return new

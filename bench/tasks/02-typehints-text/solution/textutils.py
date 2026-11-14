from collections.abc import Iterable


def shout(text: str) -> str:
    return text.upper() + "!"


def initials(name: str) -> str:
    return "".join(part[0].upper() for part in name.split() if part)


def word_lengths(words: Iterable[str]) -> dict[str, int]:
    return {word: len(word) for word in words}


def first_long_word(words: Iterable[str], minimum: int) -> str | None:
    for word in words:
        if len(word) >= minimum:
            return word
    return None


def join_lines(lines: Iterable[str], separator: str = "\n") -> str:
    return separator.join(lines)

def shout(text):
    return text.upper() + "!"


def initials(name):
    return "".join(part[0].upper() for part in name.split() if part)


def word_lengths(words):
    return {word: len(word) for word in words}


def first_long_word(words, minimum):
    for word in words:
        if len(word) >= minimum:
            return word
    return None


def join_lines(lines, separator="\n"):
    return separator.join(lines)

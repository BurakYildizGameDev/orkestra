import re
from collections import Counter

_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def top_words(text, n=3, stop_words=()):
    """The ``n`` most common words of ``text`` as a list of (word, count).

    Words are runs of letters (any alphabet) and apostrophes inside a word ("don't");
    compared in lower case. Words in ``stop_words`` (any case) are not counted. Ties are
    broken alphabetically. n < 1 gives an empty list.
    """
    if n < 1:
        return []
    stops = {word.lower() for word in stop_words}
    counts = Counter(w.lower() for w in _WORD.findall(text) if w.lower() not in stops)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]

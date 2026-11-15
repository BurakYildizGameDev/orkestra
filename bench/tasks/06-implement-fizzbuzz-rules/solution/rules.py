def play(n, rules=((3, "Fizz"), (5, "Buzz"))):
    """Generalised FizzBuzz for 1..n.

    ``rules`` is a sequence of (divisor, word). For each number the words of every rule whose
    divisor divides it are joined in the order of ``rules``; a number no rule matches is
    written as digits. Returns the list of strings. n < 1 gives an empty list; a divisor
    below 1 raises ValueError.
    """
    if any(divisor < 1 for divisor, _ in rules):
        raise ValueError("divisors must be at least 1")
    out = []
    for number in range(1, n + 1):
        words = "".join(word for divisor, word in rules if number % divisor == 0)
        out.append(words or str(number))
    return out

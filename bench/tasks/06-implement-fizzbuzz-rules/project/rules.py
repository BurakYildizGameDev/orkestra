def play(n, rules=((3, "Fizz"), (5, "Buzz"))):
    """Generalised FizzBuzz for 1..n.

    ``rules`` is a sequence of (divisor, word). For each number the words of every rule whose
    divisor divides it are joined in the order of ``rules``; a number no rule matches is
    written as digits. Returns the list of strings. n < 1 gives an empty list; a divisor
    below 1 raises ValueError.
    """
    raise NotImplementedError

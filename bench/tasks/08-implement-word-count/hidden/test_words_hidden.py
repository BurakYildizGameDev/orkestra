from words import top_words


def test_counts_and_order():
    text = "The cat and the hat. The CAT sat!"
    assert top_words(text, 2) == [("the", 3), ("cat", 2)]


def test_ties_are_alphabetical():
    assert top_words("b a c b a c", 3) == [("a", 2), ("b", 2), ("c", 2)]


def test_apostrophes_and_other_alphabets():
    assert top_words("Don't stop, don't! Çay çay ÇAY", 2) == [("çay", 3), ("don't", 2)]


def test_stop_words_and_edges():
    assert top_words("the the the cat", 1, stop_words=("The",)) == [("cat", 1)]
    assert top_words("anything", 0) == []
    assert top_words("", 3) == []
    assert top_words("123 456 !!", 3) == []

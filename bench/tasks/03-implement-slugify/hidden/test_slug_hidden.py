import pytest
from slug import slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("  Many   spaces  ", "many-spaces"),
        ("Çağrı Ünlü", "cagri-unlu"),
        ("C'est déjà l'été!", "c-est-deja-l-ete"),
        ("v2.0 -- release", "v2-0-release"),
        ("!!!", "n-a"),
        ("", "n-a"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


def test_max_length_never_ends_with_a_dash():
    slug = slugify("abc def ghi", max_length=8)
    assert slug == "abc-def"
    assert len(slugify("x" * 100)) == 50

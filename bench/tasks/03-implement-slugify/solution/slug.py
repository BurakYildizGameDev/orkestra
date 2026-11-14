import re
import unicodedata


def slugify(text, max_length=50):
    """Turn a title into a URL slug.

    - Lower case; letters with accents lose them ("Çağrı Ünlü" -> "cagri-unlu"; also ı -> i).
    - Every run of characters that are not a-z or 0-9 becomes one "-".
    - No "-" at the start or the end.
    - At most ``max_length`` characters; a cut never leaves a trailing "-".
    - An empty result is "n-a".
    """
    text = text.replace("ı", "i").replace("İ", "I")
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "n-a"

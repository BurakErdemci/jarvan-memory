"""Optional Turkish stemmer plugin (enable with `"stemmer": "tr"` in config).

A conservative suffix stripper over folded ASCII text (see util.fold). It
replaces a word with one canonical stem on both the query side and the
document side, so "notlarımızda" and "notlar" meet at "not". Being
conservative matters more than recall: an over-eager stemmer merges unrelated
words and the search gate starts letting noise through.
"""
from functools import lru_cache

# Longest first. (suffix, minimum stem length that must remain)
_SUFFIXES = sorted([
    # case and possessive endings
    ("lerinden", 3), ("larindan", 3), ("lerinde", 3), ("larinda", 3),
    ("lerine", 3), ("larina", 3), ("lerini", 3), ("larini", 3),
    ("imizda", 3), ("imizde", 3), ("umuzda", 3), ("umuzde", 3),
    ("imiz", 3), ("umuz", 3), ("iniz", 3), ("unuz", 3),
    ("ler", 3), ("lar", 3),
    ("nden", 3), ("ndan", 3), ("inde", 3), ("inda", 3), ("unda", 3), ("unde", 3),
    ("den", 3), ("dan", 3), ("ten", 3), ("tan", 3),
    ("nin", 3), ("nun", 3), ("in", 3), ("un", 3),
    ("de", 3), ("da", 3), ("te", 3), ("ta", 3),
    ("ye", 3), ("ya", 3), ("yi", 3), ("yu", 3),
    ("le", 3), ("la", 3), ("yle", 3), ("yla", 3),
    ("si", 3), ("su", 3),
    # verbal and derivational endings that carry little search meaning
    ("mesi", 3), ("masi", 3), ("mek", 3), ("mak", 3),
    ("iyor", 3), ("uyor", 3), ("acak", 3), ("ecek", 3),
    ("misti", 3), ("mustu", 3), ("dikten", 3), ("duktan", 3),
    ("dir", 3), ("dur", 3), ("tir", 3), ("tur", 3),
    ("li", 3), ("lu", 3), ("siz", 3), ("suz", 3), ("lik", 3), ("luk", 3),
], key=lambda s: -len(s[0]))

# Final consonant softening: kitabi -> kitab -> kitap.
_HARDEN = {"b": "p", "g": "k"}
_VOWELS = set("aeiou")


@lru_cache(maxsize=16384)
def stem(word):
    w = word
    # Strip to a fixpoint so query and document always reach the same stem
    # (a fixed number of passes breaks that symmetry).
    changed = True
    while changed and len(w) >= 5:
        changed = False
        for suf, keep in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= keep:
                w = w[: -len(suf)]
                changed = True
                break
    if len(w) >= 4 and w[-1] in ("b", "g") and w[-2] in _VOWELS:
        w = w[:-1] + _HARDEN[w[-1]]
    return w

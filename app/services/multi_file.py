"""
Several files in one check (stateless)

/analyze accepts up to MAX_FILES files in one request. Their text is joined with any pasted text and
scored together as one offer. Nothing is stored. One extra informational note is made here: when two
of the files contain nearly the same wording (word-shingle similarity), because a pack that repeats the
same letter, or the same letter under different file names, is worth a second look. It adds no score.
"""
import re
from typing import List, Optional

MAX_FILES = 5
SIMILARITY_LIMIT = 0.8
_MIN_WORDS = 20

DUPLICATE_NOTE = ("Two of the files you sent contain almost the same text. A genuine pack can repeat a letter, "
                  "but check that you were not sent the same document under different names.")


def _shingles(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").casefold())
    return {" ".join(words[i:i + 5]) for i in range(max(0, len(words) - 4))} if len(words) >= _MIN_WORDS else set()


def jaccard(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def duplicate_note(texts: List[str]) -> Optional[str]:
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if jaccard(texts[i], texts[j]) >= SIMILARITY_LIMIT:
                return DUPLICATE_NOTE
    return None

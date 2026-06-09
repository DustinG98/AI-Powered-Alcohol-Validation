"""Category identification for alcohol labels: wine, beer, spirits."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


SPIRITS_KEYWORDS = [
    r"whisky",
    r"whiskey",
    r"rum\b",
    r"vodka",
    r"gin\b",
    r"brandy",
    r"tequila",
    r"mezcal",
    r"bourbon",
    r"rye\b",
    r"scotch",
    r"liqueur",
    r"cognac",
    r"arak",
    r"schnapps",
    r"aquavit",
    r"grappa",
    r"pisco",
    r"eaux",
    r"distilled",
    r"distillery",
    r"straight",
]

BEER_KEYWORDS = [
    r"beer",
    r"ale\b",
    r"lager",
    r"stout",
    r"porter",
    r"brewery",
    r"brewing",
    r"brew\b",
    r"ipa\b",
    r"pilsner",
    r"pilsener",
    r"bitter",
    r"draught",
    r"draft\b",
    r"keg\b",
    r"bottled",
    r"barley",
    r"hops",
    r"fermented",
    r"bass\b",
    r"budweiser",
    r"miller",
    r"coors",
    r"heineken",
    r"corona",
    r"stella",
    r"guinness",
]

WINE_KEYWORDS = [
    r"wine\b",
    r"vineyard",
    r"vintage",
    r"winery",
    r"champagne",
    r"sparkling",
    r"port\b",
    r"sherry",
    r"moscato",
    r"bordeaux",
    r"burgundy",
    r"chardonnay",
    r"pinot",
    r"merlot",
    r"cabernet",
    r"sauvignon",
    r"riesling",
    r"zinfandel",
    r"malbec",
    r"syrah",
    r"petite",
    r"rose\b",
    r"rosa\b",
]


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _get_text_from_records(records: list[dict] | None) -> str:
    if not records:
        return ""
    parts = []
    for r in records or []:
        if isinstance(r, dict) and "text" in r:
            parts.append(r["text"])
    return " ".join(parts)


def _count_keyword_hits(text: str, patterns: list[str]) -> int:
    normalized = _normalize_text(text)
    count = 0
    for pattern in patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            count += 1
    return count


def identify_category(tokens: list[dict] | None = None, groups: list[dict] | None = None) -> str:
    text = _get_text_from_records(groups) or _get_text_from_records(tokens)

    spirits_score = _count_keyword_hits(text, SPIRITS_KEYWORDS)
    beer_score = _count_keyword_hits(text, BEER_KEYWORDS)
    wine_score = _count_keyword_hits(text, WINE_KEYWORDS)

    scores = {"spirits": spirits_score, "beer": beer_score, "wine": wine_score}
    best_category = max(scores, key=scores.get)

    if scores[best_category] == 0:
        return "unknown"

    return best_category
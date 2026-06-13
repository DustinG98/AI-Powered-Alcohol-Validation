"""Shared class/type designation extraction and validation logic.

The category-specific files (beer.py / wine.py / spirits.py) each supply
their own lexicon; this module provides the generic tokenize / match /
score machinery they all use.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.validators.rules.common import (
    _normalize_ws,
    _fuzzy_token_match,
    _is_warning_text,
    _safe_items,
)

# Local alias so the rest of the module reads naturally.
_normalize_text = _normalize_ws


# Local alias so the rest of the module reads naturally.
_normalize_text = _normalize_ws


def _word_boundary_contains(haystack: str, needle: str) -> bool:
    """True if `needle` appears in `haystack` at word boundaries.

    Both inputs are expected to be lowercased and whitespace-collapsed. This
    prevents e.g. "ale" matching inside "alehouse" or "sale".
    """
    if not needle or not haystack:
        return False
    if " " not in needle and len(needle) <= 3:
        # Short single tokens need stricter matching: require a word boundary
        # on BOTH sides, not just one.
        pattern = r"(?:^|\s)" + re.escape(needle) + r"(?:$|\s)"
        return bool(re.search(pattern, haystack))
    pattern = r"(?:^|\s)" + re.escape(needle) + r"(?:$|\s)"
    return bool(re.search(pattern, haystack))


def _entry_variants(entry: str) -> list[str]:
    """Return matching variants for a lexicon entry.

    For "kentucky straight bourbon whiskey" we also try shorter suffixes
    ("bourbon whiskey", "whiskey") so labels using just the tail of a
    composite designation still match. We DON'T include the bare first word
    because that's almost always too ambiguous.
    """
    norm = _normalize_text(entry)
    out = [norm]
    words = norm.split()
    for start in range(1, len(words)):
        sub = " ".join(words[start:])
        if len(sub) >= 4:
            out.append(sub)
    return out


def _lexicon_match_terms(lexicon: Iterable[str]) -> list[str]:
    """Flatten a lexicon into the list of normalized search terms."""
    terms: list[str] = []
    for entry in lexicon:
        terms.extend(_entry_variants(entry))
    # Deduplicate while preserving order; sort by length descending so longer
    # / more specific terms are tried first.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    deduped.sort(key=len, reverse=True)
    return deduped


def _document_text_excluding_warning(
    tokens: list[dict] | None, groups: list[dict] | None
) -> str:
    """Build the document text with government-warning lines removed.

    The warning is multi-line and dominates a large portion of typical label
    photos. Including it pollutes the class/type candidate pool with words
    like "alcoholic", "health", "consumption" that are not class designations.
    """
    source = _safe_items(groups) or _safe_items(tokens)
    if not source:
        return ""
    sorted_source = sorted(source, key=lambda r: r["bbox"].get("y_min", 0))
    parts: list[str] = []
    for r in sorted_source:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if _is_warning_text(text):
            continue
        parts.append(text)
    return " ".join(parts)


_NON_LEXICAL_TOKEN_RE = re.compile(
    r"^[\d.,%°]+$|^[a-z]{1,2}$|"
    r"^(ml|milliliters|millilitres|l|liters|litres|gal|gallons|"
    r"oz|fl|fluid|pt|qt|quarts|pint|pints|qt)$",
    re.IGNORECASE,
)


def _is_lexical_token(word: str) -> bool:
    """True for words that should participate in multi-word windows.

    Drops pure numerics, percent signs, dimensions, and 1-2 letter fragments
    so that "india pale 15.5 gal ale" can still produce the 3-word window
    "india pale ale" via non-contiguous selection.
    """
    stripped = re.sub(r"[^a-z0-9]", "", word)
    if not stripped:
        return False
    if _NON_LEXICAL_TOKEN_RE.match(word):
        return False
    return True


def _lexical_windows(words: list[str], max_words: int = 4) -> list[str]:
    """Build multi-word phrases from `words`, skipping non-lexical tokens.

    A non-lexical token (number, unit) breaks a window but does not prevent
    a window from re-starting. So "india pale 15.5 gal ale" yields windows
    like "india", "pale", "india pale", "ale", "gal ale" (5.16 was dropped),
    and via 3-4 word windows: "india pale ale" (skipping 15.5).
    """
    lexical_indices = [i for i, w in enumerate(words) if _is_lexical_token(w)]
    if not lexical_indices:
        return []

    out: set[str] = set()
    for n in range(1, max_words + 1):
        if len(lexical_indices) < n:
            continue
        for start in range(len(lexical_indices) - n + 1):
            window_indices = lexical_indices[start:start + n]
            if window_indices[-1] - window_indices[0] >= n + 2:
                # Allow skipping at most ~2 non-lexical tokens to span things
                # like "india pale 15.5 gal ale" -> "india pale ale".
                continue
            phrase = " ".join(words[i] for i in window_indices)
            if phrase:
                out.add(phrase)
    return [p for p in out if p]


def _substring_candidates_from_word(word: str) -> list[str]:
    """Emit substring candidates for an OCR-merged word.

    OCR frequently concatenates adjacent words that the group-merging step
    put on the same line, e.g. "RUMWITH" or "COCONUTLIQUEUR". We emit all
    substrings of length >= 3 as candidate phrases so that "rum", "coconut",
    and "liqueur" can still be found inside the merged token.
    """
    stripped = re.sub(r"[^a-z]", "", word)
    if len(stripped) < 3:
        return []
    out: set[str] = set()
    for start in range(len(stripped)):
        for end in range(start + 3, len(stripped) + 1):
            sub = stripped[start:end]
            out.add(sub)
    return list(out)


def _candidate_phrases_from_lines(
    text: str, max_words: int = 4
) -> list[str]:
    """Slice the warning-filtered document text into 1..max_words-word phrases.

    Also emits substring candidates for OCR-merged tokens (e.g. "RUMWITH"
    yields "rum", "rumwi", "rumwit", "rumwith", "umwith", ..., "with") so
    that class/type lexicons can still match even when the OCR fused two
    words into one. The matcher's word-boundary check will then pick the
    lexicon entries that fall inside the merged word.
    """
    norm = _normalize_text(text)
    if not norm:
        return []
    words = norm.split()
    out: set[str] = set()
    for n in range(1, max_words + 1):
        if len(words) < n:
            continue
        for start in range(len(words) - n + 1):
            phrase = " ".join(words[start:start + n])
            if phrase:
                out.add(phrase)
    out.update(_lexical_windows(words, max_words=max_words))
    for w in words:
        out.update(_substring_candidates_from_word(w))
    return [p for p in out if p]


def _is_garbage_phrase(phrase: str) -> bool:
    """Drop phrases that are clearly noise (digits, punctuation-only)."""
    stripped = re.sub(r"[^a-z0-9]", "", phrase)
    if not stripped:
        return True
    if stripped.isdigit():
        return True
    if re.match(r"^[\d\s\|]+$", phrase):
        return True
    return False


def detect_class_type(
    tokens: list[dict] | None,
    groups: list[dict] | None,
    lexicon: Iterable[str],
) -> dict:
    """Find the best-matching class/type phrase from `lexicon` in the OCR text.

    Returns a dict with:
        - match: matched lexicon entry (canonical form) or None
        - observed: the raw OCR phrase that matched
        - candidates: top scored candidates for debugging
    """
    match_terms = _lexicon_match_terms(lexicon)
    if not match_terms:
        return {"match": None, "observed": None, "candidates": []}

    doc_text = _document_text_excluding_warning(tokens, groups)
    if not doc_text:
        return {"match": None, "observed": None, "candidates": []}

    candidates = _candidate_phrases_from_lines(doc_text, max_words=4)
    candidates = [c for c in candidates if not _is_garbage_phrase(c)]

    scored: list[tuple[float, str, str]] = []
    for phrase in candidates:
        phrase_norm = _normalize_text(phrase)
        if not phrase_norm:
            continue

        # Find every lexicon entry that matches this candidate, then keep the
        # most specific (longest) one. This prevents "india" matching the
        # "india" suffix of "india pale ale" while "pale ale" matches the
        # 2-word entry -- we want the *full* "india pale ale" to win.
        matches: list[str] = []
        for term in match_terms:
            if _word_boundary_contains(phrase_norm, term):
                matches.append(term)
                continue
            # Substring match inside an OCR-merged single token, e.g.
            # candidate "coconutliqueur" contains term "liqueur" or
            # candidate "rumwith" contains term "rum". Required so
            # group-merged words can still be resolved.
            if " " not in term and " " not in phrase_norm and len(term) >= 4:
                if term in phrase_norm:
                    matches.append(term)
                    continue
            # Single-token fuzzy fallback: only when the term and candidate
            # are the same length. Catches OCR typos like "bourbn" -> "bourbon"
            # but blocks "brand" -> "brandy" (different lengths, different
            # words).
            if (
                " " not in term
                and " " not in phrase_norm
                and len(term) >= 5
                and len(term) == len(phrase_norm)
            ):
                if _fuzzy_token_match(term, phrase_norm):
                    matches.append(term)

        if not matches:
            continue

        # Prefer the longest term (most specific). Tie-break on the term
        # whose word count matches the candidate's word count.
        matches.sort(
            key=lambda t: (len(t), len(t.split())),
            reverse=True,
        )
        best_entry = matches[0]
        length_penalty = abs(
            len(phrase_norm.split()) - len(best_entry.split())
        )
        # Bonus for phrase containing the full term (no extra words).
        exact_phrase = phrase_norm == best_entry
        score = len(best_entry) - length_penalty * 2 + (5 if exact_phrase else 0)
        scored.append((score, phrase, best_entry))

    if not scored:
        return {"match": None, "observed": None, "candidates": []}

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[0]
    return {
        "match": top[2],
        "observed": top[1],
        "candidates": [
            {"phrase": p, "lexicon_entry": e, "score": round(s, 3)}
            for s, p, e in scored[:5]
        ],
    }


def verify_expected_class_type(
    expected: str,
    tokens: list[dict] | None,
    groups: list[dict] | None,
) -> dict:
    """Verify a caller-supplied class/type designation appears on the label.

    Uses word-boundary + fuzzy token matching against the warning-filtered
    document text. The result is a coverage-style outcome:
    MATCH (all expected tokens present), REVIEW REQUIRED (partial),
    MISSING (none).
    """
    expected_norm = _normalize_text(expected)
    expected_tokens = [t for t in expected_norm.split() if t]
    if not expected_tokens:
        return {
            "match": None,
            "observed": None,
            "matched_tokens": [],
            "missing_tokens": [],
            "coverage": 0.0,
        }

    doc_text = _document_text_excluding_warning(tokens, groups)
    norm_text = _normalize_text(doc_text)

    matched: list[str] = []
    missing: list[str] = []
    for et in expected_tokens:
        if _word_boundary_contains(norm_text, et):
            matched.append(et)
            continue
        words = norm_text.split()
        if any(_fuzzy_token_match(et, w) for w in words):
            matched.append(et)
            continue
        missing.append(et)

    coverage = len(matched) / len(expected_tokens) if expected_tokens else 0.0
    return {
        "match": " ".join(matched) if matched else None,
        "observed": " ".join(matched) if matched else None,
        "matched_tokens": matched,
        "missing_tokens": missing,
        "coverage": round(coverage, 3),
    }


def make_validate_class_type(lexicon: Iterable[str], label: str):
    """Build a validate_class_type function for a category-specific lexicon.

    `label` is the human-readable category name used in expected-field
    messages (e.g. "beer style", "wine varietal", "spirits type").
    """
    lexicon_list = list(lexicon)
    rule_name = f"class_type_{label.lower().replace(' ', '_')}"

    def validate_class_type(
        tokens: list[dict] | None = None,
        groups: list[dict] | None = None,
        expected: str | None = None,
    ) -> dict:
        detected = detect_class_type(tokens, groups, lexicon_list)

        if expected and expected.strip():
            verify = verify_expected_class_type(expected, tokens, groups)
            coverage = verify["coverage"]
            if coverage >= 1.0:
                status = "MATCH"
            elif coverage > 0.0:
                status = "REVIEW REQUIRED"
            else:
                status = "MISSING"
            return {
                "rule": rule_name,
                "status": status,
                "expected": expected.strip(),
                "observed": verify["observed"],
                "match": status == "MATCH",
                "detected": detected["match"],
                "detected_phrase": detected["observed"],
                "coverage": coverage,
                "missing_tokens": verify["missing_tokens"],
                "notes": [],
            }

        # No expected supplied -> detection-only outcome
        if detected["match"]:
            return {
                "rule": rule_name,
                "status": "MATCH",
                "expected": None,
                "observed": detected["observed"],
                "match": True,
                "detected": detected["match"],
                "detected_phrase": detected["observed"],
                "coverage": 1.0,
                "missing_tokens": [],
                "notes": [],
                "candidates": detected["candidates"],
            }

        return {
            "rule": rule_name,
            "status": "REVIEW REQUIRED",
            "expected": None,
            "observed": None,
            "match": False,
            "detected": None,
            "detected_phrase": None,
            "coverage": 0.0,
            "missing_tokens": [],
            "notes": [f"No recognized {label} found on label."],
            "candidates": [],
        }

    return validate_class_type

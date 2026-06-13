"""Shared validation rules applied to every alcohol category."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

REQUIRED_GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

_HEADER_CANONICAL = "GOVERNMENT WARNING:"
_BODY_THRESHOLD = 0.9
_BODY_SOFT_THRESHOLD = 0.75  # Accepts labels where OCR garbled only the tail
_WARN_HEADER = "government"

# ---------------------------------------------------------------------------
# Semantic anchor phrases
#
# The warning has two legally required clauses. Each clause is represented by
# a set of short, distinctive anchor phrases. A clause is "seen" when enough
# of its anchors are matched in the full-document text, regardless of where
# the tokens were spatially detected. This sidesteps the main failure mode of
# the old approach: keg-collar month abbreviations (SEPIOCTINOVIDEC,
# FEBIMARIAPRIM) and other noise tokens that overlap the warning region and
# corrupt spatial grouping.
# ---------------------------------------------------------------------------

# Clause 1: pregnancy / birth defects
_CLAUSE_1_ANCHORS: list[str] = [
    "surgeon general",
    "women should not drink",
    "alcoholic beverages",
    "during pregnancy",
    "birth defects",
]
# Clause 2: impairment / machinery
_CLAUSE_2_ANCHORS: list[str] = [
    "consumption of alcoholic",
    "impairs your ability",
    "drive",
    "operate machinery",
    "health problems",
]

# Minimum fraction of anchors required to consider a clause present.
_CLAUSE_ANCHOR_THRESHOLD = 0.6

# Spatial fallback constants (used only when semantic extraction is insufficient)
_COL_LEFT_SLACK = 80
_COL_RIGHT_SLACK = 150
_COL_BOUNDS_FUNCTION_LEFT = 20
_COL_BOUNDS_FUNCTION_RIGHT = 120
_MAX_GAP = 35
_RIGHT_TOKEN_RATIO = 0.4
_REVIEW_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def _flatten(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\s,.;:()]+", "", text).lower()


def _normalize_ws(text: str) -> str:
    """ASCII-fold and collapse whitespace, preserving word boundaries."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip().lower()


def _required_header_normalized() -> str:
    return _flatten(_HEADER_CANONICAL)


def _required_body_normalized() -> str:
    return _flatten(REQUIRED_GOVERNMENT_WARNING[len(_HEADER_CANONICAL):])


# ---------------------------------------------------------------------------
# Semantic anchor matching
# ---------------------------------------------------------------------------

def _anchors_present(full_text: str, anchors: list[str], threshold: float) -> bool:
    """Return True if at least `threshold` fraction of anchors appear in full_text."""
    normalised = _normalize_ws(full_text)
    hits = sum(1 for anchor in anchors if _normalize_ws(anchor) in normalised)
    return hits / len(anchors) >= threshold if anchors else False


def _clauses_present(full_text: str) -> tuple[bool, bool]:
    """Return (clause_1_present, clause_2_present) via anchor matching."""
    c1 = _anchors_present(full_text, _CLAUSE_1_ANCHORS, _CLAUSE_ANCHOR_THRESHOLD)
    c2 = _anchors_present(full_text, _CLAUSE_2_ANCHORS, _CLAUSE_ANCHOR_THRESHOLD)
    return c1, c2


def _header_present(full_text: str) -> bool:
    """True when 'GOVERNMENT WARNING' (correct casing) appears anywhere in the text."""
    return bool(re.search(r"GOVERNMENT\s*WARNING", full_text))


# ---------------------------------------------------------------------------
# Helpers shared by both extraction paths
# ---------------------------------------------------------------------------

def _safe_items(records: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        bbox = r.get("bbox")
        text = r.get("text")
        if not isinstance(bbox, dict) or not text:
            continue
        out.append({"text": text, "bbox": bbox})
    return out


def _build_token_index(
    tokens: list[dict] | None,
) -> dict[tuple[int, int, int, int], dict]:
    out: dict[tuple[int, int, int, int], dict] = {}
    for t in tokens or []:
        if not isinstance(t, dict):
            continue
        bbox = t.get("bbox")
        if not isinstance(bbox, dict):
            continue
        key = (
            int(bbox.get("x_min", 0)),
            int(bbox.get("y_min", 0)),
            int(bbox.get("x_max", 0)),
            int(bbox.get("y_max", 0)),
        )
        out[key] = t
    return out


def _tokens_in_bbox(
    token_index: dict[tuple[int, int, int, int], dict],
    bbox: dict,
    slack: int = 0,
) -> list[dict]:
    x_min = bbox.get("x_min", 0) - slack
    y_min = bbox.get("y_min", 0) - slack
    x_max = bbox.get("x_max", 0) + slack
    y_max = bbox.get("y_max", 0) + slack
    matches: list[dict] = []
    for (tx_min, ty_min, tx_max, ty_max), t in token_index.items():
        if tx_min >= x_min and ty_min >= y_min and tx_max <= x_max and ty_max <= y_max:
            matches.append(t)
    return matches


# ---------------------------------------------------------------------------
# Primary path: semantic extraction from full document text
#
# Concatenate ALL tokens (or groups) into a single string and let anchor
# matching do the heavy lifting. This is robust to spatial noise (rotated
# collar text, overlapping bboxes, OCR-merged groups) because it never tries
# to isolate a region.
# ---------------------------------------------------------------------------

def _full_document_text(
    tokens: list[dict] | None,
    groups: list[dict] | None,
) -> str:
    """Return a single string from all available OCR output, preserving reading order.

    Groups are sorted top-to-bottom; tokens fill in when groups are absent.
    Tokens that appear to be radial/calendar noise (very high aspect-ratio
    bboxes or text matching known month-abbreviation patterns) are excluded.
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
        if _is_calendar_noise(text):
            continue
        parts.append(text)
    return " ".join(parts)


_CALENDAR_NOISE_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec){2,}",
    re.IGNORECASE,
)
_DIGIT_PIPE_RE = re.compile(r"^[\d|]+$")


def _is_calendar_noise(text: str) -> bool:
    """Heuristic to drop keg-collar month/number ring tokens.

    Tokens like 'SEPIOCTINOVIDEC' or '25|26127|28|29|30|31' are artefacts of
    radially printed month/date rings and should not pollute the warning text.
    """
    stripped = text.strip()
    if _DIGIT_PIPE_RE.match(stripped):
        return True
    if len(stripped) >= 12 and _CALENDAR_NOISE_RE.match(stripped):
        return True
    # Runs of concatenated 2-digit numbers (date rings)
    if re.match(r"^(\d{2}){4,}$", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Government-warning text detection (shared with branding / class_type)
# ---------------------------------------------------------------------------

_WARNING_LEAK_PATTERNS = [
    r"government\s*warning",
    r"surgeon\s*general",
    r"women\s*should\s*not",
    r"drink\s*alcoholic",
    r"alcoholic\s*beverages",
    r"pregnancy",
    r"birth\s*defects",
    r"machinery",
    r"health\s*problems",
    r"consumption\s*of",
    r"impairs\s*your",
    r"operate\s*machinery",
    r"\(1\)",
    r"\(2\)",
    r"according\s*to\s*the",
    r"drive\s*a\s*car",
]
_WARNING_RE = re.compile("|".join(_WARNING_LEAK_PATTERNS), re.IGNORECASE)


def _is_warning_text(text: str) -> bool:
    flat = _flatten(text)
    return bool(_WARNING_RE.search(flat))


def _extract_warning_from_full_text(full_text: str) -> str:
    """Locate and return the government warning substring from the full document text.

    Scans for the 'GOVERNMENT WARNING' header and returns from that point to
    the end of the last sentence that contains a warning keyword. Falls back
    to returning everything from the header onward if no clean endpoint is
    found.
    """
    match = re.search(r"GOVERNMENT\s*WARNING", full_text)
    if not match:
        # Try case-insensitive as a last resort for the extraction step; case
        # correctness is checked separately in validate_government_warning.
        match = re.search(r"government\s*warning", full_text, re.IGNORECASE)
    if not match:
        return ""

    candidate = full_text[match.start():]

    # Try to trim at a natural endpoint: the last occurrence of a clause-2
    # tail keyword followed by a sentence-ending punctuation or end-of-string.
    tail_pattern = re.compile(
        r"(health\s+problems|operate\s+machinery)[^.]*\.?", re.IGNORECASE
    )
    tail_match = None
    for m in tail_pattern.finditer(candidate):
        tail_match = m
    if tail_match:
        candidate = candidate[: tail_match.end()].strip()

    return candidate


# ---------------------------------------------------------------------------
# Spatial fallback path (kept from original; used only when semantic path
# cannot locate the warning)
# ---------------------------------------------------------------------------

def _find_clean_header(records: list[dict], token_index: dict) -> dict | None:
    if not records:
        return None
    sorted_records = sorted(records, key=lambda r: r["bbox"].get("y_min", 0))

    for r in sorted_records:
        contained = _tokens_in_bbox(token_index, r["bbox"], slack=2) if token_index else []
        if contained:
            g_x_min = r["bbox"].get("x_min", 0)
            g_x_max = r["bbox"].get("x_max", 0)
            x_threshold = g_x_min + (g_x_max - g_x_min) * _RIGHT_TOKEN_RATIO
            right_tokens = [t for t in contained if t["bbox"].get("x_min", 0) >= x_threshold]
            candidate_tokens = right_tokens if right_tokens else contained
            joined = " ".join(t.get("text", "") for t in candidate_tokens).strip()
        else:
            joined = (r.get("text") or "").strip()
        flat = _flatten(joined)
        if "government" in flat and "warning" in flat:
            return r

    for r in sorted_records:
        contained = _tokens_in_bbox(token_index, r["bbox"], slack=2) if token_index else []
        if contained:
            g_x_min = r["bbox"].get("x_min", 0)
            g_x_max = r["bbox"].get("x_max", 0)
            x_threshold = g_x_min + (g_x_max - g_x_min) * _RIGHT_TOKEN_RATIO
            right_tokens = [t for t in contained if t["bbox"].get("x_min", 0) >= x_threshold]
            candidate_tokens = right_tokens if right_tokens else contained
            joined = " ".join(t.get("text", "") for t in candidate_tokens).strip()
        else:
            joined = (r.get("text") or "").strip()
        if _WARN_HEADER in _flatten(joined):
            return r

    return None


def _col_bounds_for(
    header: dict,
    right_slack: int = _COL_BOUNDS_FUNCTION_RIGHT,
    left_slack: int = _COL_BOUNDS_FUNCTION_LEFT,
) -> tuple[int, int]:
    bbox = header["bbox"]
    return bbox.get("x_min", 0) - left_slack, bbox.get("x_max", 0) + right_slack


def _collect_in_column(
    records: list[dict], header: dict, max_gap: int = _MAX_GAP
) -> list[dict]:
    header_x_min = header["bbox"].get("x_min", 0)
    header_x_max = header["bbox"].get("x_max", 0)
    header_y_min = header["bbox"].get("y_min", 0)
    col_x_min = header_x_min - _COL_LEFT_SLACK
    col_x_max = header_x_max + _COL_RIGHT_SLACK
    sorted_records = sorted(
        (r for r in records if r is not header),
        key=lambda r: r["bbox"].get("y_min", 0),
    )
    block: list[dict] = []
    prev_y_max = header["bbox"].get("y_max", 0)
    for r in sorted_records:
        r_x_min = r["bbox"].get("x_min", 0)
        r_y_min = r["bbox"].get("y_min", 0)
        in_column = col_x_min <= r_x_min <= col_x_max
        if r_y_min < header_y_min:
            continue
        if not in_column and block:
            continue
        gap = r_y_min - prev_y_max
        if block and gap > max_gap:
            break
        block.append(r)
        prev_y_max = max(prev_y_max, r["bbox"].get("y_max", 0))
    return [header, *block]


def _spatial_extract_warning_text(
    records: list[dict] | None,
    tokens: list[dict] | None = None,
) -> str:
    """Spatial fallback: isolate the warning column then read it line by line."""
    safe = _safe_items(records)
    token_index = _build_token_index(tokens)
    header = _find_clean_header(safe, token_index)
    if not header:
        return ""

    col_x_min = header["bbox"].get("x_min", 0) - _COL_LEFT_SLACK
    col_x_max = header["bbox"].get("x_max", 0) + _COL_RIGHT_SLACK
    block = _collect_in_column(safe, header)

    pieces: list[str] = []
    for r in block:
        if tokens:
            contained = _tokens_in_bbox(token_index, r["bbox"], slack=2)
            contained = [
                t for t in contained
                if col_x_min <= t["bbox"].get("x_min", 0) <= col_x_max
            ]
            if contained:
                contained_sorted = sorted(
                    contained, key=lambda t: t["bbox"].get("x_min", 0)
                )
                line_text = " ".join(
                    t.get("text", "") for t in contained_sorted
                ).strip()
                if line_text:
                    pieces.append(line_text)
                continue
        text = (r.get("text") or "").strip()
        if text:
            pieces.append(text)

    return " ".join(pieces)


# ---------------------------------------------------------------------------
# Token-level scoring (unchanged from original)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase, ASCII, alnum-only tokens. Keeps single letters; drops digits."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z]+", " ", text).lower()
    return [t for t in text.split() if t and not t.isdigit()]


def _expand_against_vocab(tokens: Iterable[str], vocab: set[str]) -> list[str]:
    out: list[str] = []
    for token in tokens:
        if not token or token in vocab:
            out.append(token)
            continue
        cursor = 0
        pieces: list[str] = []
        while cursor < len(token):
            matched = ""
            for end in range(len(token), cursor, -1):
                piece = token[cursor:end]
                if piece in vocab:
                    matched = piece
                    break
            if not matched:
                pieces.append(token[cursor:])
                cursor = len(token)
                break
            pieces.append(matched)
            cursor += len(matched)
        out.extend(p for p in pieces if p)
    return out


def _fuzzy_token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    if abs(len(a) - len(b)) <= 1:
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        diffs = sum(1 for x, y in zip(short, long) if x != y) + abs(len(a) - len(b))
        if diffs <= 1:
            return True
    return False


def _token_presence_score(observed: list[str], required: list[str]) -> float:
    if not required:
        return 1.0
    n, m = len(observed), len(required)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if _fuzzy_token_match(observed[i - 1], required[j - 1]):
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m] / m


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_government_warning(
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
) -> dict:
    """Check the Government Warning against the TTB-required statement.

    Extraction strategy (in priority order):

    1. **Semantic path** — concatenate all tokens into one string (excluding
       obvious calendar/noise tokens), locate 'GOVERNMENT WARNING' by regex,
       and trim to the natural end of the warning body. This is resilient to
       spatial noise, overlapping bbox groups, and OCR-merged tokens.

    2. **Spatial fallback** — if the semantic path yields no header, fall back
       to the original column-isolation approach. This handles edge cases where
       the header token is only detectable spatially (e.g. extremely low
       contrast text that OCR partially drops).

    Scoring is always done on the extracted text using the same LCS-based
    fuzzy token presence score as before.
    """
    # --- Step 1: build full-document text and attempt semantic extraction ---
    full_text = _full_document_text(tokens, groups)
    warning_text = _extract_warning_from_full_text(full_text)

    # --- Step 2: spatial fallback if semantic path found nothing ---
    if not warning_text:
        warning_text = (
            _spatial_extract_warning_text(groups, tokens=tokens)
            or _spatial_extract_warning_text(tokens, tokens=tokens)
        )

    # --- Step 3: quick semantic clause check to detect obvious absences ---
    # If we have a full_text but the semantic path found no header, we can
    # still report clause coverage to distinguish MISSING vs MISMATCH.
    c1_present, c2_present = _clauses_present(full_text)

    if not warning_text:
        return {
            "rule": "government_warning",
            "status": "MISSING",
            "expected": REQUIRED_GOVERNMENT_WARNING,
            "observed": None,
            "match": False,
            "header_match": False,
            "clause_1_present": c1_present,
            "clause_2_present": c2_present,
        }

    # --- Step 4: header casing check ---
    flattened = _flatten(warning_text)
    case_insensitive_header = flattened.startswith(_required_header_normalized())
    case_sensitive_header = bool(
        re.match(r"^[^A-Za-z]*GOVERNMENT\s*WARNING", warning_text.lstrip())
    )
    header_match = case_insensitive_header and case_sensitive_header

    # --- Step 5: body token-presence score ---
    required_tokens = _tokenize(REQUIRED_GOVERNMENT_WARNING[len(_HEADER_CANONICAL):])
    observed_tokens = _tokenize(warning_text)
    observed_tokens = _expand_against_vocab(observed_tokens, set(required_tokens))
    score = _token_presence_score(observed_tokens, required_tokens)

    if score >= _BODY_THRESHOLD and case_sensitive_header:
        body_match = True
        status = "MATCH"
    elif score >= _BODY_SOFT_THRESHOLD and case_sensitive_header:
        body_match = True
        status = "MATCH"
    elif not case_sensitive_header:
        body_match = False
        status = "MISMATCH"
    elif score >= _REVIEW_THRESHOLD:
        body_match = False
        status = "REVIEW REQUIRED"
    else:
        body_match = False
        status = "MISMATCH"

    matched = header_match and body_match

    return {
        "rule": "government_warning",
        "status": status,
        "expected": REQUIRED_GOVERNMENT_WARNING,
        "observed": warning_text,
        "match": matched,
        "header_match": header_match,
        "header_case_valid": case_sensitive_header,
        "body_token_score": round(score, 3),
        "clause_1_present": c1_present,
        "clause_2_present": c2_present,
    }


_NET_CONTENTS_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(ml|milliliters|millilitres|l|liters|litres|gal|gallons|oz|fl\s*oz|fluid\s*ounces|pint|pints|pt|qt|quarts)\b",
    r"net\s+(?:wt\s+)?(\d+(?:\.\d+)?)\s*(ml|milliliters|millilitres|l|liters|litres|oz|fl\s*oz|fluid\s*ounces|g|grams|kg|kilograms)\b",
    r"(\d+(?:\.\d+)?)\s*(ml|milliliters|millilitres|l|liters|litres|oz|fl\s*oz|fluid\s*ounces|pint|pints|pt|gal|gallons)\s*(?:net\s+)?(?:wt|contents)?",
]

_NET_CONTENTS_UNITS = {
    "ml": "ml",
    "milliliters": "ml",
    "millilitres": "ml",
    "l": "L",
    "liters": "L",
    "litres": "L",
    "gal": "gal",
    "gallons": "gal",
    "oz": "oz",
    "fl oz": "fl oz",
    "fluid ounces": "fl oz",
    "pint": "pint",
    "pints": "pint",
    "pt": "pint",
    "qt": "qt",
    "quarts": "qt",
    "g": "g",
    "grams": "g",
    "kg": "kg",
    "kilograms": "kg",
}

_VALID_NET_CONTENTS = {
    "beer": {
        "pint", "pints", "pt",
        "fl oz", "fluid ounces",
        "oz", "L", "ml", "liters", "milliliters",
        "gal", "gallon", "gallons",
        "qt", "quarts",
    },
    "wine": {
        "ml", "milliliters", "millilitres",
        "L", "liters", "litres",
        "fl oz", "fluid ounces", "oz",
        "gal", "gallons",
    },
    "spirits": {
        "ml", "milliliters", "millilitres",
        "L", "liters", "litres",
        "fl oz", "fluid ounces", "oz",
        "gal", "gallons",
        "pint", "pints", "pt",
    },
}


def _find_net_contents(text: str) -> str | None:
    for pattern in _NET_CONTENTS_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1)
            unit = match.group(2).lower()
            normalized_unit = _NET_CONTENTS_UNITS.get(unit, unit)
            return f"{value} {normalized_unit}"
    return None


def validate_net_contents(
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
    category: str = "unknown",
) -> dict:
    """Check that net contents are present and use a valid unit for the category."""
    source = _safe_items(groups) or _safe_items(tokens)
    if not source:
        return {
            "rule": "net_contents",
            "status": "MISSING",
            "expected": "Valid net contents (e.g., 750 ml, 1.75 L, 12 fl oz, 1 pint)",
            "observed": None,
            "match": False,
        }

    sorted_source = sorted(source, key=lambda r: r["bbox"].get("y_min", 0))
    full_text = " ".join(r.get("text", "") for r in sorted_source)

    found = _find_net_contents(full_text)
    if not found:
        return {
            "rule": "net_contents",
            "status": "MISSING",
            "expected": "Valid net contents (e.g., 750 ml, 1.75 L, 12 fl oz, 1 pint)",
            "observed": None,
            "match": False,
        }

    value_match = re.match(r"([\d.]+)\s+(\w+)", found, re.IGNORECASE)
    if not value_match:
        return {
            "rule": "net_contents",
            "status": "MISMATCH",
            "expected": "Valid net contents (e.g., 750 ml, 1.75 L, 12 fl oz, 1 pint)",
            "observed": found,
            "match": False,
        }

    value = float(value_match.group(1))
    unit_raw = value_match.group(2).lower()
    unit = _NET_CONTENTS_UNITS.get(unit_raw, unit_raw)

    valid_units = _VALID_NET_CONTENTS.get(category, set())
    if unit in valid_units or category == "unknown":
        return {
            "rule": "net_contents",
            "status": "MATCH",
            "expected": "Valid net contents for category",
            "observed": found,
            "match": True,
        }
    else:
        return {
            "rule": "net_contents",
            "status": "MISMATCH",
            "expected": f"Valid net contents units for {category}: {', '.join(sorted(valid_units))}",
            "observed": found,
            "match": False,
        }
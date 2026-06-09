"""Brand verification and detection for alcohol labels."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.validators.rules.common import (
    _safe_items,
    _is_calendar_noise,
    _tokenize,
    _fuzzy_token_match,
    _full_document_text,
    _flatten,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_BRAND_LEXICON = {
    "brewery",
    "brewing",
    "co",
    "company",
    "distilling",
    "distillery",
    "winery",
    "vineyards",
    "estate",
    "imports",
    "cellars",
    "spirits",
    "cidery",
    "meadery",
    "liquors",
    "beer",
    "ale",
    "lager",
    "pub",
    "tavern",
    "bottling",
    "vintners",
}

_DETECT_HIGH_THRESHOLD = 0.5
_DETECT_FLOOR = 0.2
_GROUP_MERGE_GAP_RATIO = 0.6
_FUZZY_MIN_TOKEN_LEN = 3       # for direct fuzzy/prefix match
_SUBSTRING_MIN_TOKEN_LEN = 2   # for substring match (e.g. "co" in "examplebrewingco")

# ---------------------------------------------------------------------------
# Warning text detection (used to filter brand candidates and build observed)
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


# ---------------------------------------------------------------------------
# Token building helpers
# ---------------------------------------------------------------------------

def _build_observed_tokens(tokens, groups):
    """Return (observed_tokens, observed_full_text) from all non-warning tokens.

    observed_tokens is a list of {"text": ..., "bbox": ...} dicts from the OCR,
    filtered to exclude calendar noise and warning text. They are sorted
    top-to-bottom, left-to-right.
    """
    items = _safe_items(groups) or _safe_items(tokens)
    if not items:
        return [], ""

    sorted_items = sorted(items, key=lambda r: (r["bbox"].get("y_min", 0), r["bbox"].get("x_min", 0)))

    cleaned = []
    for r in sorted_items:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if _is_calendar_noise(text):
            continue
        if _is_warning_text(text):
            continue
        cleaned.append({"text": text, "bbox": r["bbox"]})

    full_text = " ".join(c["text"] for c in cleaned)
    return cleaned, full_text


# ---------------------------------------------------------------------------
# verify_brand — matching path (expected brand supplied)
# ---------------------------------------------------------------------------

def _strip_punct(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _token_matches_in_observed_text(
    et: str,
    observed_text: str,
) -> bool:
    """Check if expected token matches against a single observed text value.

    Two strategies, in order:
    1. Direct fuzzy token match (equal, prefix with len >= 3, or 1-edit).
    2. Substring: et appears inside the stripped (punctuation-removed) text.
       Allows 2-char tokens like "co" to match inside "examplebrewingco".
    """
    ot = observed_text.lower()
    if _fuzzy_token_match(et, ot):
        return True
    stripped = _strip_punct(observed_text)
    if len(et) >= _SUBSTRING_MIN_TOKEN_LEN and et in stripped:
        return True
    return False


def _find_expected_matches(
    expected_tokens: list[str],
    observed_texts: list[str],
) -> dict[str, dict]:
    """For each expected token, locate the best observed token(s) that match it.

    Returns a dict mapping expected_token -> {
        "observed_indices": set[int],  # OCR token indices consumed
        "observed_texts": list[str],   # the consumed texts
    }

    Matching strategies (per expected token):
    1. Direct fuzzy or substring match against a single observed token.
       A single observed token can satisfy multiple expected tokens
       (e.g. "EXAMPLEBREWINGCO." matches "example", "brewing", and "co").
    2. Concatenation of 2 or 3 adjacent observed tokens matches the
       expected token (handles OCR splits like "BRE" + "WERY" = "brewery").
       Index ranges already claimed by other adjacent-concat matches are
       skipped to prevent double-counting.
    """
    observed_lower = [t.lower() for t in observed_texts]
    used_ranges: list[set[int]] = []
    matches: dict[str, dict] = {}

    def _range_available(indices: set[int]) -> bool:
        for used in used_ranges:
            if indices & used:
                return False
        return True

    for et in expected_tokens:
        if et in matches:
            continue

        # 1. Single-token direct / substring match. Multiple expected
        #    tokens can claim the same observed token.
        matched_single = False
        for i, ot in enumerate(observed_lower):
            if _token_matches_in_observed_text(et, observed_texts[i]):
                matches[et] = {
                    "observed_indices": {i},
                    "observed_texts": [observed_texts[i]],
                }
                matched_single = True
                break

        if matched_single:
            continue

        # 2. Adjacent-token concatenation (handles "BRE" + "WERY" = "brewery")
        for n in (2, 3):
            if len(observed_lower) < n:
                continue
            matched_concat = False
            for start in range(len(observed_lower) - n + 1):
                indices = {start + k for k in range(n)}
                if not _range_available(indices):
                    continue
                joined = "".join(observed_texts[start:start + n])
                if _token_matches_in_observed_text(et, joined):
                    used_ranges.append(indices)
                    matches[et] = {
                        "observed_indices": indices,
                        "observed_texts": list(observed_texts[start:start + n]),
                    }
                    matched_concat = True
                    break
            if matched_concat:
                break

    return matches


def verify_brand(
    expected_brand: str,
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
) -> dict[str, Any]:
    """Check that the expected brand appears in the OCR output.

    Case-insensitive. Uses three matching strategies to handle OCR noise:
    1. Direct fuzzy token match (prefix + 1-edit tolerance).
    2. Substring match: expected word appears inside a concatenated OCR
       token (e.g. "BREWINGCO." contains both "brewing" and "co").
    3. Adjacent-token concatenation: expected word is the join of 2-3
       consecutive OCR tokens (e.g. "BRE" + "WERY" = "brewery").
    """
    empty_result = {
        "rule": "brand_verification",
        "status": "MISSING",
        "expected": expected_brand or "",
        "observed": None,
        "match": False,
        "expected_token_count": 0,
        "matched_token_count": 0,
        "coverage": 0.0,
        "missing_tokens": [],
        "matched_token_bboxes": [],
    }

    if not expected_brand or not expected_brand.strip():
        return empty_result

    expected_tokens = _tokenize(expected_brand)
    if not expected_tokens:
        return {**empty_result, "expected": expected_brand}

    observed_items, _ = _build_observed_tokens(tokens, groups)
    observed_texts = [item["text"] for item in observed_items]
    observed_bboxes = [item["bbox"] for item in observed_items]

    matches = _find_expected_matches(expected_tokens, observed_texts)

    matched_expected = list(matches.keys())
    missing = [et for et in expected_tokens if et not in matches]
    coverage = len(matched_expected) / len(expected_tokens) if expected_tokens else 0.0

    if coverage == 1.0:
        status = "MATCH"
    elif coverage > 0.0:
        status = "REVIEW REQUIRED"
    else:
        status = "MISSING"

    matched_observed_texts: list[str] = []
    matched_bboxes: list[dict] = []
    seen_observed_indices: set[int] = set()
    for et in matched_expected:
        info = matches[et]
        for idx, txt in zip(info["observed_indices"], info["observed_texts"]):
            if idx in seen_observed_indices:
                continue
            seen_observed_indices.add(idx)
            matched_observed_texts.append(txt)
            matched_bboxes.append(observed_bboxes[idx])

    return {
        "rule": "brand_verification",
        "status": status,
        "expected": expected_brand,
        "observed": " ".join(matched_observed_texts) if matched_observed_texts else None,
        "match": status == "MATCH",
        "expected_token_count": len(expected_tokens),
        "matched_token_count": len(matched_expected),
        "coverage": round(coverage, 3),
        "missing_tokens": missing,
        "matched_token_bboxes": matched_bboxes,
    }


# ---------------------------------------------------------------------------
# detect_branding — detection fallback (no expected brand supplied)
# ---------------------------------------------------------------------------

def _merge_adjacent_groups(groups: list[dict]) -> list[dict]:
    """Re-join groups that are vertically adjacent and horizontally overlapping.

    This recovers split brand names like "EXAMPLE" / "BREWINGCO." into one group.
    """
    if not groups:
        return []

    sorted_groups = sorted(groups, key=lambda g: g["bbox"].get("y_min", 0))
    heights = [
        max(g["bbox"].get("y_max", 0) - g["bbox"].get("y_min", 0), 1)
        for g in sorted_groups
    ]
    median_h = sorted(heights)[len(heights) // 2] if heights else 12
    max_gap = max(median_h * _GROUP_MERGE_GAP_RATIO, 4)

    merged: list[dict] = []
    for g in sorted_groups:
        if not merged:
            merged.append(g)
            continue
        prev = merged[-1]
        prev_y_max = prev["bbox"].get("y_max", 0)
        curr_y_min = g["bbox"].get("y_min", 0)
        gap = curr_y_min - prev_y_max
        prev_x_min = prev["bbox"].get("x_min", 0)
        prev_x_max = prev["bbox"].get("x_max", 0)
        curr_x_min = g["bbox"].get("x_min", 0)
        curr_x_max = g["bbox"].get("x_max", 0)
        x_overlap = not (curr_x_min > prev_x_max or curr_x_max < prev_x_min)
        if gap <= max_gap and x_overlap:
            new_bbox = {
                "x_min": min(prev_x_min, curr_x_min),
                "y_min": prev["bbox"].get("y_min", 0),
                "x_max": max(prev_x_max, curr_x_max),
                "y_max": max(prev_y_max, g["bbox"].get("y_max", 0)),
            }
            merged[-1] = {"text": (prev.get("text") or "") + " " + (g.get("text") or ""), "bbox": new_bbox}
        else:
            merged.append(g)
    return merged


def _candidate_score(
    group: dict,
    tokens_by_group: dict[int, list[dict]],
    group_idx: int,
    image_height: int | None = None,
) -> float:
    """Score a group candidate for brand detection.

    Combines position, font-size, lexicon match, and OCR confidence.
    """
    bbox = group.get("bbox", {})
    y_min = bbox.get("y_min", 0)
    y_max = bbox.get("y_max", 0)
    height = max(y_max - y_min, 1)

    text = group.get("text", "") or ""
    norm_text = _flatten(text)
    token_list = [t for t in norm_text.split() if t]

    if not token_list:
        return 0.0

    pos_score = 0.0
    if image_height and image_height > 0:
        rel_y = y_min / image_height
        if rel_y < 0.15:
            pos_score = 1.0
        elif rel_y < 0.35:
            pos_score = 0.6
        elif rel_y < 0.55:
            pos_score = 0.3
        else:
            pos_score = 0.0

    tokens_in_group = tokens_by_group.get(group_idx, [])
    median_token_h = 12
    if tokens_in_group:
        token_heights = [
            max(t["bbox"].get("y_max", 0) - t["bbox"].get("y_min", 0), 1)
            for t in tokens_in_group
        ]
        if token_heights:
            sorted_h = sorted(token_heights)
            median_token_h = sorted_h[len(sorted_h) // 2]

    all_token_heights = []
    for tlist in tokens_by_group.values():
        for t in tlist:
            all_token_heights.append(max(t["bbox"].get("y_max", 0) - t["bbox"].get("y_min", 0), 1))
    overall_median_h = 12
    if all_token_heights:
        sorted_ah = sorted(all_token_heights)
        overall_median_h = sorted_ah[len(sorted_ah) // 2]

    size_score = min(median_token_h / max(overall_median_h, 1), 2.0) / 2.0

    lex_score = 0.0
    for tok in token_list:
        if tok in _BRAND_LEXICON:
            lex_score += 0.25
    lex_score = min(lex_score, 1.0)

    conf_score = 0.0
    if tokens_in_group:
        conf_score = sum(t.get("confidence", 0.0) for t in tokens_in_group) / len(tokens_in_group)

    return 0.35 * pos_score + 0.25 * size_score + 0.25 * lex_score + 0.15 * conf_score


def detect_branding(
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
    category: str = "unknown",
) -> dict[str, Any]:
    """Best-effort brand detection when no expected brand is supplied.

    Returns MATCH / REVIEW REQUIRED / MISSING based on detection confidence.
    Also returns detected_brand and candidates for debugging / display.
    """
    safe_tokens = _safe_items(tokens)
    safe_groups = _safe_items(groups)

    if not safe_tokens:
        return {
            "rule": "brand_verification",
            "status": "MISSING",
            "expected": None,
            "observed": None,
            "match": False,
            "detected_brand": None,
            "detection_score": 0.0,
            "candidates": [],
            "expected_token_count": 0,
            "matched_token_count": 0,
            "coverage": 0.0,
            "missing_tokens": [],
            "matched_token_bboxes": [],
        }

    image_height = 0
    if safe_tokens:
        max_y = max(t.get("bbox", {}).get("y_max", 0) for t in safe_tokens)
        min_y = min(t.get("bbox", {}).get("y_min", 0) for t in safe_tokens)
        image_height = max_y - min_y

    if not safe_groups:
        safe_groups = safe_tokens

    merged_groups = _merge_adjacent_groups(safe_groups)

    filtered_groups = []
    for g in merged_groups:
        text = (g.get("text") or "").strip()
        if not text:
            continue
        if _is_calendar_noise(text):
            continue
        if _is_warning_text(text):
            continue
        if re.match(r"^[\d\s\|]+$", text):
            continue
        filtered_groups.append(g)

    tokens_by_group: dict[int, list[dict]] = {i: [] for i in range(len(filtered_groups))}
    for t in safe_tokens:
        tx_min = t["bbox"].get("x_min", 0)
        ty_min = t["bbox"].get("y_min", 0)
        for i, g in enumerate(filtered_groups):
            gx_min = g["bbox"].get("x_min", 0)
            gx_max = g["bbox"].get("x_max", 0)
            gy_min = g["bbox"].get("y_min", 0)
            gy_max = g["bbox"].get("y_max", 0)
            if gx_min <= tx_min <= gx_max and gy_min <= ty_min <= gy_max:
                tokens_by_group[i].append(t)
                break

    scored = []
    for i, g in enumerate(filtered_groups):
        score = _candidate_score(g, tokens_by_group, i, image_height or None)
        tokens_in_g = tokens_by_group.get(i, [])
        avg_conf = sum(t.get("confidence", 0.0) for t in tokens_in_g) / max(len(tokens_in_g), 1)
        scored.append((score, avg_conf, g))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return {
            "rule": "brand_verification",
            "status": "MISSING",
            "expected": None,
            "observed": None,
            "match": False,
            "detected_brand": None,
            "detection_score": 0.0,
            "candidates": [],
            "expected_token_count": 0,
            "matched_token_count": 0,
            "coverage": 0.0,
            "missing_tokens": [],
            "matched_token_bboxes": [],
        }

    top_score, top_conf, top_group = scored[0]
    detected = top_group.get("text", "").strip()

    if top_score >= _DETECT_HIGH_THRESHOLD:
        status = "MATCH"
    elif top_score >= _DETECT_FLOOR:
        status = "REVIEW REQUIRED"
    else:
        status = "MISSING"

    return {
        "rule": "brand_verification",
        "status": status,
        "expected": None,
        "observed": detected,
        "match": status == "MATCH",
        "detected_brand": detected,
        "detection_score": round(top_score, 3),
        "candidates": [
            {"text": g.get("text", "").strip(), "score": round(s, 3)}
            for s, _, g in scored[:3]
        ],
        "expected_token_count": 0,
        "matched_token_count": 0,
        "coverage": 0.0,
        "missing_tokens": [],
        "matched_token_bboxes": [],
    }
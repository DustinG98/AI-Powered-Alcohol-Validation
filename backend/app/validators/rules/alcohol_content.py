"""Alcohol content (ABV / proof) extraction and category-specific validation.

The extractor returns a single normalized string per category, e.g.
- beer:    "5.2% ABV"
- wine:    "13.5% ABV"
- spirits: "40% ABV / 80 proof" (only when both are present and consistent)

Category rules (mirrors alcohol_label_verification_spec_v2.md):
- Beer:    ABV only. Proof is invalid -> REVIEW REQUIRED.
- Wine:    ABV only. Proof is invalid -> REVIEW REQUIRED.
- Spirits: Must include ABV and/or proof. If both present, proof == ABV * 2
           (+/- 0.5) or status is REVIEW REQUIRED.

When `expected_abv` is supplied, the extracted ABV is compared to it with a
small tolerance; mismatch -> MISMATCH.
"""

from __future__ import annotations

import re
from typing import Any

from app.validators.rules.common import _full_document_text, _safe_items


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# ABV: "5.2% ABV", "13.5% ALC/VOL", "40% ALC", "5.2% ALC BY VOL"
_ABV_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:alc(?:ohol)?(?:\s+by\s+vol(?:ume)?)?|alc\s*/\s*vol|abv)?",
    re.IGNORECASE,
)

# Proof: "80 PROOF", "PROOF 80", "80° PROOF"
_PROOF_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*°?\s*proof|proof\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Tolerance for proof == ABV * 2 check (per spec: +/- 0.5 proof)
_PROOF_TOLERANCE = 0.5
# Tolerance for expected ABV match
_EXPECTED_ABV_TOLERANCE = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_text(tokens, groups) -> str:
    """Use the same full-document text builder as the other rules so we benefit
    from the calendar-noise filtering.
    """
    full = _full_document_text(tokens, groups)
    if full:
        return full
    source = _safe_items(groups) or _safe_items(tokens)
    if not source:
        return ""
    sorted_source = sorted(source, key=lambda r: r["bbox"].get("y_min", 0))
    return " ".join((r.get("text") or "").strip() for r in sorted_source)


def _extract_abv(text: str) -> tuple[float | None, str | None]:
    """Return (numeric_abv, raw_string) or (None, None) if not found.

    Scans ABV-like matches and filters out values that are clearly not alcohol
    percentages (e.g. "0.5%", "100%+", or implausibly large values).
    """
    best: tuple[float, str] | None = None
    for m in _ABV_RE.finditer(text):
        raw = m.group(0)
        try:
            value = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if value <= 0 or value > 100:
            continue
        # Prefer the match that explicitly carries an ABV/ALC marker; otherwise
        # take the first plausible value.
        has_marker = bool(re.search(r"(abv|alc|alcohol)", raw, re.IGNORECASE))
        if best is None or (has_marker and best is not None):
            best = (value, raw.strip())
            if has_marker:
                break
    if not best:
        return None, None
    return best


def _extract_proof(text: str) -> tuple[float | None, str | None]:
    """Return (numeric_proof, raw_string) or (None, None) if not found."""
    for m in _PROOF_RE.finditer(text):
        raw_str = m.group(0)
        num_str = m.group(1) or m.group(2)
        try:
            value = float(num_str)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value > 200:
            continue
        return value, raw_str.strip()
    return None, None


def _format_display(abv: float | None, proof: float | None) -> str:
    parts: list[str] = []
    if abv is not None:
        parts.append(f"{abv:g}% ABV")
    if proof is not None:
        parts.append(f"{proof:g} proof")
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_alcohol_content(
    category: str = "unknown",
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
    expected_abv: str | None = None,
) -> dict[str, Any]:
    """Extract and validate alcohol content for the given category.

    Returns a rule-result dict with the same shape as the other validators,
    plus a normalized `alcohol_content` string for display.
    """
    text = _build_text(tokens, groups)
    abv_value, _ = _extract_abv(text)
    proof_value, _ = _extract_proof(text)

    display = _format_display(abv_value, proof_value)
    observed = display or None

    # Parse optional expected ABV
    expected_value: float | None = None
    expected_norm: str | None = None
    if expected_abv and expected_abv.strip():
        expected_norm = expected_abv.strip()
        match = re.search(r"\d+(?:\.\d+)?", expected_norm)
        if match:
            try:
                expected_value = float(match.group(0))
            except ValueError:
                expected_value = None

    notes: list[str] = []
    status = "MATCH"

    # Category-specific rules
    if category == "beer" or category == "wine":
        if proof_value is not None:
            status = "REVIEW REQUIRED"
            notes.append(
                f"Proof ({proof_value:g}) present on {category} label; ABV only is required."
            )
        if abv_value is None:
            status = "MISSING" if not notes else status
        elif expected_value is not None:
            if abs(abv_value - expected_value) > _EXPECTED_ABV_TOLERANCE:
                status = "MISMATCH"
                notes.append(
                    f"ABV {abv_value:g}% does not match expected {expected_value:g}%."
                )
    elif category == "spirits":
        if abv_value is None and proof_value is None:
            status = "MISSING"
        elif abv_value is None:
            # Spec line 235-238: "Must include at least one" of ABV/proof.
            # A proof-only spirits label is compliant; flag the missing ABV
            # for human review but do not downgrade the status.
            status = "MATCH"
            notes.append("ABV missing; only proof detected on spirits label.")
            if expected_value is not None:
                notes.append(
                    f"Expected ABV {expected_value:g}% could not be checked (no ABV on label)."
                )
        elif proof_value is None:
            # ABV present but proof missing is allowed per spec ("at least one")
            status = "MATCH"
            if expected_value is not None and abs(abv_value - expected_value) > _EXPECTED_ABV_TOLERANCE:
                status = "MISMATCH"
                notes.append(
                    f"ABV {abv_value:g}% does not match expected {expected_value:g}%."
                )
        else:
            expected_proof = abv_value * 2
            if abs(proof_value - expected_proof) > _PROOF_TOLERANCE:
                status = "REVIEW REQUIRED"
                notes.append(
                    f"Proof {proof_value:g} does not equal ABV x 2 (expected {expected_proof:g})."
                )
            if expected_value is not None and abs(abv_value - expected_value) > _EXPECTED_ABV_TOLERANCE:
                # MISMATCH takes precedence over a proof-validity REVIEW.
                status = "MISMATCH"
                notes.append(
                    f"ABV {abv_value:g}% does not match expected {expected_value:g}%."
                )
    else:  # unknown / fallback
        if abv_value is None and proof_value is None:
            status = "MISSING"
        elif expected_value is not None and abv_value is not None:
            if abs(abv_value - expected_value) > _EXPECTED_ABV_TOLERANCE:
                status = "MISMATCH"
                notes.append(
                    f"ABV {abv_value:g}% does not match expected {expected_value:g}%."
                )

    return {
        "rule": "alcohol_content",
        "status": status,
        "expected": expected_norm,
        "observed": observed,
        "match": status == "MATCH",
        "alcohol_content": display or None,
        "abv": abv_value,
        "proof": proof_value,
        "category": category,
        "notes": notes,
    }

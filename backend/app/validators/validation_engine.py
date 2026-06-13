"""Validation engine that aggregates shared + category-specific rules."""

from __future__ import annotations

from typing import Any

from app.validators.rules.common import validate_government_warning, validate_net_contents
from app.validators.rules.branding import verify_brand, detect_branding
from app.validators.rules.alcohol_content import validate_alcohol_content
from app.validators.rules.beer import validate_beer_class_type
from app.validators.rules.wine import validate_wine_class_type
from app.validators.rules.spirits import validate_spirits_class_type


_CATEGORY_CLASS_TYPE_VALIDATORS = {
    "beer": validate_beer_class_type,
    "wine": validate_wine_class_type,
    "spirits": validate_spirits_class_type,
}


def run_validations(
    category: str,
    tokens: list[dict] | None = None,
    groups: list[dict] | None = None,
    expected_brand: str | None = None,
    expected_abv: str | None = None,
    expected_class_type: str | None = None,
) -> dict:
    """Run all validations applicable to the given category.

    `tokens` is the raw OCR token list; `groups` is the line-grouped output.
    Validators that need token-level precision (e.g. locating the government
    warning) prefer `tokens`; validators that need the reconstructed text
    fall back to `groups`.

    Returns a dict with:
        category, results (list[rule-result]), overall_status.
    """
    results: list[dict[str, Any]] = []
    results.append(validate_government_warning(tokens=tokens or [], groups=groups or []))
    results.append(validate_net_contents(tokens=tokens or [], groups=groups or [], category=category))
    results.append(
        validate_alcohol_content(
            category=category,
            tokens=tokens or [],
            groups=groups or [],
            expected_abv=expected_abv,
        )
    )

    class_type_validator = _CATEGORY_CLASS_TYPE_VALIDATORS.get(category)
    if class_type_validator is not None:
        results.append(
            class_type_validator(
                tokens=tokens or [],
                groups=groups or [],
                expected=expected_class_type,
            )
        )

    if expected_brand and expected_brand.strip():
        results.append(verify_brand(expected_brand, tokens=tokens or [], groups=groups or []))
    else:
        results.append(detect_branding(tokens=tokens or [], groups=groups or [], category=category))

    overall = "PASS"
    for r in results:
        status = r.get("status")
        if status == "MISMATCH":
            overall = "FAIL"
        elif status in ("MISSING", "REVIEW REQUIRED") and overall != "FAIL":
            overall = "REVIEW REQUIRED"

    return {
        "category": category,
        "results": results,
        "overall_status": overall,
    }
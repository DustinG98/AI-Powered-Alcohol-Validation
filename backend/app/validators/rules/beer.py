"""Beer-specific validation rules."""

from __future__ import annotations

from app.validators.rules.class_type import make_validate_class_type


_BEER_STYLES = [
    "india pale ale",
    "ip a",
    "ipa",
    "pale ale",
    "amber ale",
    "brown ale",
    "golden ale",
    "hefeweizen",
    "hefe weizen",
    "witbier",
    "wit bier",
    "lager",
    "pilsner",
    "pilsener",
    "pils",
    "bock",
    "doppelbock",
    "maibock",
    "märzen",
    "marzen",
    "stout",
    "milk stout",
    "oatmeal stout",
    "imperial stout",
    "porter",
    "porter",
    "sour",
    "gose",
    "lambic",
    "kellerbier",
    "kölsch",
    "kolsch",
    "altbier",
    "saison",
    "farmhouse ale",
    "tripel",
    "dubbel",
    "quadrupel",
    "belgian ale",
    "saison",
    "barleywine",
    "barley wine",
    "session ipa",
    "hazy ipa",
    "west coast ipa",
    "new england ipa",
    "double ipa",
    "imperial ipa",
    "black ipa",
    "radler",
    "shandy",
    "malt liquor",
    "non alcoholic",
    "non-alcoholic",
]


validate_beer_class_type = make_validate_class_type(
    lexicon=_BEER_STYLES,
    label="beer style",
)

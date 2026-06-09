# AI-Powered-Alcohol-Validation

Validates alcohol beverage labels for compliance with TTB requirements using OCR and rule-based validation.

## OCR

**Engine:** PaddleOCR (PP-OCRv5)

**Token Combining:** OCR tokens are grouped into line-level groups using spatial clustering:
1. Tokens are clustered into vertical columns based on x-coordinate proximity
2. Within each column, tokens are grouped into lines by y-center clustering
3. Tokens within a line are sorted left-to-right and merged into a single text group with a combined bounding box

This ratio-based spatial approach allows combining fragmented OCR detections while respecting the natural reading order of the label.

**Image Preprocessing:**
- Upscales images to 2400px on the longest edge before OCR
- Applies grayscale conversion + CLAHE enhancement
- Adds sharpening filter to improve small/dense text recognition

## Government Warning

**Method:** Fuzzy text match using anchor phrase detection

The TTB-required government warning contains two legally distinct clauses:
1. Pregnancy/birth defects warning (Surgeon General)
2. Impairment warning (driving/operating machinery)

**Validation Strategy:**
- **Semantic path:** Concatenates all OCR tokens into a single document string, then searches for the "GOVERNMENT WARNING" header and extracts the body. Anchor phrases from each clause are matched against the full text to detect presence.
- **Spatial fallback:** If the semantic path fails to locate the header, falls back to column-isolation based extraction using bounding box positioning.

**Scoring:** Uses LCS-based fuzzy token matching with vocabulary expansion. Tokens are matched with tolerance for minor OCR errors (1 character difference for short tokens, prefix matching for longer ones).

**Limitation:** Labels may false-pass if OCR drops critical words from the warning body, since the fuzzy matching tolerates missing tokens. This trade-off was accepted because improving OCR accuracy would significantly slow processing beyond the 5-second target.

## Net Contents

**Method:** Regex pattern matching for volume/weight patterns

**Patterns Matched:**
- Direct volume: `750 ml`, `1.75 L`, `12 fl oz`
- "Net wt/contents" prefix: `Net750 ml`, `Net wt 12 oz`
- Various unit formats: `ml`, `milliliters`, `L`, `liters`, `oz`, `fl oz`, `fluid ounces`, `pint`, `pints`, `pt`, `gal`, `gallons`, `qt`, `quarts`, `g`, `grams`, `kg`

**Category-Specific Units:**
| Category | Valid Units |
|----------|-------------|
| Beer | pint, fl oz, oz, L, ml, gal, qt |
| Wine | ml, L, fl oz, oz, gal |
| Spirits | ml, L, fl oz, oz, gal, pint |

## Categorization

**Method:** Keyword scoring across three categories

**Keywords by Category:**

| Spirits | Beer | Wine |
|---------|------|------|
| whisky, whiskey | beer | wine |
| rum | ale | vineyard |
| vodka | lager | vintage |
| gin | stout | winery |
| brandy | porter | champagne |
| tequila | brewery | sparkling |
| mezcal | brewing | port |
| bourbon | brew | sherry |
| rye | ipa | moscato |
| scotch | pilsner | bordeaux |
| liqueur | bitter | burgundy |
| cognac | draught/draft | chardonnay |
| arak | keg | pinot |
| schnapps | bottled | merlot |
| aquavit | barley | cabernet |
| grappa | hops | sauvignon |
| pisco | fermented | riesling |
| eaux | IPA | zinfandel |
| distilled | (brand names) | syrah |
| distillery | | rose |
| straight | | |

The category with the highest keyword match score is selected. If no keywords match, the category is "unknown".

**Limitation:** Category detection relies on keyword presence. New brands or international terms may not be recognized and would require expanding the keyword lists.

## Branding

**Method:** Two-mode brand handling — verification (expected brand supplied) and detection (no expected brand supplied). The API consumer chooses which path to take by including or omitting `expected_brand` in the per-image metadata sent to `POST /analyze` (`backend/app/api/analyze.py:36`).

### 1. Verify Mode — expected brand supplied

When the caller passes an `expected_brand` string (e.g. `"Example Brewing Co."`), the engine tokenizes it and tries to locate every token in the OCR output (`verify_brand` in `backend/app/validators/rules/branding.py`).

- **Tokenization:** Brand is split into lowercase tokens; punctuation stripped.
- **Matching strategies** (applied in order, per expected token):
  1. **Single-token fuzzy / prefix match** — uses the common `_fuzzy_token_match` helper (equal, prefix ≥ 3 chars, or 1-edit Levenshtein).
  2. **Substring match** — expected token appears inside a punctuation-stripped OCR token. This is what lets `"co"` match inside `"EXAMPLEBREWINGCO."` and also lets `"brewing"` and `"example"` all claim the same OCR token.
  3. **Adjacent-token concatenation (2 or 3 tokens)** — joins consecutive OCR tokens and re-runs the match. This recovers OCR splits like `"BRE" + "WERY" = "brewery"`. Index ranges already consumed by another concat match are tracked in `used_ranges` to prevent double-counting.
- **Result:** `status` is `MATCH` (100% coverage), `REVIEW REQUIRED` (partial), or `MISSING` (no coverage). The response includes `expected`, `observed` (joined matched OCR texts), `coverage`, `missing_tokens`, and `matched_token_bboxes` for downstream highlighting.

### 2. Detect Mode — no expected brand supplied

When `expected_brand` is omitted/empty, the engine runs `detect_branding` to guess the most likely brand from the label itself (`backend/app/validators/rules/branding.py`).

- **Group merging:** Adjacent groups whose vertical gap is ≤ 60% of the median group height *and* whose x-ranges overlap are merged — this reassembles lines that the OCR split into multiple groups (e.g. `"EXAMPLE"` and `"BREWINGCO."` become one candidate).
- **Filtering:** Calendar noise, government-warning text (matched against `_WARNING_LEAK_PATTERNS`), and pure-digit/pipe groups are dropped so they can't be picked as the brand.
- **Token-to-group assignment:** Each OCR token is assigned to the first group whose bbox contains it (`tokens_by_group`).
- **Candidate scoring:** Each candidate group is scored on four signals:
  - **Position (35%)** — top of the image is brand territory (`rel_y < 0.15` → 1.0, fading to 0 below the midline).
  - **Relative size (25%)** — median token height inside the group vs. overall median, capped at 2.0×.
  - **Lexicon (25%)** — presence of brand-y words (`brewery`, `distillery`, `winery`, `co`, `estate`, `cellars`, `spirits`, `cidery`, `meadery`, `vintners`, …), 0.25 per hit, capped at 1.0.
  - **OCR confidence (15%)** — mean token confidence inside the group.
- **Result:** Top-scoring group becomes `detected_brand`. `MATCH` (score ≥ 0.50), `REVIEW REQUIRED` (≥ 0.20), or `MISSING`. The top-3 candidates are returned for debugging.

### OCR Quality Fixes Integrated

Label photos in the wild produce noisy OCR — small fonts, curved/decorative type, glare, and inconsistent tokenization. The branding pipeline incorporates several fixes for these issues:

- **Substring matching inside concatenated tokens** (`_token_matches_in_observed_text`) — handles the very common case where a brand prints without spaces (`EXAMPLEBREWINGCO.`), letting the engine claim multiple expected tokens off a single OCR string.
- **Adjacent-token concatenation for OCR splits** (`_find_expected_matches`, n=2 and n=3) — recovers words broken across multiple OCR tokens (`"BRE" + "WERY"`) with a `used_ranges` guard so a single OCR token can't satisfy the same expected word twice.
- **Vertical/horizontal group merging** (`_merge_adjacent_groups`) — re-joins line fragments that came back as separate OCR groups but are spatially one line (gap ≤ 0.6 × median height, x-overlap required).
- **Warning-text exclusion** (`_WARNING_LEAK_PATTERNS` + `_is_warning_text`) — strips out the multi-line government warning, which otherwise dominates the top of the label and would otherwise win the position/size scores and be mis-detected as the brand.
- **Calendar / digit / pipe filtering** — drops date codes, batch numbers, and bar-code artifacts before scoring so they can't be picked as the brand.
- **Fuzzy match with 1-edit tolerance and prefix matching** (`_fuzzy_token_match` in `common.py`) — tolerates single-character OCR errors and small-font glyph confusion.
- **Per-token confidence weighting** — candidates built from low-confidence OCR tokens are penalized via the 15% confidence term, preventing the detector from committing to a garbled top-of-label guess.

**Limitation:** Brand detection is heuristic — the position/size/lexicon blend works well for typical U.S. beer/wine/spirits labels but can be fooled by labels where the brand sits mid-label, uses only stylized script (low OCR confidence), or shares visual weight with mandatory text. The detect path is best treated as a `REVIEW REQUIRED` suggestion rather than ground truth; verify mode is the authoritative path whenever an expected brand is known.

## Performance

**Current Benchmark:** ~2.01s average per image on local Docker host (Ryzen 7 5800X)

**Target:** < 5 seconds per label

OCR preprocessing (upscaling, CLAHE, sharpening) trades some accuracy for speed, which is acceptable given the performance requirement.

**GPU Acceleration:** Using a GPU-enabled PaddleOCR model would enable both faster processing and improved accuracy. The current CPU-only setup achieves good speed but could deliver better OCR quality with a GPU model without sacrificing the 5-second target.

## Limitations Summary

| Component | Limitation |
|-----------|------------|
| OCR | Using faster PP-OCRv5_mobile model; better accuracy available with PP-OCRv5_server but slower |
| Government Warning | May false-pass if OCR drops critical words; fuzzy matching tolerates gaps |
| Categorization | Keyword-based; requires expansion for new brands/terms |
| Branding | Heuristic detector (position/size/lexicon blend) can be fooled by stylized script, mid-label brands, or labels where mandatory text visually dominates — use verify mode whenever the expected brand is known |
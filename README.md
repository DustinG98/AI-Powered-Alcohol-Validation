# AI-Powered-Alcohol-Validation

Validates alcohol beverage labels for compliance with TTB requirements using OCR and rule-based validation.

## Quick Start

### Local development (HTTP, no cert, no domain)

```bash
# Use the pre-baked .env.local that has TLS off and ALLOWED_ORIGINS set
# to http://localhost. (Or copy .env.example -> .env and blank out the
# CERTBOT_* vars + set ALLOWED_ORIGINS=http://localhost.)
cp .env.local .env

# Bring up backend + nginx only (certbot is not started).
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build

# Open http://localhost
```

The local override (`docker-compose.local.yml`) mounts a sibling `nginx/nginx.local.conf` that listens on port 80 only, swaps the HTTPS server block for plain HTTP, and starts the frontend service with a `profiles: ["never"]` no-op for certbot. The backend container, the Vite build, and the `/api/*` reverse proxy are identical to production — only TLS is missing.

### Production (HTTPS via Let's Encrypt)

```bash
# 1. Copy the env template and edit
cp .env.example .env
# In .env, set:
#   CERTBOT_DOMAIN   = your real hostname (A record must point at this VPS)
#   CERTBOT_EMAIL    = an email for Let's Encrypt notices
#   ALLOWED_ORIGINS  = https://${CERTBOT_DOMAIN}
# Leave CERTBOT_STAGING=false for production; set true to test the
# http-01 flow without hitting Let's Encrypt rate limits.

# 2. Build and start the full stack (backend + nginx + certbot)
docker compose up --build -d

# 3. Wait ~30s for certbot to obtain the cert on its first run, then:
docker compose restart frontend

# 4. Open the app
# Web app:  https://your-domain.example
# API docs: https://your-domain.example/docs
```

The single-VPS layout:

```
   internet  ──►  host:80   ──►  nginx (frontend container)  ──►  ACME challenge (.well-known/)
   internet  ──►  host:443  ──►  nginx (frontend container)
                                    ├── /             ──► static Vite bundle
                                    ├── /api/*        ──► FastAPI (backend container, internal only)
                                    └── /docs, /redoc ──► FastAPI (Swagger UI)

   certbot container  ──►  /var/www/certbot  (shared with nginx)  +  /etc/letsencrypt
```

The backend listens on port 8000 but is **only** reachable from the nginx container via the internal `app-net` Docker network — it's not published to the host, so it's not exposed to the public internet. The certbot container shares two volumes with nginx: `certbot-www` (the webroot for the http-01 challenge) and `certbot-certs` (the issued certificates that nginx reads).

### TLS / certificate renewal

- **First run:** certbot issues a certificate, then exits to `sleep infinity` so the container stays up. After ~30 s, `docker compose restart frontend` picks up the new cert and the HTTPS listener comes alive.
- **Renewal:** every time the certbot container starts (e.g. after a `docker compose up -d` or a manual `docker compose restart certbot`), it runs `certbot renew` and reloads. If the cert is more than 60 days from expiry, the renew is a no-op.
- **Staging/testing:** set `CERTBOT_STAGING=true` in `.env` to get a fake Let's Encrypt cert. Useful when verifying the flow without burning the production rate limit (5 certs / 7 days per domain).
- **Custom certs:** if you have your own cert + key (e.g. wildcard from a corporate CA), skip the certbot service and mount your files into the frontend container at `/etc/letsencrypt/live/${CERTBOT_DOMAIN}/fullchain.pem` and `privkey.pem`.

### Configuration

All runtime configuration is driven by the root `.env` file (loaded by `docker compose`). See `.env.example` for the full list. Key variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `ALLOWED_ORIGINS` | `http://localhost,https://your-domain.example` | Comma-separated CORS allow-list. Replace the placeholder with your real hostname before going live. |
| `CERTBOT_DOMAIN` | `your-domain.example` | Hostname for the Let's Encrypt certificate. Must resolve to this VPS before the stack starts. |
| `CERTBOT_EMAIL` | `admin@your-domain.example` | Email for Let's Encrypt expiry notices. |
| `CERTBOT_STAGING` | `false` | `true` to issue a staging cert (testing only). |
| `UVICORN_WORKERS` | `1` | Number of uvicorn worker processes. Each owns its own PaddleOCR engine. See **Performance → Batch Throughput** for why threads are unsafe. |
| `UVICORN_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error`. |
| `MAX_UPLOAD_SIZE_MB` | `15` | Per-image size cap. Larger files are rejected with 413. |
| `MAX_BATCH_SIZE` | `25` | Per-request image count cap. Larger batches are rejected with 400. |
| `VITE_API_BASE_URL` | `/api` | Front-end → back-end base URL. Defaults to same-origin (`/api`) so nginx can reverse-proxy it. |

`docker compose` reads the root `.env` automatically. Real `.env` files are gitignored; only `.env.example` is committed.

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

## Alcohol Content

**Method:** Regex extraction of ABV (`5.2% ABV`, `13.5% ALC/VOL`, `40% ALC`, …) and proof (`80 PROOF`, `PROOF 80`, `80° PROOF`) tokens from the full OCR document text (`backend/app/validators/rules/alcohol_content.py`).

**Category-Specific Rules (mirrors `alcohol_label_verification_spec_v2.md`):**

| Category | Rule | Failure Mode |
|----------|------|--------------|
| Beer | ABV only. Proof is invalid. | `REVIEW REQUIRED` if proof present; `MISSING` if no ABV. |
| Wine | ABV only. Proof is invalid. | `REVIEW REQUIRED` if proof present; `MISSING` if no ABV. |
| Spirits | Must include ABV and/or proof. When both are present, `proof == ABV × 2` (±0.5). | `REVIEW REQUIRED` on proof mismatch or if only proof is detected. `MISSING` if neither is present. |
| Unknown | Extracted only; no category rule applied. | `MISSING` if neither is present. |

**Output:**
- A `rule` result (`alcohol_content`) is appended to `validation.results` with `status`, `expected`, `observed`, `match`, `alcohol_content` (normalized display string, e.g. `"40% ABV / 80 proof"`), `abv` (float or null), `proof` (float or null), and `notes` (human-readable reasons when `REVIEW REQUIRED` / `MISMATCH`).
- The engine always returns the extracted value even when the status is not `MATCH`, so the front-end can show "Detected: …" alongside the badge.

**Optional `expected_abv`:** The API consumer may supply an expected ABV per image in the `metadata_json` form field (e.g. `{"filename": "label.jpg", "expected_brand": "Stone Throw", "expected_abv": "6.2"}`). The validator compares the extracted ABV against the expected value with a ±0.5 tolerance; mismatch → `MISMATCH` (overall `FAIL`). Proof consistency and category-specific rules still take precedence.

**Limitation:** The extractor is regex-based on OCR text and assumes the ABV is printed with a `%` symbol. Labels that use only the word "Alcohol" or display ABV on a separate colored band may be missed.

## Class / Type Designation

**Method:** Lexicon-based detection over the full OCR document text, with one lexicon per category (`backend/app/validators/rules/beer.py`, `wine.py`, `spirits.py`, all built by `app/validators/rules/class_type.py`).

| Category | Field | Example values |
|----------|-------|----------------|
| Beer | Style | IPA, Pale Ale, Lager, Pilsner, Stout, Porter, Saison, Wheat, Hefeweizen, Kölsch, Bock, Gose, Lambic, … |
| Wine | Varietal | Cabernet Sauvignon, Pinot Noir, Chardonnay, Merlot, Sauvignon Blanc, Riesling, Syrah, Malbec, Zinfandel, Champagne, Prosecco, Rosé, … |
| Spirits | Type | Bourbon Whiskey, Rye Whiskey, Scotch Whisky, Vodka, Rum, Gin, Tequila (Blanco/Reposado/Añejo), Mezcal, Brandy, Cognac, … |

**How it works:**
- The shared `class_type.py` module slices the full document text into 1–4 word phrases and matches them against a per-category lexicon.
- Lexicon entries are matched both verbatim and via substring variants (e.g. an entry of `"kentucky straight bourbon whiskey"` also matches a label that just says `"bourbon whiskey"`), so common shorthand still scores.
- A fuzzy word-level match is applied as a fallback (single-character edit / prefix), tolerating minor OCR errors.

**Outcomes (no expected value supplied):**
- `MATCH` — a lexicon entry was detected on the label.
- `REVIEW REQUIRED` — no recognized entry was found. Per spec, missing style / type is a review item; unknown varietals also fall into this bucket.

**Outcomes (with `expected_class_type` supplied):**
- `MATCH` — all expected tokens appear in the OCR text.
- `REVIEW REQUIRED` — partial match (some expected tokens found, some missing).
- `MISSING` — no expected tokens found.

**Optional `expected_class_type`:** Pass an expected class/type per image in the `metadata_json` form field (e.g. `{"filename": "label.jpg", "expected_class_type": "IPA"}`). The validator checks expected-token coverage against the full document text.

**Limitation:** Detection is lexicon-bound; new styles, proprietary designations, or international terms may not be recognized. The detector does not currently distinguish between "label does not declare a class/type" and "label declares something not in the lexicon" — both surface as `REVIEW REQUIRED`.

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

**Current Benchmark:** ~3.0s average per image on local Docker host (Ryzen 7 5800X, CPU-only PaddleOCR, single uvicorn worker)

**Target:** < 5 seconds per label

OCR preprocessing (upscaling, CLAHE, sharpening) trades some accuracy for speed, which is acceptable given the performance requirement.

**GPU Acceleration:** Using a GPU-enabled PaddleOCR model would enable both faster processing and improved accuracy. The current CPU-only setup achieves good speed but could deliver better OCR quality with a GPU model without sacrificing the 5-second target.

### Batch Throughput

The endpoint processes images **serially in a single uvicorn worker** (`POST /analyze` in `backend/app/api/analyze.py`). PaddleOCR's PaddlePaddle backend holds shared native state (the inference session and an internal thread pool) that is not safe to call concurrently from multiple Python threads — concurrent invocations from the same process either serialize on internal locks (defeating the purpose) or corrupt shared state. A comment at the call site explains this in the code.

For a single image this comfortably meets the < 5s target. For the 200–300-image import batches that Janet's office handles, scale out the process and let the workers share the load.

**Future: parallel processing.** Two safe paths, in order of preference:

1. **Multiple uvicorn workers, one PaddleOCR engine per worker.** Each worker owns its own OCR instance with no shared state, so they run in parallel trivially. Recommended deployment:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
   Behind a reverse proxy (`nginx` or the platform's load balancer), each request is routed to one worker and the engine is fully isolated. Memory cost is ~1 model load per worker (~1–2 GB each for the mobile PP-OCRv5 stack).

2. **ProcessPoolExecutor with a fresh engine per worker process.** When running as a single uvicorn worker but you still want intra-request parallelism (e.g. a frontend that already pins to one backend instance), dispatch each image to a worker process. Each subprocess imports its own `PaddleOCR` instance, so shared-state races are eliminated by process isolation. Higher per-image startup cost than option 1, so it's only worth it if you must stay single-process.

Do **not** parallelize via `asyncio.to_thread` or `ThreadPoolExecutor` within a single process — the underlying C++ inference session is not re-entrant and will either deadlock on its own locks or produce wrong results.

## Testing

**This prototype ships without an automated test suite**, a deliberate trade-off driven by the time-constrained nature of the take-home. Every validator, extractor, and rule path was exercised against real label images during development, but the assertions live in manual reproduction rather than in CI-runnable code. The plan below describes what a real test suite would look like; implementing it is the first task for anyone turning this prototype into a maintained codebase.

### What unit tests we would add

The validation engine is pure-Python and trivially testable, so the highest-ROI tests are validator-level and don't need a running OCR engine.

**`backend/tests/test_alcohol_content.py`** — covers `app/validators/rules/alcohol_content.py`
- Beer with `5.2% ABV` → `MATCH`
- Beer with `5.2% ABV` and `80 PROOF` → `REVIEW REQUIRED` (proof invalid on beer per spec)
- Wine with `13.5% ALC/VOL` → `MATCH`
- Spirits with `40% ABV` and `80 PROOF` → `MATCH` (proof ≈ ABV × 2)
- Spirits with `40% ABV` and `90 PROOF` → `REVIEW REQUIRED` (proof mismatch > 0.5)
- Spirits with only `80 PROOF` (no ABV) → `MATCH` per spec line 235-238
- Spirits with no ABV and no proof → `MISSING`
- `expected_abv` mismatch by > 0.5 → `MISMATCH`

**`backend/tests/test_government_warning.py`** — covers the casing + clause-anchor logic in `common.py`
- Exact spec text → `MATCH`
- Title-case header `Government Warning:` (Jenny's "rejected" case) → `MISMATCH`
- Missing clause 1 (no pregnancy/birth-defects wording) → `REVIEW REQUIRED`
- Garbled tail (only the head clause is intact) → `MATCH` (soft threshold)
- Warning entirely missing → `MISSING`

**`backend/tests/test_net_contents.py`**
- `750 mL` on a wine label → `MATCH`
- `1 pint` on a beer label → `MATCH`
- `750 mL` on a beer label with a `pints` unit → `MISMATCH` (category-specific unit set)
- No net contents → `MISSING`

**`backend/tests/test_class_type.py`** — covers `class_type.py` plus the three lexicons
- Beer label with `INDIA PALE ALE` → detected = `india pale ale`, status `MATCH`
- Beer label with no style designation → `REVIEW REQUIRED` per spec line 135
- Wine label with `CABERNET SAUVIGNON` → `MATCH`
- Wine label with only `WINE` (no varietal) → `REVIEW REQUIRED` per spec line 192-194
- Spirits label with `KENTUCKY STRAIGHT BOURBON WHISKEY` → `MATCH`
- Spirits label with only `SPIRITS` (no concrete type) → `REVIEW REQUIRED` per spec line 267
- `verify_expected_class_type("IPA", ...)` against OCR `india pale ale` — currently `MISSING`; document as a known limitation (no abbreviation expansion) and pin the behavior

**`backend/tests/test_branding.py`** — covers `branding.py`
- Verify mode: `expected="Example Brewing Co."`, OCR tokens include `EXAMPLE`, `BREWINGCO.` → `MATCH` (substring + concat paths exercised)
- Verify mode: `expected="Stone's Throw"`, OCR `STONE'S THROW` (Dave's case) → `MATCH` (fuzzy + apostrophe handling)
- Detect mode: top-of-image group with lexicon hits → `MATCH`
- Detect mode: warning text excluded from brand candidates

**`backend/tests/test_categorize.py`** — covers `categorize.py`
- `KENTUCKY BOURBON WHISKEY` → `spirits`
- `CABERNET SAUVIGNON 2019` → `wine`
- `INDIA PALE ALE` → `beer`
- No keywords → `unknown`

**`backend/tests/test_validation_engine.py`** — covers `validation_engine.py`
- `overall_status` aggregation: a `MISMATCH` result anywhere in the list must surface as `FAIL`, not be masked by an earlier `REVIEW REQUIRED` (regression test for the #4 fix)
- Unknown category: class/type validators are not run

### Recommended tooling

- **`pytest`** as the test runner, with **`pytest-asyncio`** for the FastAPI endpoint tests below.
- **`pytest-cov`** for coverage reporting. Target: 80%+ on `app/validators/` (the pure logic) before considering the suite adequate.
- **`httpx`** + **`pytest-asyncio`** for an integration test of `POST /analyze` with mocked OCR (patch `ocr_image_file` to return canned tokens).
- **`moto`** or **`responses`** if the project ever adds cloud calls (currently none).
- **Frontend:** **`vitest`** + **`@testing-library/react`** for the React components. The two highest-ROI tests are `statusKind` (pure function) and the result-correlation logic (the `#15` `image_id` matching fix). Pin both with regression tests.

## Limitations Summary

| Component | Limitation |
|-----------|------------|
| OCR | Using faster PP-OCRv5_mobile model; better accuracy available with PP-OCRv5_server but slower |
| Government Warning | May false-pass if OCR drops critical words; fuzzy matching tolerates gaps |
| Categorization | Keyword-based; requires expansion for new brands/terms |
| Alcohol Content | Regex-based; assumes ABV is printed with `%`. Proof consistency check assumes US-style proof (ABV × 2). |
| Class / Type | Lexicon-bound; new styles, proprietary designations, or international terms may not be recognized. Can't distinguish "not declared" from "declared but unknown". |
| Branding | Heuristic detector (position/size/lexicon blend) can be fooled by stylized script, mid-label brands, or labels where mandatory text visually dominates — use verify mode whenever the expected brand is known |

## API

`POST /analyze` accepts a multipart form with:

- `images`: one or more image files (JPG/JPEG/PNG)
- `metadata_json`: JSON array, one entry per image:
  ```json
  [
    {
      "filename": "label.jpg",
      "expected_brand": "Stone Throw",
      "expected_abv": "6.2",
      "expected_class_type": "IPA"
    }
  ]
  ```
  `expected_brand`, `expected_abv`, and `expected_class_type` are all optional.
  - `expected_abv`: extracted ABV must match within ±0.5 percentage points.
  - `expected_class_type`: every expected token must appear in the OCR text for `MATCH`.
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
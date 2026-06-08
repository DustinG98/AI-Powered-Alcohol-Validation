# AI-Powered Alcohol Label Verification App

## Overview

This application assists TTB compliance agents in reviewing alcohol beverage labels using local OCR (PaddleOCR) and deterministic validation rules.

The system supports **multiple alcohol categories**:
- Beer
- Wine
- Distilled Spirits

Each category shares common validation logic but also has category-specific compliance rules.

---

# Goals

- Reduce manual compliance verification workload
- Support beer, wine, and distilled spirits labeling rules
- Process single images and batch uploads
- Return results in under 5 seconds per image
- Maintain explainability and auditability
- Operate fully offline (no external AI APIs)

---

# Alcohol Category Support

## Supported Product Types

The system must classify each label into one of:

- Beer
- Wine
- Distilled Spirits
- Unknown (fallback / review required)

---

## Category Classification

Classification is determined via:

- OCR keyword detection
- ABV range heuristics
- Label language patterns (e.g., "brewed", "distilled", "vintage")
- Optional manual override from user input

---

# Shared Core Requirements (All Categories)

## Image Upload

- JPG, JPEG, PNG supported
- Single + batch upload supported
- Batch size recommended: 1–25 images

---

## OCR Extraction Fields (Base Schema)

All categories must attempt extraction of:

- Brand name
- Alcohol content (ABV / proof where applicable)
- Net contents
- Producer / bottler / importer
- Country of origin (if present)
- Government warning statement (where applicable)

---

## Bounding Boxes (Required)

Each OCR token must include:

- Text
- Normalized text
- Confidence score
- Bounding box coordinates

---

## Standard Validation Outcomes

- MATCH
- MISMATCH
- MISSING
- REVIEW REQUIRED

---

## Government Warning (Shared Rule)

- Must exist where legally required
- Must match required regulatory wording
- Must be deterministic validation (no fuzzy matching)

---

# CATEGORY-SPECIFIC REQUIREMENTS

---

# 1. BEER LABEL VALIDATION

## Key Characteristics

Beer labels typically include:
- Brand name
- Beer style (IPA, Lager, Stout, etc.)
- ABV only (no proof)
- Brewer name and location
- Net contents (fluid ounces or liters)
- No distilled proof system

---

## Beer-Specific Rules

### Alcohol Content

- Must be expressed as **ABV only**
- Proof values are invalid for beer and should trigger REVIEW

---

### Style / Class Designation

Beer requires validation of:
- Style presence (IPA, Lager, Ale, Stout, Pilsner, etc.)
- OR generic classification (“Beer”)

Missing style → REVIEW REQUIRED

---

### Government Warning

- Required on most commercial beer labels
- Must match standard TTB warning text

---

## Beer-Specific Failure Cases

- Proof listed instead of ABV
- Missing style classification
- Missing brewer identity
- Missing government warning

---

# 2. WINE LABEL VALIDATION

## Key Characteristics

Wine labels typically include:
- Brand name / producer
- Vintage year (optional but common)
- Appellation / AVA / region
- Varietal (Cabernet Sauvignon, Chardonnay, etc.)
- Alcohol content (ABV only)
- Bottler / importer
- Net contents

---

## Wine-Specific Rules

### Vintage Year

- Optional but must be valid 4-digit year if present
- Future years → FAIL
- Missing vintage → allowed but may reduce confidence

---

### Appellation / Origin

Wine often includes:
- AVA (American Viticultural Area)
- Country + region combination

Mismatch between declared origin and label → REVIEW REQUIRED

---

### Varietal Validation

If present:
- Must be valid grape varietal name
- Unknown varietals → REVIEW REQUIRED

---

### Government Warning

- Required on wine labels
- Must match exact wording requirement

---

## Wine-Specific Failure Cases

- Invalid vintage year
- Missing origin information when required
- Unknown varietal terms
- Incorrect appellation labeling

---

# 3. DISTILLED SPIRITS VALIDATION

## Key Characteristics

Distilled spirits include:
- Whiskey
- Vodka
- Rum
- Tequila
- Gin
- Brandy

They are the only category that uses:
- ABV AND proof

---

## Spirits-Specific Rules

### Alcohol Content

Must include at least one:

- ABV (%)
- Proof

### Validation Logic

- Proof must equal ABV × 2 (within tolerance ±0.5)
- If mismatch → REVIEW REQUIRED

---

### Statement Requirements

Must include:
- Type designation (e.g., Whiskey, Vodka)
- Distillation source may be required depending on type

---

### Age Statements (if present)

- Must be numeric or valid descriptor
- Example: "Aged 8 Years"
- Invalid formats → REVIEW REQUIRED

---

## Spirits-Specific Failure Cases

- Missing proof where expected
- ABV/proof mismatch
- Missing type designation
- Invalid age statement format

---

# BATCH PROCESSING

## Behavior

- Each image processed independently
- Each image assigned `image_id`
- Category classification performed per image
- Results aggregated into batch response

---

## Batch Response Example

```json
{
  "batch_id": "xyz123",
  "results": [
    {
      "image_id": "img_1",
      "category": "beer",
      "status": "PASS"
    },
    {
      "image_id": "img_2",
      "category": "spirits",
      "status": "REVIEW REQUIRED"
    }
  ]
}
```

---

# OCR OUTPUT STRUCTURE

Each detected token includes:

```json
{
  "text": "STONE'S THROW",
  "normalized_text": "stones throw",
  "confidence": 0.98,
  "bbox": {
    "x_min": 120,
    "y_min": 340,
    "x_max": 420,
    "y_max": 390
  }
}
```

---

# ERROR HANDLING

- Blurry images
- Rotated images
- Low contrast images
- Missing fields
- Category misclassification
- OCR failure per region

Batch failures do NOT stop processing.

---

# PERFORMANCE

- Target: < 5 seconds per image
- Batch scaling: linear per image
- Future: parallel + async queue processing

---

# ARCHITECTURE

## Frontend (React + Vite)
- Upload single or batch images
- Display category per image
- Show validation results
- Render OCR bounding boxes

## Backend (FastAPI)
- Handle uploads
- Classify product type
- Run OCR pipeline
- Execute category-specific validation

## OCR Engine (PaddleOCR)
- Text detection
- Bounding box extraction
- Confidence scoring

## Validation Engine
- Shared rules engine
- Category-specific rule modules:
  - beer_rules.py
  - wine_rules.py
  - spirits_rules.py

---

# HIGH LEVEL FLOW

Upload → OCR → Category Detection → Validation Rules → Aggregation → Response

---

# FUTURE ENHANCEMENTS

- ML-based category classifier
- Regulatory rule versioning (TTB updates)
- Confidence scoring per field
- Human-in-the-loop review system
- Export to PDF/CSV audit reports
- OpenCV preprocessing pipeline
- Multi-label document support

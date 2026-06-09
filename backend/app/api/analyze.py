import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List

from app.services.ocr_service import OCRUnavailable, group_tokens, ocr_image_file
from app.validators.validation_engine import run_validations
from app.validators.rules.categorize import identify_category

router = APIRouter()


@router.post("/analyze")
async def analyze(
    images: List[UploadFile] = File(...),
    metadata_json: str = Form(default="[]"),
):
    try:
        metadata_list = json.loads(metadata_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata_json must be valid JSON")

    if not isinstance(metadata_list, list):
        raise HTTPException(status_code=400, detail="metadata_json must be a JSON array")

    metadata_by_filename = {entry.get("filename", ""): entry for entry in metadata_list}

    results = []
    for idx, image in enumerate(images, start=1):
        try:
            contents = await image.read()
            tokens = ocr_image_file(contents)
            groups = group_tokens(tokens)
            category = identify_category(tokens=tokens, groups=groups)

            entry = metadata_by_filename.get(image.filename, {})
            expected_brand = entry.get("expected_brand", "") or ""

            validation = run_validations(
                category=category,
                tokens=tokens,
                groups=groups,
                expected_brand=expected_brand,
            )
            results.append(
                {
                    "image_id": f"img_{idx}",
                    "filename": image.filename,
                    "metadata": entry,
                    "expected_brand_supplied": bool(expected_brand.strip()),
                    "token_count": len(tokens),
                    "tokens": tokens,
                    "groups": groups,
                    "category": validation["category"],
                    "validation": validation,
                }
            )
        except OCRUnavailable as exc:
            results.append(
                {
                    "image_id": f"img_{idx}",
                    "filename": image.filename,
                    "error": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "image_id": f"img_{idx}",
                    "filename": image.filename,
                    "error": f"OCR failed: {exc}",
                }
            )

    return {
        "status": "Success",
        "image_count": len(images),
        "results": results,
    }
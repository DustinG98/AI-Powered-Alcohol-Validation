import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List

from app.config import MAX_BATCH_SIZE, MAX_UPLOAD_BYTES
from app.services.ocr_service import OCRUnavailable, group_tokens, ocr_image_file
from app.validators.validation_engine import run_validations
from app.validators.rules.categorize import identify_category

router = APIRouter()


@router.post("/analyze")
async def analyze(
    images: List[UploadFile] = File(...),
    metadata_json: str = Form(default="[]"),
):
    # Enforce batch count limit before reading anything.
    if len(images) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(images)} exceeds MAX_BATCH_SIZE={MAX_BATCH_SIZE}.",
        )

    try:
        metadata_list = json.loads(metadata_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata_json must be valid JSON")

    if not isinstance(metadata_list, list):
        raise HTTPException(status_code=400, detail="metadata_json must be a JSON array")

    metadata_by_filename = {
        entry.get("filename", ""): entry
        for entry in metadata_list
        if isinstance(entry, dict)
    }

    # Process serially. PaddleOCR's PaddlePaddle backend holds shared native
    # state (the inference session and internal thread pool) that is not
    # safe to call concurrently from multiple Python threads — concurrent
    # invocations either serialize on internal locks (defeating the
    # purpose) or corrupt shared state. To run the batch in parallel
    # safely, scale out by running multiple uvicorn workers (e.g.
    # `uvicorn app.main:app --workers N`) or a process pool with a fresh
    # PaddleOCR engine per worker.
    results = []
    for idx, image in enumerate(images, start=1):
        try:
            contents = await image.read()
            if len(contents) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Image '{image.filename}' is "
                        f"{len(contents) / (1024 * 1024):.1f} MB, exceeds "
                        f"MAX_UPLOAD_SIZE_MB={MAX_UPLOAD_BYTES // (1024 * 1024)}."
                    ),
                )
            tokens = ocr_image_file(contents)
            groups = group_tokens(tokens)
            category = identify_category(tokens=tokens, groups=groups)

            entry = metadata_by_filename.get(image.filename, {}) or {}
            if not isinstance(entry, dict):
                entry = {}
            expected_brand = entry.get("expected_brand", "") or ""
            expected_abv = entry.get("expected_abv", "") or ""
            expected_class_type = entry.get("expected_class_type", "") or ""

            validation = run_validations(
                category=category,
                tokens=tokens,
                groups=groups,
                expected_brand=expected_brand,
                expected_abv=expected_abv,
                expected_class_type=expected_class_type,
            )
            results.append(
                {
                    "image_id": f"img_{idx}",
                    "filename": image.filename,
                    "metadata": entry,
                    "expected_brand_supplied": bool(expected_brand.strip()),
                    "expected_abv_supplied": bool(expected_abv.strip()),
                    "expected_class_type_supplied": bool(expected_class_type.strip()),
                    "token_count": len(tokens),
                    "tokens": tokens,
                    "groups": groups,
                    "category": validation["category"],
                    "validation": validation,
                }
            )
        except HTTPException:
            raise
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

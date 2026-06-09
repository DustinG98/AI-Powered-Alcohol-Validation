from fastapi import APIRouter, UploadFile, File
from typing import List

from app.services.ocr_service import OCRUnavailable, group_tokens, ocr_image_file
from app.validators.validation_engine import run_validations
from app.validators.rules.categorize import identify_category

router = APIRouter()


@router.post("/analyze")
async def analyze(images: List[UploadFile] = File(...)):
    results = []
    for idx, image in enumerate(images, start=1):
        try:
            contents = await image.read()
            tokens = ocr_image_file(contents)
            groups = group_tokens(tokens)
            category = identify_category(tokens=tokens, groups=groups)
            validation = run_validations(category=category, tokens=tokens, groups=groups)
            results.append(
                {
                    "image_id": f"img_{idx}",
                    "filename": image.filename,
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
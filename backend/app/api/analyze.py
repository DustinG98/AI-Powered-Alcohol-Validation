from fastapi import APIRouter, UploadFile, File
from typing import List

router = APIRouter()


@router.post("/analyze")
async def analyze(images: List[UploadFile] = File(...)):
    return {
        "status": "Success",
        "image_count": len(images),
    }

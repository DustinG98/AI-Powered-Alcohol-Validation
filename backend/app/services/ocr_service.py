from __future__ import annotations

import io
import re
import unicodedata
from functools import lru_cache
from typing import BinaryIO

import numpy as np
from PIL import Image

import os

try:
    from paddleocr import PaddleOCR  # type: ignore
except Exception:  # pragma: no cover - allow import without paddleocr installed
    PaddleOCR = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


# OCR model selection. Defaults to the mobile recognition model for
# faster CPU inference. Set OCR_RECOGNITION_MODEL=PP-OCRv5_server_rec
# in the environment to use the heavier server model (higher accuracy,
# ~2-3x slower on CPU).
_RECOGNITION_MODEL = os.environ.get(
    "OCR_RECOGNITION_MODEL", "PP-OCRv5_mobile_rec"
)
_DETECTION_MODEL = os.environ.get(
    "OCR_DETECTION_MODEL", "PP-OCRv5_mobile_det"
)


class OCRUnavailable(RuntimeError):
    """Raised when the PaddleOCR engine cannot be initialized."""


@lru_cache(maxsize=1)
def get_ocr_engine() -> "PaddleOCR":
    if PaddleOCR is None:
        raise OCRUnavailable(
            "PaddleOCR is not installed. Run `pip install paddleocr paddlepaddle`."
        )
    return PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        text_detection_model_name=_DETECTION_MODEL,
        text_recognition_model_name=_RECOGNITION_MODEL,
    )


def reset_ocr_engine() -> None:
    """Drop the cached PaddleOCR instance so the next call to
    `get_ocr_engine()` rebuilds with current env vars. Useful in
    tests or when toggling between mobile/server models at runtime.
    """
    get_ocr_engine.cache_clear()


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_image(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    return np.array(image)


def _enhance_for_ocr(img_array: np.ndarray) -> np.ndarray:
    """Preprocess the image so PaddleOCR reads dense/small text accurately.

    Upscales to 2400px longest edge, then applies grayscale +
    CLAHE + sharpening. Returns original if OpenCV is unavailable.
    """
    if cv2 is None:
        return img_array
    try:
        h, w = img_array.shape[:2]
        longest = max(h, w)
        if longest < 2400:
            scale = 2400 / longest
            new_w = int(round(w * scale))
            new_h = int(round(h * scale))
            img_array = cv2.resize(
                img_array, (new_w, new_h), interpolation=cv2.INTER_LINEAR
            )

        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        img_array = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)

        blurred = cv2.GaussianBlur(img_array, (0, 0), sigmaX=1.0)
        img_array = cv2.addWeighted(img_array, 1.5, blurred, -0.5, 0)
        return img_array
    except Exception:
        return img_array


def _coerce_pages(raw_result) -> list:
    if raw_result is None:
        return []
    if hasattr(raw_result, "__iter__") and not isinstance(raw_result, (list, tuple, dict, str, bytes)):
        try:
            raw_result = list(raw_result)
        except TypeError:
            pass
    if isinstance(raw_result, list):
        if len(raw_result) == 1 and isinstance(raw_result[0], list):
            return [raw_result[0]]
        return raw_result
    return [raw_result]


def _bbox_from_points(points) -> dict:
    arr = np.asarray(points, dtype=float).reshape(-1)
    if arr.size >= 2:
        xs = arr[0::2]
        ys = arr[1::2]
    else:
        xs = arr
        ys = arr
    return {
        "x_min": int(xs.min()),
        "y_min": int(ys.min()),
        "x_max": int(xs.max()),
        "y_max": int(ys.max()),
    }


def _bbox_from_array(box) -> dict:
    try:
        arr = np.asarray(box, dtype=float)
    except Exception:
        return {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}
    if arr.size == 0:
        return {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}
    if arr.ndim == 1 and arr.size == 4:
        return {
            "x_min": int(arr[0]),
            "y_min": int(arr[1]),
            "x_max": int(arr[2]),
            "y_max": int(arr[3]),
        }
    return _bbox_from_points(arr)


def _safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _page_to_dict(page) -> dict | None:
    if page is None:
        return None
    if isinstance(page, dict):
        return page

    json_attr = _safe_getattr(page, "json", None)
    if json_attr is not None:
        if isinstance(json_attr, dict):
            return json_attr
        if hasattr(json_attr, "get") and callable(getattr(json_attr, "get", None)):
            try:
                if isinstance(json_attr.get("res"), dict):
                    return json_attr.get("res")
            except Exception:
                pass

    rec_texts = _safe_getattr(page, "rec_texts", None)
    if rec_texts is None:
        rec_texts = _safe_getattr(page, "texts", None)
    if rec_texts is not None:
        rec_boxes = _safe_getattr(page, "rec_boxes", None)
        if rec_boxes is None:
            rec_boxes = _safe_getattr(page, "boxes", None)
        rec_scores = _safe_getattr(page, "rec_scores", None)
        if rec_scores is None:
            rec_scores = _safe_getattr(page, "scores", None)
        return {
            "rec_texts": rec_texts,
            "rec_boxes": rec_boxes,
            "rec_scores": rec_scores,
        }

    if isinstance(page, (list, tuple)) and page:
        first = page[0]
        if isinstance(first, str):
            return {"rec_texts": list(page)}
        if hasattr(first, "__iter__") and not isinstance(first, (str, bytes, dict)):
            try:
                return {"rec_texts": list(page)}
            except Exception:
                return None

    return None


def _first_present(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _has_items(value) -> bool:
    if value is None:
        return False
    try:
        return len(value) > 0
    except TypeError:
        return True


def _extract_tokens(raw_result) -> list[dict]:
    tokens: list[dict] = []
    if raw_result is None:
        return tokens

    for page in _coerce_pages(raw_result):
        data = _page_to_dict(page)
        if data is None:
            continue

        recs = _first_present(data.get("rec_texts"), data.get("texts"))
        boxes = _first_present(data.get("rec_boxes"), data.get("boxes"))
        scores = _first_present(data.get("rec_scores"), data.get("scores"))

        if not _has_items(recs):
            continue

        if isinstance(recs, str):
            tokens.append(
                {
                    "text": recs.strip(),
                    "normalized_text": _normalize_text(recs),
                    "confidence": 1.0,
                    "bbox": {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0},
                }
            )
            continue

        for i, text in enumerate(recs):
            if isinstance(text, dict):
                token_text = text.get("text") or text.get("transcription") or ""
                token_box = text.get("bbox") or text.get("box")
                token_score = text.get("score") or text.get("confidence")
            else:
                token_text = str(text) if text is not None else ""
                token_box = boxes[i] if _has_items(boxes) and i < len(boxes) else None
                token_score = scores[i] if _has_items(scores) and i < len(scores) else None

            if not token_text:
                continue

            if isinstance(token_box, (list, tuple, np.ndarray)):
                bbox = _bbox_from_array(token_box)
            else:
                bbox = {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}

            try:
                confidence = float(token_score) if token_score is not None else 1.0
            except Exception:
                confidence = 1.0

            tokens.append(
                {
                    "text": token_text,
                    "normalized_text": _normalize_text(token_text),
                    "confidence": round(confidence, 4),
                    "bbox": bbox,
                }
            )

    return tokens


def extract_tokens(source: str | bytes | BinaryIO) -> list[dict]:
    """Run PaddleOCR on an image and return tokens in the project's schema.

    `source` can be a filesystem path, raw bytes, or a binary file-like object.
    Bounding-box coordinates are returned in the ORIGINAL image space (i.e.
    rescaled down if the image was upscaled internally for OCR accuracy).
    """
    engine = get_ocr_engine()

    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif hasattr(source, "read"):
        raw = source.read()
    else:
        raw = None

    if raw is not None:
        original = _read_image(raw)
    elif isinstance(source, np.ndarray):
        original = source
    else:
        original = np.array(source)

    original_h, original_w = original.shape[:2]
    enhanced = _enhance_for_ocr(original)
    if enhanced.shape[:2] != (original_h, original_w):
        scale_x = original_w / enhanced.shape[1]
        scale_y = original_h / enhanced.shape[0]
    else:
        scale_x = scale_y = 1.0

    result = engine.predict(enhanced)

    tokens = _extract_tokens(result)
    if scale_x != 1.0 or scale_y != 1.0:
        for t in tokens:
            b = t.get("bbox")
            if isinstance(b, dict):
                b["x_min"] = int(round(b.get("x_min", 0) * scale_x))
                b["y_min"] = int(round(b.get("y_min", 0) * scale_y))
                b["x_max"] = int(round(b.get("x_max", 0) * scale_x))
                b["y_max"] = int(round(b.get("y_max", 0) * scale_y))
    return tokens


def _cluster_columns(tokens: list[dict], min_x_gap: int = 40) -> list[list[dict]]:
    """Cluster tokens into vertical columns by x-overlap.

    Tokens are sorted by x_min. A token joins the current column if its
    x_min is within `min_x_gap` pixels of the column's running x_max; a new
    column is started when the gap exceeds the threshold.
    """
    if not tokens:
        return []
    sorted_tokens = sorted(tokens, key=lambda t: t["bbox"].get("x_min", 0))
    columns: list[list[dict]] = [[sorted_tokens[0]]]
    current_x_max = sorted_tokens[0]["bbox"].get("x_max", 0)
    for token in sorted_tokens[1:]:
        cur_x_min = token["bbox"].get("x_min", 0)
        if cur_x_min - current_x_max > min_x_gap:
            columns.append([token])
        else:
            columns[-1].append(token)
        current_x_max = max(current_x_max, token["bbox"].get("x_max", 0))
    return columns


def _group_lines_in_column(
    tokens: list[dict], cluster_tolerance_ratio: float = 0.5
) -> list[list[dict]]:
    """Group tokens within a single column into lines by y-center clustering."""
    if not tokens:
        return []
    sorted_tokens = sorted(
        tokens,
        key=lambda t: (t["bbox"].get("y_min", 0) + t["bbox"].get("y_max", 0)) / 2,
    )
    heights = [
        max(t["bbox"].get("y_max", 0) - t["bbox"].get("y_min", 0), 1)
        for t in sorted_tokens
    ]
    median_h = sorted(heights)[len(heights) // 2] if heights else 12
    tolerance = max(median_h * cluster_tolerance_ratio, 4)

    lines: list[list[dict]] = []
    cluster: list[dict] = [sorted_tokens[0]]
    cluster_centers: list[float] = [
        (sorted_tokens[0]["bbox"].get("y_min", 0)
         + sorted_tokens[0]["bbox"].get("y_max", 0)) / 2
    ]
    for token in sorted_tokens[1:]:
        cy = (token["bbox"].get("y_min", 0) + token["bbox"].get("y_max", 0)) / 2
        running_center = sum(cluster_centers) / len(cluster_centers)
        if abs(cy - running_center) <= tolerance:
            cluster.append(token)
            cluster_centers.append(cy)
        else:
            lines.append(cluster)
            cluster = [token]
            cluster_centers = [cy]
    lines.append(cluster)
    return lines


def _merge_bbox(tokens: list[dict]) -> dict:
    return {
        "x_min": int(min(t["bbox"].get("x_min", 0) for t in tokens)),
        "y_min": int(min(t["bbox"].get("y_min", 0) for t in tokens)),
        "x_max": int(max(t["bbox"].get("x_max", 0) for t in tokens)),
        "y_max": int(max(t["bbox"].get("y_max", 0) for t in tokens)),
    }


def group_tokens(
    tokens: list[dict],
    cluster_tolerance_ratio: float = 0.35,
    min_x_gap: int = 40,
) -> list[dict]:
    """Group OCR tokens into line-level groups with merged bounding boxes."""
    safe_tokens: list[dict] = []
    for t in tokens:
        if not isinstance(t, dict):
            continue
        bbox = t.get("bbox")
        text = t.get("text")
        if not isinstance(bbox, dict) or text is None:
            continue
        safe_tokens.append(t)

    if not safe_tokens:
        return []

    columns = _cluster_columns(safe_tokens, min_x_gap=min_x_gap)
    groups: list[dict] = []
    for col in sorted(columns, key=lambda c: c[0]["bbox"].get("x_min", 0)):
        for line_tokens in _group_lines_in_column(
            col, cluster_tolerance_ratio=cluster_tolerance_ratio
        ):
            line_sorted = sorted(line_tokens, key=lambda t: t["bbox"].get("x_min", 0))
            text = " ".join(t.get("text", "") for t in line_sorted).strip()
            if not text:
                continue
            groups.append({"text": text, "bbox": _merge_bbox(line_sorted)})
    return groups


def ocr_image_file(file_bytes: bytes) -> list[dict]:
    """Convenience wrapper for FastAPI UploadFile contents."""
    return extract_tokens(file_bytes)

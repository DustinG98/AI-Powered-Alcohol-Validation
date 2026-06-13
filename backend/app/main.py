from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.config import ALLOWED_ORIGINS, configure_logging


configure_logging()

app = FastAPI(
    title="AI-Powered Alcohol Label Verification",
    version="0.1.0",
    description="OCR + rule-based validation for TTB label compliance.",
)

app.include_router(analyze_router, prefix="/api")


@app.get("/")
def ping():
    return {"status": "ok"}


# CORS: the ALLOWED_ORIGINS env var is a comma-separated list. Use ["*"]
# explicitly only for local development; production should pin the
# deployed front-end origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

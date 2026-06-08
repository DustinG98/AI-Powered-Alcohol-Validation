from fastapi import FastAPI
from app.api.analyze import router as analyze_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.include_router(analyze_router, prefix="/api")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
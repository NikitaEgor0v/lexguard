"""
Legal Analyzer — Система анализа юридических документов
Дипломная работа — Егоров Н.Р., УрФУ 2026
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from api.chat_routes import router as chat_router
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(
    title="Legal Analyzer API",
    description="Система анализа юридических документов на базе Gemma3 + RAG",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")

@app.get("/")
def root():
    return {"status": "ok", "service": "Legal Analyzer API v1.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.mock_crm_routes import router as mock_crm_router
from app.api.routes import router as api_router
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title="Retail AI MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(mock_crm_router)

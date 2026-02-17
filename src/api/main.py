"""FastAPI application entry point."""

from fastapi import FastAPI

from .middleware import APIKeyMiddleware
from .routes import router

app = FastAPI(title="PLC Knowledge Base API", version="1.0.0")
app.add_middleware(APIKeyMiddleware)
app.include_router(router, prefix="/api/v1")

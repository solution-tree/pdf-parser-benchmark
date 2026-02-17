"""API key authentication middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import get_config


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Check X-API-Key header against config.API_KEY. Exempt /health."""

    async def dispatch(self, request: Request, call_next):
        # Exempt health endpoint from auth
        if request.url.path.endswith("/health"):
            return await call_next(request)

        config = get_config()

        # Skip auth if no API key is configured
        if not config.API_KEY:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if api_key != config.API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)

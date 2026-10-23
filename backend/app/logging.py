import json
import logging
import sys
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
               "logger": record.name, "msg": record.getMessage()}
        out.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # на INFO він пише адресу запиту, а в Telegram у ній токен бота


class RequestLogMiddleware(BaseHTTPMiddleware):
    """request_id + один JSON-рядок на запит; тіла, паролі й токени не логуються."""

    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("vigil.access").info(
            "request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                              "status": response.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return response

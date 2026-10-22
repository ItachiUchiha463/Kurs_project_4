import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("vigil.errors")


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", details: list | None = None, code: str | None = None):
        super().__init__(message)
        self.message, self.details = message, details or []
        if code:
            self.code = code


class NotFound(AppError):
    status, code = 404, "not_found"


class Conflict(AppError):
    status, code = 409, "conflict"


class QuotaExceeded(AppError):
    status, code = 409, "quota_exceeded"


class AuthError(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


def _body(code: str, message: str, details: list | None = None, request_id: str | None = None) -> dict:
    err = {"code": code, "message": message, "details": details or []}
    if request_id:
        err["request_id"] = request_id
    return {"error": err}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Некоректні дані", details), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        log.error("unhandled", exc_info=exc, extra={"request_id": rid})
        return JSONResponse(_body("internal_error", "Внутрішня помилка", request_id=rid), status_code=500)

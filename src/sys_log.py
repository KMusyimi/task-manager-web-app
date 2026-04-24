from contextlib import asynccontextmanager
import logging
import re
import traceback
import logging.config
from fastapi import FastAPI, Request

from src.models.entities import ErrorLog, RequestLog

# define the name of the module as the logger name
LOGGER = logging.getLogger("users_logger")


class RequestInfo:
    def __init__(self, request) -> None:
        self.request = request

    @property
    def method(self) -> str:
        return str(self.request.method)

    @property
    def route(self) -> str:
        return self.request["path"]

    @property
    def ip(self) -> str:
        return str(self.request.client.host)

    @property
    def url(self) -> str:
        return str(self.request.url)

    @property
    def host(self) -> str:
        return str(self.request.url.hostname)

    @property
    def headers(self) -> dict:
        return {key: value for key, value in self.request.headers.items()}

    @property
    def body(self) -> dict:
        return self.request.state.body


def log_request(request: Request):
    request_info = RequestInfo(request)
    request_log = RequestLog(
        req_id=request.state.req_id,
        method=request_info.method,
        route=request_info.route,
        ip=request_info.ip,
        url=request_info.url,
        host=request_info.host,
        body=request_info.body,
        headers=request_info.headers,
    )
    LOGGER.info(request_log.model_dump())


def log_error(uuid: str, response_body: dict):
    error_log = ErrorLog(
        req_id=uuid,
        error_message=response_body["error_message"],
    )
    LOGGER.error(error_log.model_dump())
    LOGGER.error(traceback.format_exc())


class SensitiveDataFilter(logging.Filter):
    SENSITIVE_KEYS = (
        "credentials", "authorization", "token",
        "password", "access_token", "refresh_token",
        'current_pw', 'new_pw', 'confirm_pw'
    )

    # Dynamically build regex: (?<=(token|password|...)=)([^;\s&]+)
    SENSITIVE_PATTERN = rf"({'|'.join(SENSITIVE_KEYS)})[\s\"']*[=:]\s*[\"']?([^\"'\s&;,]+)[\"']?"

    def filter(self, record):
        try:
            # Handle extra arguments (e.g., logger.info("msg", {"password": "123"}))
            if record.args:
                record.args = self.mask_sensitive_args(
                    record.args)  # type: ignore

            # Handle the main message string
            if isinstance(record.msg, str):
                record.msg = self.mask_sensitive_msg(record.msg)
            return True
        except Exception:
            return True

    def mask_sensitive_args(self, args):
        if isinstance(args, dict):
            return {
                k: "******" if str(k).lower() in self.SENSITIVE_KEYS
                else self.mask_sensitive_msg(v)
                for k, v in args.items()
            }
        if isinstance(args, (list, tuple)):
            return type(args)(self.mask_sensitive_msg(arg) for arg in args)
        return args

    def mask_sensitive_msg(self, message):
        if isinstance(message, dict):
            return self.mask_sensitive_args(message)

        if isinstance(message, str):
            # The replacement is JUST the stars because 'key=' is preserved by lookbehind
            return re.sub(self.SENSITIVE_PATTERN, "******", message, flags=re.IGNORECASE)

        return message


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            # Added %(levelprefix)s for colored [INFO], [ERROR], etc.
            "fmt": "%(levelprefix)s %(asctime)s  [%(name)s]  %(message)s",
            "use_colors": True,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            # Specialized formatter for HTTP access logs
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            "use_colors": True,
        },
    },
    "filters": {
        "sensitive_data_filter": {
            "()": SensitiveDataFilter,
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["sensitive_data_filter"],
            "formatter": "default",
            "level": "DEBUG",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "formatter": "default",
            "class": "logging.handlers.RotatingFileHandler",
            "filters": ["sensitive_data_filter"],
            "level": "DEBUG",
            "filename": "sys_log.log",
            "mode": "a",
            "maxBytes": 5242880,
            "backupCount": 3,
        },
    },
    "loggers": {
        "users_logger": {
            "handlers": ["file", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
            "formatter": "access",  # Use the access-specific colored format
        },
    },
}


@asynccontextmanager
async def log_lifespan(app: FastAPI):
    # --- Startup Logic ---
    logging.config.dictConfig(LOGGING_CONFIG)
    LOGGER.info("Custom Log Config Loaded with Sensitivity Filters")

    yield  # The application runs while this yield is active

    # --- Shutdown Logic (Optional) ---
    LOGGER.info("Shutting down...")

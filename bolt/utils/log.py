import logging
import logging.config
from os import environ

request_logger = logging.getLogger("bolt.request")


def configure_logging(logging_settings):
    # Load the defaults
    default_logging = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {
                "format": "[%(levelname)s] %(message)s",
            },
        },
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "simple",
            },
        },
        "loggers": {
            "bolt": {
                "handlers": ["console"],
                "level": environ.get("BOLT_LOG_LEVEL", "INFO"),
            },
            "app": {
                "handlers": ["console"],
                "level": environ.get("APP_LOG_LEVEL", "INFO"),
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(default_logging)

    # Then customize it from settings
    if logging_settings:
        logging.config.dictConfig(logging_settings)


def log_response(
    message,
    *args,
    response=None,
    request=None,
    logger=request_logger,
    level=None,
    exception=None,
):
    """
    Log errors based on HttpResponse status.

    Log 5xx responses as errors and 4xx responses as warnings (unless a level
    is given as a keyword argument). The HttpResponse status_code and the
    request are passed to the logger's extra parameter.
    """
    # Check if the response has already been logged. Multiple requests to log
    # the same response can be received in some cases, e.g., when the
    # response is the result of an exception and is logged when the exception
    # is caught, to record the exception.
    if getattr(response, "_has_been_logged", False):
        return

    if level is None:
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"
        else:
            level = "info"

    getattr(logger, level)(
        message,
        *args,
        extra={
            "status_code": response.status_code,
            "request": request,
        },
        exc_info=exception,
    )
    response._has_been_logged = True

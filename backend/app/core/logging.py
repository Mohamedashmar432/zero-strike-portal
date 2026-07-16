import logging

import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            # Lets existing `logger.error("... %s ...", arg)`-style call sites (written for
            # stdlib logging.getLogger) keep working unchanged after switching to structlog.
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        # stdlib-backed (not PrintLoggerFactory): routes through logging.getLogger/handlers
        # rather than a bare print, so anything that hooks stdlib logging later (pytest's
        # caplog today; a Sentry/log-shipping handler tomorrow) still sees these records.
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)

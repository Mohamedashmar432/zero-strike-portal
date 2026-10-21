import logging

from app.core import log_sink


def test_install_also_covers_uvicorn_whose_logger_does_not_propagate_to_root():
    # An unhandled 500 is logged by uvicorn.error ("Exception in ASGI application"); uvicorn sets
    # propagate=False on it, so a root-only handler never saw a single one in production.
    root, uvicorn_logger = logging.getLogger(), logging.getLogger("uvicorn")
    before = (list(root.handlers), list(uvicorn_logger.handlers))
    try:
        log_sink.install()
        log_sink.install()  # idempotent
        for logger in (root, uvicorn_logger):
            assert sum(isinstance(h, log_sink.MongoLogHandler) for h in logger.handlers) >= 1
        assert sum(isinstance(h, log_sink.MongoLogHandler) for h in uvicorn_logger.handlers) <= 1
    finally:
        root.handlers[:], uvicorn_logger.handlers[:] = before

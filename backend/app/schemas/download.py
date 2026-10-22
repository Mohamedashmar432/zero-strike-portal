from datetime import datetime

from pydantic import BaseModel


class ScannerBinaryInfo(BaseModel):
    """Public metadata for one published zerostrike binary (lets a pipeline check before downloading)."""

    version: str
    os: str
    arch: str
    filename: str
    sha256: str
    size_bytes: int
    uploaded_at: datetime

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pymongo import IndexModel

ScannerOs = Literal["linux", "windows", "darwin"]
ScannerArch = Literal["amd64", "arm64"]


class ScannerBinary(Document):
    """Metadata for a zerostrike binary uploaded into GridFS (bucket "scanner_binaries").

    The bytes live in GridFS, not on this document — see download_service for the
    upload/stream helpers. `uploaded_at` (not a parsed version string) decides "latest",
    since uploads happen in release order and that's simplest-correct without a
    semver-comparison dependency.
    """

    version: str
    os: ScannerOs
    arch: ScannerArch
    filename: str
    gridfs_file_id: PydanticObjectId
    sha256: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str

    class Settings:
        name = "scanner_binaries"
        indexes = [
            IndexModel([("version", 1), ("os", 1), ("arch", 1)], unique=True),
            IndexModel([("os", 1), ("arch", 1), ("uploaded_at", -1)]),  # "latest" lookup
        ]

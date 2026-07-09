"""Filesystem storage for scan artifacts.

Layout: {artifact_storage_path}/{project_id}/{scan_id}/report.{json,html}
Ids must be 24-hex Mongo ObjectIds and the resolved path is asserted to stay
within the storage root (traversal defense).
"""

import re
import shutil
from pathlib import Path

from app.core.config import settings

_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{24}$")


def _base() -> Path:
    return Path(settings.artifact_storage_path).resolve()


def _scan_dir(project_id: str, scan_id: str) -> Path:
    if not _OBJECT_ID.match(project_id) or not _OBJECT_ID.match(scan_id):
        raise ValueError("project_id and scan_id must be 24-hex ObjectIds")
    base = _base()
    target = (base / project_id / scan_id).resolve()
    if not target.is_relative_to(base):
        raise ValueError("resolved artifact path escapes storage root")
    return target


def path_for(project_id: str, scan_id: str, kind: str) -> Path:
    """kind is 'json' or 'html'."""
    if kind not in ("json", "html"):
        raise ValueError("kind must be 'json' or 'html'")
    return _scan_dir(project_id, scan_id) / f"report.{kind}"


def _write(project_id: str, scan_id: str, kind: str, data: bytes) -> str:
    path = path_for(project_id, scan_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def write_json(project_id: str, scan_id: str, data: bytes) -> str:
    return _write(project_id, scan_id, "json", data)


def write_html(project_id: str, scan_id: str, data: bytes) -> str:
    return _write(project_id, scan_id, "html", data)


def delete_scan_dir(project_id: str, scan_id: str) -> None:
    shutil.rmtree(_scan_dir(project_id, scan_id), ignore_errors=True)


def delete_project_dir(project_id: str) -> None:
    if not _OBJECT_ID.match(project_id):
        raise ValueError("project_id must be a 24-hex ObjectId")
    base = _base()
    target = (base / project_id).resolve()
    if not target.is_relative_to(base):
        raise ValueError("resolved project path escapes storage root")
    shutil.rmtree(target, ignore_errors=True)

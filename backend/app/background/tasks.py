"""BackgroundTasks entrypoints.

Thin re-export so scheduling sites read as `background.add_task(tasks.run_cloud_scan, ...)`
while the implementation lives in the cloud_scan_service.
"""

from app.services.cloud_scan_service import run_cloud_scan

__all__ = ["run_cloud_scan"]

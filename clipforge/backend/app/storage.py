"""Storage adapters for rendered clips.

* ``LocalStorage`` (default): files stay in the job's working directory and are
  served by the API. Good for development and single-node deployments.
* ``S3Storage``: after rendering, clips/thumbnails are uploaded to S3 (or any
  S3-compatible store via AWS_ENDPOINT_URL) and served with presigned URLs.
  Requires ``pip install boto3`` and standard AWS credentials in the environment.
  NOTE: written against the boto3 API but not exercised in this repo's test run.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import settings

log = logging.getLogger(__name__)


class Storage:
    name = "base"

    def publish(self, job_id: str, path: Path) -> None:
        """Called after a file is produced. Local storage: no-op."""

    def url_for(self, job_id: str, path: Path, download_name: Optional[str] = None) -> Optional[str]:
        """Return an external URL to redirect to, or None to serve the local file."""
        return None

    def delete_job(self, job_id: str) -> None: ...


class LocalStorage(Storage):
    name = "local"


class S3Storage(Storage):
    name = "s3"

    def __init__(self) -> None:
        import boto3  # optional dependency

        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        self.client = boto3.client("s3")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix

    def _key(self, job_id: str, path: Path) -> str:
        return f"{self.prefix}{job_id}/{path.name}"

    def publish(self, job_id: str, path: Path) -> None:
        ctype = {"mp4": "video/mp4", "jpg": "image/jpeg", "zip": "application/zip"}.get(path.suffix.lstrip("."), "application/octet-stream")
        self.client.upload_file(str(path), self.bucket, self._key(job_id, path), ExtraArgs={"ContentType": ctype})

    def url_for(self, job_id: str, path: Path, download_name: Optional[str] = None) -> Optional[str]:
        params = {"Bucket": self.bucket, "Key": self._key(job_id, path)}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=3600)

    def delete_job(self, job_id: str) -> None:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=f"{self.prefix}{job_id}/")
        keys = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        if keys:
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})


def make_storage() -> Storage:
    if settings.storage_backend.lower() == "s3":
        return S3Storage()
    return LocalStorage()


storage = make_storage()

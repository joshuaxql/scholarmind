from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Protocol, cast
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client
from mypy_boto3_s3.literals import BucketLocationConstraintType

from scholarmind.core.config import Settings


class ObjectStore(Protocol):
    async def ensure_ready(self) -> None: ...

    async def healthcheck(self) -> None: ...

    async def put_file(self, key: str, source: Path, content_type: str) -> None: ...

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str | None: ...

    def local_path(self, key: str) -> Path | None: ...

    async def close(self) -> None: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    async def ensure_ready(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    async def healthcheck(self) -> None:
        available = await asyncio.to_thread(
            lambda: self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK)
        )
        if not available:
            raise OSError("Local object storage is unavailable")

    async def put_file(self, key: str, source: Path, content_type: str) -> None:
        del content_type
        destination = self._path(key)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

        def copy_atomically() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, temporary)
            temporary.replace(destination)

        await asyncio.to_thread(copy_atomically)

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        destination = self._path(key)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

        def write_atomically() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            temporary.replace(destination)

        await asyncio.to_thread(write_atomically)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str | None:
        del key, expires_seconds
        return None

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.is_file() else None

    async def close(self) -> None:
        return None

    def _path(self, key: str) -> Path:
        normalized = _validate_key(key)
        candidate = (self.root / Path(*normalized.parts)).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Object key escapes the storage root")
        return candidate


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        secret = (
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        )
        self.bucket = settings.s3_bucket
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=secret,
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    async def ensure_ready(self) -> None:
        def ensure_bucket() -> None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
                return
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
            region = self.client.meta.region_name
            try:
                if region not in {None, "us-east-1"}:
                    self.client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={
                            "LocationConstraint": cast(BucketLocationConstraintType, region)
                        },
                    )
                else:
                    self.client.create_bucket(Bucket=self.bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code != "BucketAlreadyOwnedByYou":
                    raise

        await asyncio.to_thread(ensure_bucket)

    async def healthcheck(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    async def put_file(self, key: str, source: Path, content_type: str) -> None:
        object_key = str(_validate_key(key))
        await asyncio.to_thread(
            self.client.upload_file,
            str(source),
            self.bucket,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> None:
        object_key = str(_validate_key(key))
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )

    async def delete(self, key: str) -> None:
        object_key = str(_validate_key(key))
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=object_key)

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str | None:
        object_key = str(_validate_key(key))
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires_seconds,
        )

    def local_path(self, key: str) -> Path | None:
        del key
        return None

    async def close(self) -> None:
        self.client.close()


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "s3":
        return S3ObjectStore(settings)
    return LocalObjectStore(settings.local_storage_path)


def _validate_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts or "\\" in key:
        raise ValueError("Invalid object key")
    return path

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class StoredObject:
    uri: str
    sha256: str
    size_bytes: int
    content_type: str
    backend: str


class ArtifactStorage(Protocol):
    def put(self, payload: bytes, *, content_type: str) -> StoredObject: ...
    def open(self, uri: str) -> BinaryIO: ...
    def exists(self, uri: str) -> bool: ...
    def delete(self, uri: str) -> None: ...


class LocalArtifactStorage:
    backend = "local"

    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, payload: bytes, *, content_type: str) -> StoredObject:
        sha256 = hashlib.sha256(payload).hexdigest()
        key = f"sha256/{sha256[:2]}/{sha256}"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(payload)
        return StoredObject(path.as_uri(), sha256, len(payload), content_type, self.backend)

    def _path(self, uri: str) -> Path:
        path = Path(urlparse(uri).path).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("Artifact URI is outside configured local storage")
        return path

    def open(self, uri: str) -> BinaryIO:
        return self._path(uri).open("rb")

    def exists(self, uri: str) -> bool:
        return self._path(uri).exists()

    def delete(self, uri: str) -> None:
        self._path(uri).unlink(missing_ok=True)


class S3ArtifactStorage:
    backend = "s3"

    def __init__(self, client, *, bucket: str, prefix: str = "artifacts"):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def _key(self, sha256: str) -> str:
        return f"{self.prefix}/sha256/{sha256[:2]}/{sha256}"

    def _parse(self, uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("Invalid S3 artifact URI")
        return parsed.netloc, parsed.path.lstrip("/")

    def put(self, payload: bytes, *, content_type: str) -> StoredObject:
        sha256 = hashlib.sha256(payload).hexdigest()
        key = self._key(sha256)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType=content_type)
        return StoredObject(f"s3://{self.bucket}/{key}", sha256, len(payload), content_type, self.backend)

    def open(self, uri: str) -> BinaryIO:
        bucket, key = self._parse(uri)
        return BytesIO(self.client.get_object(Bucket=bucket, Key=key)["Body"].read())

    def exists(self, uri: str) -> bool:
        bucket, key = self._parse(uri)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, uri: str) -> None:
        bucket, key = self._parse(uri)
        self.client.delete_object(Bucket=bucket, Key=key)

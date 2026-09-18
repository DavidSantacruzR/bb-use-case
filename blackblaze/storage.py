"""Object storage, behind a protocol so the service layer never imports b2sdk."""

from dataclasses import dataclass
from typing import Protocol

from b2sdk.v3 import B2Api, InMemoryAccountInfo


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    handle: str  # Backend identifier for this exact version of the object.


class Storage(Protocol):
    def store(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def replace_metadata(
        self, stored: StoredObject, content_type: str, metadata: dict[str, str]
    ) -> StoredObject: ...


class B2Storage:
    """Backblaze B2 via the official SDK.

    B2 objects are immutable, so metadata cannot be edited in place. Replacing it
    means copying the object onto a new version with the new metadata attached --
    passing both content_type and file_info is what triggers B2's REPLACE
    directive rather than carrying the source metadata over.
    """

    def __init__(self, key_id: str, app_key: str, bucket_name: str) -> None:
        self._api = B2Api(InMemoryAccountInfo())
        self._api.authorize_account(key_id, app_key)
        # Resolves the bucket up front: a wrong name fails at startup, not on
        # the first upload.
        self._bucket = self._api.get_bucket_by_name(bucket_name)

    def store(self, key: str, data: bytes, content_type: str) -> StoredObject:
        version = self._bucket.upload_bytes(
            data_bytes=data, file_name=key, content_type=content_type
        )
        return StoredObject(key=key, size=len(data), handle=version.id_)

    def replace_metadata(
        self, stored: StoredObject, content_type: str, metadata: dict[str, str]
    ) -> StoredObject:
        version = self._bucket.copy(
            file_id=stored.handle,
            new_file_name=stored.key,
            content_type=content_type,
            file_info=metadata,
        )
        return StoredObject(key=stored.key, size=stored.size, handle=version.id_)

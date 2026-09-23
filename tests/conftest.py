"""Fixtures shared by every test.

The environment is populated before ``blackblaze.settings`` is ever imported:
that module builds its ``Settings`` at import time and raises without these
keys. Real environment variables win over the developer's .env, so the suite
behaves identically on a laptop and in CI.
"""

import os

os.environ.setdefault("B2_KEY_ID", "test-key-id")
os.environ.setdefault("B2_APP_KEY", "test-app-key")
os.environ.setdefault("B2_BUCKET_NAME", "test-bucket")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

import pytest

from blackblaze.describer import DescriptionUnavailable
from blackblaze.storage import StoredObject

# --- sample files -----------------------------------------------------------
# Real magic bytes: detect_media_type sniffs contents, so these have to be the
# genuine signatures rather than arbitrary placeholders.

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
TEXT_BYTES = b"A quarterly report about warehouse throughput.\n"
UNDECODABLE_BYTES = b"\x00\x01\x02\xff\xfe"


@pytest.fixture
def png_bytes() -> bytes:
    return PNG_BYTES


@pytest.fixture
def jpeg_bytes() -> bytes:
    return JPEG_BYTES


@pytest.fixture
def text_bytes() -> bytes:
    return TEXT_BYTES


@pytest.fixture
def undecodable_bytes() -> bytes:
    """Neither an image we recognise nor valid UTF-8 -- an unsupported file."""
    return UNDECODABLE_BYTES


# --- doubles ----------------------------------------------------------------


class FakeStorage:
    """An in-memory stand-in for B2, satisfying the Storage protocol.

    b2sdk is faked at this boundary rather than at the SDK call, because the
    service layer's contract is the protocol, not Backblaze's wire format.
    """

    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.store_failure: Exception | None = None
        self.metadata_failure: Exception | None = None
        self._handles = 0

    def store(self, key: str, data: bytes, content_type: str) -> StoredObject:
        if self.store_failure is not None:
            raise self.store_failure
        self._handles += 1
        handle = f"handle-{self._handles}"
        self.stored[key] = {"data": data, "content_type": content_type, "handle": handle}
        return StoredObject(key=key, size=len(data), handle=handle)

    def replace_metadata(
        self, stored: StoredObject, content_type: str, metadata: dict[str, str]
    ) -> StoredObject:
        if self.metadata_failure is not None:
            raise self.metadata_failure
        self.metadata[stored.key] = metadata
        self._handles += 1
        return StoredObject(
            key=stored.key, size=stored.size, handle=f"handle-{self._handles}"
        )


class FakeDescriber:
    """Stands in for ClaudeDescriber, with no Anthropic client behind it."""

    def __init__(
        self,
        description: str = "A warehouse floor seen from above.",
        model: str = "claude-opus-5",
        failure: Exception | None = None,
    ) -> None:
        self._description = description
        self._model = model
        self.failure = failure
        self.calls: list[tuple[bytes, str]] = []

    @property
    def model(self) -> str:
        return self._model

    def describe(self, data: bytes, media_type: str) -> str:
        self.calls.append((data, media_type))
        if self.failure is not None:
            raise self.failure
        return self._description


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def describer() -> FakeDescriber:
    return FakeDescriber()


@pytest.fixture
def unavailable_describer() -> FakeDescriber:
    return FakeDescriber(failure=DescriptionUnavailable("the model is overloaded"))


@pytest.fixture
def make_describer():
    """Build a describer with a specific description or failure."""
    return FakeDescriber

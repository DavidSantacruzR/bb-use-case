"""The ingest flow: store the file, describe it, attach the description.

Knows nothing about HTTP -- the API and the CLI both call ingest().
"""

import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import quote

from .describer import ClaudeDescriber, DescriptionUnavailable
from .storage import Storage

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

SUPPORTED_MEDIA_TYPES = ("image/png", "image/jpeg", "text/plain")

STATUS_COMPLETE = "complete"
STATUS_NO_DESCRIPTION = "stored_without_description"

_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class UnsupportedFileType(Exception):
    """Raised when a file is neither a PNG, a JPEG, nor UTF-8 text."""


@dataclass(frozen=True)
class IngestResult:
    name: str
    size: int
    status: str
    key: str
    description: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def detect_media_type(data: bytes) -> str | None:
    """Identify a file by its contents, never by its extension or by what the
    client claimed. Returns None for anything we can't describe."""
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain"


def build_key(filename: str) -> str:
    """A collision-proof key that still sorts chronologically and stays readable."""
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    safe = _UNSAFE_KEY_CHARS.sub("_", stem).strip("._") or "file"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4()}/{safe[:100]}"


def ingest(
    *,
    filename: str,
    data: bytes,
    storage: Storage,
    describer: ClaudeDescriber,
    max_metadata_description_chars: int,
) -> IngestResult:
    media_type = detect_media_type(data)
    if media_type is None:
        raise UnsupportedFileType(
            f"unsupported file type; accepted types are {', '.join(SUPPORTED_MEDIA_TYPES)}"
        )

    # Storage first. The file is durable before we involve the AI provider, so a
    # failure to describe it never costs the caller their upload.
    key = build_key(filename)
    stored = storage.store(key=key, data=data, content_type=media_type)

    try:
        description = describer.describe(data, media_type)
    except DescriptionUnavailable as error:
        return IngestResult(
            name=filename, size=stored.size, status=STATUS_NO_DESCRIPTION,
            key=stored.key, error=str(error),
        )

    try:
        storage.replace_metadata(
            stored,
            content_type=media_type,
            metadata=_metadata(
                description, filename, describer.model, max_metadata_description_chars
            ),
        )
    except Exception as error:  # noqa: BLE001 - the file is stored either way
        return IngestResult(
            name=filename, size=stored.size, status=STATUS_NO_DESCRIPTION,
            key=stored.key, description=description,
            error=f"description could not be attached as metadata: {error}",
        )

    return IngestResult(
        name=filename, size=stored.size, status=STATUS_COMPLETE,
        key=stored.key, description=description,
    )


def _metadata(
    description: str, filename: str, model: str, max_description_chars: int
) -> dict[str, str]:
    # B2 file_info values travel as HTTP headers, so they must be ASCII-safe and
    # small. The caller still gets the full description in the response body.
    return {
        "ai-description": quote(description[:max_description_chars]),
        "original-filename": quote(filename[:200]),
        "described-by": model,
    }

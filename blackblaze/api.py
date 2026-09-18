"""HTTP surface: a health check, the upload endpoint, and the demo page."""

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .describer import ClaudeDescriber
from .service import SUPPORTED_MEDIA_TYPES, UnsupportedFileType, ingest
from .settings import settings
from .storage import B2Storage, Storage


# Cached: authorising with B2 and resolving the bucket on every request would
# add a round trip to a flow that already has three.
@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return B2Storage(
        key_id=settings.b2_key_id,
        app_key=settings.b2_app_key,
        bucket_name=settings.b2_bucket_name,
    )


@lru_cache(maxsize=1)
def get_describer() -> ClaudeDescriber:
    return ClaudeDescriber(
        api_key=settings.anthropic_api_key,
        model=settings.model,
        max_text_chars=settings.max_text_chars,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build both up front so bad credentials or a wrong bucket name fail at
    # startup rather than on someone's first upload. Overrides are honoured so
    # tests never reach B2 or Anthropic.
    app.dependency_overrides.get(get_storage, get_storage)()
    app.dependency_overrides.get(get_describer, get_describer)()
    yield


app = FastAPI(
    title="blackblaze",
    description="Store a file in B2 with an AI description.",
    lifespan=lifespan,
)

_STATIC = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/files")
async def upload(
    request: Request,
    storage: Annotated[Storage, Depends(get_storage)],
    describer: Annotated[ClaudeDescriber, Depends(get_describer)],
    file: UploadFile = File(...),
) -> dict:
    _reject_oversized(request)
    data = await _read_within_limit(file)

    try:
        result = ingest(
            filename=file.filename or "file",
            data=data,
            storage=storage,
            describer=describer,
            max_metadata_description_chars=settings.max_metadata_description_chars,
        )
    except UnsupportedFileType as error:
        raise HTTPException(
            status_code=415,
            detail={"error": str(error), "accepted": list(SUPPORTED_MEDIA_TYPES)},
        ) from error

    return result.to_dict()


def _reject_oversized(request: Request) -> None:
    """Refuse an oversized upload from its Content-Length, before reading it."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=_too_large())


async def _read_within_limit(file: UploadFile) -> bytes:
    """Read the body, stopping the moment it exceeds the cap.

    Content-Length is a claim, not a guarantee -- a chunked upload has none at
    all -- so the limit is enforced again here rather than trusted once above.
    """
    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=_too_large())
        chunks.append(chunk)
    return b"".join(chunks)


def _too_large() -> dict:
    return {
        "error": "file is too large",
        "max_bytes": settings.max_upload_bytes,
    }

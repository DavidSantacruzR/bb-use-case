"""Ingest a file from a local path, through the same core flow as the API."""

import argparse
import json
import sys
from pathlib import Path

from .describer import ClaudeDescriber
from .service import UnsupportedFileType, ingest
from .settings import settings
from .storage import B2Storage


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ingest",
        description="Store a local file in Backblaze B2 with an AI-generated description.",
    )
    parser.add_argument("path", type=Path, help="path to a PNG, JPEG, or UTF-8 text file")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 2

    try:
        result = ingest(
            filename=args.path.name,
            data=args.path.read_bytes(),
            storage=B2Storage(
                key_id=settings.b2_key_id,
                app_key=settings.b2_app_key,
                bucket_name=settings.b2_bucket_name,
            ),
            describer=ClaudeDescriber(
                api_key=settings.anthropic_api_key,
                model=settings.model,
                max_text_chars=settings.max_text_chars,
            ),
            max_metadata_description_chars=settings.max_metadata_description_chars,
        )
    except UnsupportedFileType as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

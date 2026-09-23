"""Unit tests for the ingest flow and its pure helpers."""

import pytest

from blackblaze.service import (
    STATUS_COMPLETE,
    STATUS_NO_DESCRIPTION,
    UnsupportedFileType,
    build_key,
    detect_media_type,
    ingest,
)


class TestDetectMediaType:
    def test_recognises_a_png_by_its_signature(self, png_bytes):
        assert detect_media_type(png_bytes) == "image/png"

    def test_recognises_a_jpeg_by_its_signature(self, jpeg_bytes):
        assert detect_media_type(jpeg_bytes) == "image/jpeg"

    def test_treats_decodable_bytes_as_text(self, text_bytes):
        assert detect_media_type(text_bytes) == "text/plain"

    def test_rejects_bytes_that_are_neither_image_nor_utf8(self, undecodable_bytes):
        assert detect_media_type(undecodable_bytes) is None

    def test_ignores_the_claimed_extension(self):
        """A file named .png that is really text is text."""
        assert detect_media_type(b"not actually an image") == "text/plain"


class TestBuildKey:
    def test_keeps_the_readable_filename_in_the_key(self):
        assert build_key("quarterly-report.txt").endswith("/quarterly-report.txt")

    def test_strips_any_directory_component(self):
        """A client-supplied name must never steer where the object lands."""
        assert build_key("../../etc/passwd").endswith("/passwd")
        assert build_key(r"C:\Users\someone\notes.txt").endswith("/notes.txt")

    def test_replaces_characters_that_are_unsafe_in_a_key(self):
        # Each unsafe character maps to one underscore, so " (" becomes "__".
        assert build_key("my report (final).txt").endswith("/my_report__final_.txt")

    def test_falls_back_to_a_placeholder_when_nothing_safe_remains(self):
        assert build_key("!!!").endswith("/file")

    def test_truncates_a_very_long_filename(self):
        stem = build_key("a" * 500).rsplit("/", 1)[-1]
        assert len(stem) == 100

    def test_two_keys_for_the_same_filename_never_collide(self):
        assert build_key("report.txt") != build_key("report.txt")

    def test_starts_with_a_sortable_utc_timestamp(self):
        from datetime import datetime, timezone

        prefix = build_key("report.txt").split("-", 1)[0]
        parsed = datetime.strptime(prefix, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60


def run_ingest(storage, describer, *, filename="report.txt", data=b"hello", chars=500):
    return ingest(
        filename=filename,
        data=data,
        storage=storage,
        describer=describer,
        max_metadata_description_chars=chars,
    )


class TestIngestHappyPath:
    def test_reports_the_file_name_size_and_description(self, storage, describer):
        result = run_ingest(storage, describer, data=b"hello there")

        assert result.name == "report.txt"
        assert result.size == len(b"hello there")
        assert result.status == STATUS_COMPLETE
        assert result.description == "A warehouse floor seen from above."
        assert result.error is None

    def test_stores_the_bytes_under_the_returned_key(self, storage, describer):
        result = run_ingest(storage, describer, data=b"hello there")

        assert storage.stored[result.key]["data"] == b"hello there"

    def test_stores_the_sniffed_content_type_not_the_claimed_one(
        self, storage, describer, png_bytes
    ):
        result = run_ingest(storage, describer, filename="photo.txt", data=png_bytes)

        assert storage.stored[result.key]["content_type"] == "image/png"

    def test_describes_the_file_with_its_sniffed_media_type(
        self, storage, describer, png_bytes
    ):
        run_ingest(storage, describer, filename="photo.png", data=png_bytes)

        assert describer.calls == [(png_bytes, "image/png")]

    def test_attaches_the_description_to_the_stored_object(self, storage, describer):
        result = run_ingest(storage, describer)

        assert storage.metadata[result.key] == {
            "ai-description": "A%20warehouse%20floor%20seen%20from%20above.",
            "original-filename": "report.txt",
            "described-by": "claude-opus-5",
        }


class TestIngestMetadataEncoding:
    """B2 file_info travels as HTTP headers: ASCII-safe and small."""

    def test_percent_encodes_a_description_that_is_not_header_safe(
        self, storage, make_describer
    ):
        describer = make_describer(description="Café: 20° outside")
        result = run_ingest(storage, describer)

        stored = storage.metadata[result.key]["ai-description"]
        assert stored.isascii()
        assert stored == "Caf%C3%A9%3A%2020%C2%B0%20outside"

    def test_truncates_the_stored_description_to_the_configured_limit(
        self, storage, make_describer
    ):
        describer = make_describer(description="x" * 900)
        result = run_ingest(storage, describer, chars=500)

        assert storage.metadata[result.key]["ai-description"] == "x" * 500

    def test_the_caller_still_receives_the_untruncated_description(
        self, storage, make_describer
    ):
        describer = make_describer(description="x" * 900)
        result = run_ingest(storage, describer, chars=500)

        assert result.description == "x" * 900


class TestIngestFailureModes:
    def test_rejects_a_file_it_cannot_describe(
        self, storage, describer, undecodable_bytes
    ):
        with pytest.raises(UnsupportedFileType):
            run_ingest(storage, describer, filename="blob.bin", data=undecodable_bytes)

    def test_stores_nothing_when_the_file_type_is_unsupported(
        self, storage, describer, undecodable_bytes
    ):
        with pytest.raises(UnsupportedFileType):
            run_ingest(storage, describer, data=undecodable_bytes)

        assert storage.stored == {}

    def test_keeps_the_upload_when_the_description_is_unavailable(
        self, storage, unavailable_describer
    ):
        result = run_ingest(storage, unavailable_describer)

        assert result.status == STATUS_NO_DESCRIPTION
        assert result.key in storage.stored
        assert result.description is None
        assert "overloaded" in result.error

    def test_keeps_the_description_when_it_cannot_be_attached(self, storage, describer):
        storage.metadata_failure = RuntimeError("b2 rejected the copy")

        result = run_ingest(storage, describer)

        assert result.status == STATUS_NO_DESCRIPTION
        assert result.description == "A warehouse floor seen from above."
        assert "b2 rejected the copy" in result.error

    def test_a_storage_failure_is_not_swallowed(self, storage, describer):
        """Nothing is durable, so the caller must hear about it."""
        storage.store_failure = RuntimeError("b2 is unreachable")

        with pytest.raises(RuntimeError, match="b2 is unreachable"):
            run_ingest(storage, describer)


class TestIngestResultSerialisation:
    def test_to_dict_carries_every_field_the_api_returns(self, storage, describer):
        result = run_ingest(storage, describer).to_dict()

        assert set(result) == {"name", "size", "status", "key", "description", "error"}

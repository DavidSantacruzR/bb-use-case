"""Response assertions for the HTTP surface."""


class TestHealth:
    def test_reports_ok(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestUploadSucceeds:
    def test_returns_the_name_size_status_and_description(self, client, text_bytes):
        response = client.post(
            "/files", files={"file": ("report.txt", text_bytes, "text/plain")}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "report.txt"
        assert body["size"] == len(text_bytes)
        assert body["status"] == "complete"
        assert body["description"] == "A warehouse floor seen from above."
        assert body["error"] is None
        assert body["key"].endswith("/report.txt")

    def test_the_uploaded_bytes_reach_storage_intact(self, client, storage, png_bytes):
        response = client.post(
            "/files", files={"file": ("photo.png", png_bytes, "image/png")}
        )

        key = response.json()["key"]
        assert storage.stored[key]["data"] == png_bytes

    def test_the_description_is_attached_as_metadata(self, client, storage, text_bytes):
        response = client.post(
            "/files", files={"file": ("report.txt", text_bytes, "text/plain")}
        )

        key = response.json()["key"]
        assert storage.metadata[key]["ai-description"].startswith("A%20warehouse")

    def test_the_declared_content_type_does_not_override_sniffing(
        self, client, storage, png_bytes
    ):
        """A PNG announced as text/plain is still stored and described as a PNG."""
        response = client.post(
            "/files", files={"file": ("photo.png", png_bytes, "text/plain")}
        )

        key = response.json()["key"]
        assert storage.stored[key]["content_type"] == "image/png"


class TestUploadIsRejected:
    def test_an_undescribable_file_gets_415_and_the_accepted_types(
        self, client, undecodable_bytes
    ):
        response = client.post(
            "/files",
            files={"file": ("blob.bin", undecodable_bytes, "application/octet-stream")},
        )

        assert response.status_code == 415
        detail = response.json()["detail"]
        assert detail["accepted"] == ["image/png", "image/jpeg", "text/plain"]
        assert "unsupported file type" in detail["error"]

    def test_nothing_is_stored_when_the_type_is_unsupported(
        self, client, storage, undecodable_bytes
    ):
        client.post(
            "/files",
            files={"file": ("blob.bin", undecodable_bytes, "application/octet-stream")},
        )

        assert storage.stored == {}

    def test_an_oversized_upload_gets_413_and_the_limit(self, client):
        from blackblaze.settings import settings

        oversized = b"a" * (settings.max_upload_bytes + 1)

        response = client.post(
            "/files", files={"file": ("big.txt", oversized, "text/plain")}
        )

        assert response.status_code == 413
        assert response.json()["detail"] == {
            "error": "file is too large",
            "max_bytes": settings.max_upload_bytes,
        }

    def test_an_upload_comfortably_under_the_limit_is_accepted(
        self, client, monkeypatch
    ):
        """The Content-Length guard measures the whole multipart envelope, not
        just the file, so a file near the cap can still be refused. Anything
        well under it must get through."""
        from blackblaze import api

        monkeypatch.setattr(api.settings, "max_upload_bytes", 4096)

        response = client.post(
            "/files", files={"file": ("small.txt", b"a" * 1024, "text/plain")}
        )

        assert response.status_code == 200

    def test_an_oversized_body_is_caught_without_a_content_length(
        self, client, monkeypatch
    ):
        """A chunked upload declares no length, so the streaming guard is the
        only thing standing between it and memory."""
        from blackblaze import api

        monkeypatch.setattr(api.settings, "max_upload_bytes", 1024)
        boundary = "boundary123"
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="big.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()

        def chunks():
            yield head
            yield b"a" * 4096
            yield tail

        response = client.post(
            "/files",
            content=chunks(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )

        assert response.status_code == 413
        assert "content-length" not in {
            k.lower() for k in response.request.headers
        }

    def test_a_missing_file_field_gets_422(self, client):
        response = client.post("/files")

        assert response.status_code == 422


class TestUploadDegrades:
    def test_a_file_that_could_not_be_described_is_still_stored(
        self, storage, unavailable_describer, text_bytes
    ):
        from fastapi.testclient import TestClient

        from blackblaze.api import app, get_describer, get_storage

        app.dependency_overrides[get_storage] = lambda: storage
        app.dependency_overrides[get_describer] = lambda: unavailable_describer
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/files", files={"file": ("report.txt", text_bytes, "text/plain")}
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "stored_without_description"
        assert body["description"] is None
        assert "overloaded" in body["error"]
        assert body["key"] in storage.stored

    def test_a_metadata_failure_still_returns_the_description(
        self, client, storage, text_bytes
    ):
        storage.metadata_failure = RuntimeError("b2 rejected the copy")

        response = client.post(
            "/files", files={"file": ("report.txt", text_bytes, "text/plain")}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "stored_without_description"
        assert body["description"] == "A warehouse floor seen from above."
        assert "b2 rejected the copy" in body["error"]


class TestDemoPage:
    def test_the_index_page_is_served(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

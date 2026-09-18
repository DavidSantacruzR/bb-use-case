# blackblaze

Accepts a file, stores it in Backblaze B2, generates a short AI description of
its contents, attaches that description to the stored object as metadata, and
returns it alongside the file name, size and status.

A caption for an image, a summary for text.

## Setup

Requires Python 3.14 and Poetry.

```bash
poetry install
cp .env.example .env   # then fill it in
```

| Variable | Purpose |
| --- | --- |
| `B2_KEY_ID` / `B2_APP_KEY` | A B2 application key with read/write access to the bucket |
| `B2_BUCKET_NAME` | An existing private bucket; the service resolves it, never creates it |
| `ANTHROPIC_API_KEY` | Used to generate descriptions |

A missing key fails at startup rather than midway through someone's upload.

## Running

```bash
poetry run python main.py
```

Defaults to `127.0.0.1:8000` with reload on; `HOST`, `PORT` and `RELOAD`
override it. Equivalent to `poetry run uvicorn blackblaze.api:app --reload`.

`http://localhost:8000` serves an upload page. `http://localhost:8000/docs` has
the generated API reference.

### Endpoint

```bash
curl -F "file=@photo.jpg" http://localhost:8000/files
```

```json
{
  "name": "photo.jpg",
  "size": 148213,
  "status": "complete",
  "key": "20260918T165540Z-083c12ba-.../photo.jpg",
  "description": "A tabby cat asleep in a patch of sunlight on a wooden floor.",
  "error": null
}
```

### CLI

```bash
poetry run ingest ./notes.txt
```

Same core flow as the endpoint, for files already on this machine.

## Accepted files

PNG, JPEG, and UTF-8 text, up to 10 MB. Anything else is rejected with `415`,
anything larger with `413`.

Type is determined by **sniffing the file's magic bytes**, not by its extension
or by the `Content-Type` the client claims. A `.png` that is really a zip is
rejected.

## Design notes

**Storage happens before description, which costs a second write.** B2 objects
are immutable, so metadata cannot be edited in place — attaching the description
means copying the object onto a new version with new metadata (passing both
`content_type` and `file_info` is what triggers B2's `REPLACE` directive rather
than carrying the source metadata over).

Describing the file first and uploading once would avoid that second write, but
this order buys a better failure story: the file is durable before the AI
provider is involved, so a failed description leaves a real stored object that
can be re-described rather than a dropped upload.

**Failures degrade instead of erroring.** If the description or the metadata
copy fails, the response is still `200` — with `status:
"stored_without_description"` and an `error` field. The file *is* stored, which
is the caller's main concern, and returning a `500` after a successful durable
write would misreport what happened. The two statuses are `complete` and
`stored_without_description`.

**Object keys are `{timestamp}-{uuid4}/{filename}`.** The UUID makes collisions
impossible; the timestamp makes a bucket listing sort chronologically and stay
readable. Filenames are sanitised down to a single path segment, so a caller
cannot steer the key with `../`.

**The description is truncated to 500 characters and percent-encoded** before it
goes into B2 metadata, because `file_info` values travel as HTTP headers: they
must be ASCII-safe and cap at roughly 2KB across all keys. An emoji in a caption
would otherwise fail the upload. The full, untruncated description is returned in
the response body. Stored alongside it: `original-filename` and `described-by`
(the model id), so a wrong-looking caption can be traced to the model that wrote
it.

**The model is `claude-opus-5` at low effort**, with `max_tokens` capped at 150 —
captioning is a short, well-specified task, and the request is synchronous so
latency is user-visible. A refusal (`stop_reason: "refusal"`) is handled as a
missing description, not a crash.

## Deliberately out of scope

Written as an exercise, so some things are named rather than built:

- **No tests.** The seams are in place for them — `service.ingest()` takes a
  `Storage` protocol and a describer, so both are substitutable — but nothing is
  wired up.
- **`POST /files` accepts an uploaded file only.** Local paths go through the
  CLI instead. Accepting a server-side filesystem path from an HTTP caller is
  arbitrary file read, which is not something to ship even in an exercise.
- **Synchronous.** No job queue, so the caller waits out the round trip.
- **10 MB cap**, which avoids multipart upload handling entirely.

### Next

WebP and GIF (one string each — Claude's vision supports both); PDF via native
document content blocks; presigned download URLs in the response; an async
`202 + job id` variant; multipart for larger files.

"""Start the service.

    poetry run python main.py

HOST, PORT and RELOAD can override the defaults. Passed as an import string so
reload works.
"""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "blackblaze.api:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "true").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import ee

# GEE + Drive scopes — Drive is required for batch chip export.
# The first run after adding Drive scope will trigger a browser re-auth.
GEE_SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/drive",
]

_CREDENTIALS_PATH = Path.home() / ".config" / "earthengine" / "credentials"

DEFAULT_PROJECT = "gen-lang-client-0350293091"


def authenticate() -> None:
    """Runs browser-based OAuth flow with GEE + Drive scopes.

    Only needs to run once (or when scopes change). Credentials are stored at:
      Windows: C:\\Users\\<user>\\.config\\earthengine\\credentials
    """
    ee.Authenticate(scopes=GEE_SCOPES)


def initialize(project: str | None = None) -> None:
    """Initializes the GEE client using saved credentials."""
    ee.Initialize(project=project or DEFAULT_PROJECT)
    print("Google Earth Engine initialized successfully.")


def authenticate_and_initialize(project: str | None = None) -> None:
    """Authenticate only when credentials are absent, then initialize GEE."""
    if not _CREDENTIALS_PATH.exists():
        authenticate()
    initialize(project=project)


def get_drive_credentials():
    """Returns Google OAuth2 Credentials for Drive API, reusing the GEE token.

    Requires that authenticate() was called with GEE_SCOPES (includes Drive).
    If the stored token pre-dates Drive scope, re-run authenticate() once.
    """
    from google.oauth2.credentials import Credentials

    if not _CREDENTIALS_PATH.exists():
        raise RuntimeError(
            f"GEE credentials not found at {_CREDENTIALS_PATH}. "
            "Run authenticate_and_initialize() first."
        )
    with open(_CREDENTIALS_PATH) as f:
        data = json.load(f)

    return Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GEE_SCOPES,
    )


if __name__ == "__main__":
    authenticate_and_initialize()
    result = ee.Number(42).getInfo()
    assert result == 42, f"Unexpected result: {result}"
    print("Auth smoke test passed.")

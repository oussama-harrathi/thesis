import os

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "true"

from app.core.config import Settings
from app.main import app


client = TestClient(app)


def test_loopback_preflight_is_allowed() -> None:
    response = client.options(
        "/api/v1/courses",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_comma_separated_cors_origins_are_normalized() -> None:
    settings = Settings(CORS_ORIGINS="http://localhost:3000/, http://127.0.0.1:3000")

    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

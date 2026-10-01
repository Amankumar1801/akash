from akash_api.main import create_app
from fastapi.testclient import TestClient


def test_health():
    r = TestClient(create_app()).get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "does not independently establish" in body["disclaimer"]

from akash_ml.registry import save_system
from conftest import H


def test_empty_registry_lists_nothing(client, keys):
    assert client.get("/v1/models", headers=H(keys["viewer"])).json() == []
    assert client.get("/v1/models/transit/v1", headers=H(keys["viewer"])).status_code == 404


def test_models_are_listed_with_provenance_fields_and_details(client, services, system, keys):
    save_system(services.registry_root, "transit-api", "v1", system)
    rows = client.get("/v1/models", headers=H(keys["viewer"])).json()
    assert len(rows) == 1 and rows[0]["name"] == "transit-api" and rows[0]["version"] == "v1"
    assert rows[0]["feature_version"] == "tf@1" and len(rows[0]["data_hash"]) == 64
    d = client.get("/v1/models/transit-api/v1", headers=H(keys["viewer"])).json()
    assert d["metadata"]["split_manifest_digest"] and d["model_card"] is None
    (services.registry_root / "transit-api" / "v1" / "MODEL_CARD.md").write_text("# card")
    assert client.get("/v1/models/transit-api/v1", headers=H(keys["viewer"])).json()["model_card"] == "# card"


def test_registry_paths_cannot_escape(client, services, system, keys):
    save_system(services.registry_root, "transit-api", "v1", system)
    (services.registry_root.parent / "secret").mkdir()
    (services.registry_root.parent / "secret" / "metadata.json").write_text('{"leak": true}')
    # NB: HTTP clients normalise "/a/.." away before sending, so literal ".." URLs would silently
    # hit a different route; the validator itself is tested directly below.
    for path in ("/v1/models/%2e%2e/secret", "/v1/models/%2e%2e/%2e%2e",
                 "/v1/models/transit-api/%2e%2e%2f%2e%2e%2fsecret", "/v1/models/.hidden/v1",
                 "/v1/models/a b/v1", "/v1/models/transit-api/v1%00"):
        r = client.get(path, headers=H(keys["viewer"]))
        assert r.status_code in (404, 422) and "leak" not in r.text, path


def test_model_dir_validator_rejects_traversal_regardless_of_the_http_client(services, system):
    import pytest
    from akash_api.errors import ApiError
    from akash_api.routers.models import _model_dir
    save_system(services.registry_root, "transit-api", "v1", system)
    (services.registry_root.parent / "secret").mkdir()
    for name, version in [("..", "v1"), ("transit-api", ".."), (".", "v1"), ("transit-api", "."),
                          ("../secret", "x"), ("transit-api", "../../secret"), ("a/b", "v1"),
                          ("transit-api", "v1/../../x"), ("", "v1"), (".hidden", "v1"),
                          ("transit-api\\x00", "v1"), ("x" * 100, "v1"), ("transit-api", "nope")]:
        with pytest.raises(ApiError) as e:
            _model_dir(services, name, version)
        assert e.value.status == 404, (name, version)
    assert _model_dir(services, "transit-api", "v1").name == "v1"  # the legitimate path works
    services.registry_root = None
    with pytest.raises(ApiError):
        _model_dir(services, "transit-api", "v1")


def test_models_require_authentication(client):
    assert client.get("/v1/models").status_code == 401

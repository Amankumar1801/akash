"""Static guards on the deployment files. They cannot prove an image builds (CI does that); they
stop the safety properties from being edited away unnoticed."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "infra/docker/api.Dockerfile").read_text()
WEB = (ROOT / "infra/docker/web.Dockerfile").read_text()
NGINX = (ROOT / "infra/docker/nginx.conf").read_text()
COMPOSE = yaml.safe_load((ROOT / "infra/compose/docker-compose.prod.yml").read_text())


def test_api_image_is_non_root_single_worker_and_has_a_healthcheck():
    assert "USER akash" in API and "--uid 10001" in API
    assert '"--workers", "1"' in API  # in-process jobs + one SQLite owner
    assert "HEALTHCHECK" in API and "/v1/ready" in API
    assert "--no-editable" in API and "--frozen" in API and "--no-dev" in API


def test_images_pin_their_tooling():
    assert "uv:0.11.32" in API and ":latest" not in API + WEB
    assert "nginx-unprivileged" in WEB and "npm ci" in WEB


def test_compose_hardens_both_services_and_hides_the_api():
    svc = COMPOSE["services"]
    for s in svc.values():
        assert s["read_only"] is True and s["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in s["security_opt"]
    assert "ports" not in svc["api"] and svc["api"]["expose"] == ["8000"]  # only nginx is public
    assert svc["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert any(str(v).endswith(":/models:ro") for v in svc["api"]["volumes"])  # models read-only
    assert COMPOSE["volumes"]["akash-data"] == {}


def test_nginx_keeps_sse_unbuffered_and_sets_security_headers():
    assert "proxy_buffering off" in NGINX and "proxy_read_timeout" in NGINX
    for h in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy",
              "X-Frame-Options"):
        assert h in NGINX
    assert "default-src 'none'" in NGINX and "frame-ancestors 'none'" in NGINX
    assert "'unsafe-eval'" not in NGINX and "script-src 'self'" in NGINX
    assert "server_tokens off" in NGINX


def test_no_secrets_in_committed_env_examples_or_ignore_rules():
    ex = (ROOT / "infra/compose/prod.env.example").read_text()
    for line in ex.splitlines():
        if line.startswith("AKASH_LLM_API_KEY="):
            assert line == "AKASH_LLM_API_KEY="
    ign = (ROOT / ".dockerignore").read_text()
    assert ".env" in ign and ".git" in ign and "data" in ign
    assert ".env" in (ROOT / ".gitignore").read_text()

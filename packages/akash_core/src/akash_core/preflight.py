"""Configuration checks that turn a misconfigured deployment into a loud startup failure.

`errors` stop a production start. `warnings` are reported and allowed. Nothing here reads or prints
secret values."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import Settings

ENVS = ("dev", "test", "staging", "prod")


@dataclass(frozen=True)
class Finding:
    level: Literal["error", "warning"]
    code: str
    message: str


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".akash-write-test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def check(s: Settings) -> list[Finding]:
    f: list[Finding] = []

    def err(code: str, msg: str) -> None:
        f.append(Finding("error", code, msg))

    def warn(code: str, msg: str) -> None:
        f.append(Finding("warning", code, msg))

    if s.env not in ENVS:
        err("bad_env", f"AKASH_ENV must be one of {', '.join(ENVS)}")
    prod = s.env == "prod"
    origins = [o.strip() for o in s.api_cors_origins.split(",") if o.strip()]
    if "*" in origins:
        (err if prod else warn)("cors_wildcard", "CORS must list explicit origins, not '*'")
    if prod and any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
                    for o in origins):
        err("cors_http", "production CORS origins must be https")
    if not _writable(Path(s.data_dir)):
        err("data_dir", "the data directory is not writable")
    try:
        if not Path(s.sqlite_path).resolve().is_relative_to(Path(s.data_dir).resolve()):
            warn("sqlite_outside_data", "the database is outside the data directory, so it is "
                                        "not covered by the volume or backup you configured")
    except OSError:
        pass
    if s.transit_model:
        if "/" not in s.transit_model:
            err("transit_model", "AKASH_TRANSIT_MODEL must look like name/version")
        elif not (Path(s.registry_root) / s.transit_model / "metadata.json").is_file():
            err("transit_model_missing", "the configured transit model is not in the registry")
    elif prod:
        warn("no_classifier", "no transit model configured: investigations run without the "
                              "classifier")
    if s.anomaly_reference and not Path(s.anomaly_reference).exists():
        err("anomaly_reference_missing", "the configured anomaly reference file does not exist")
    if s.llm_api_key:
        if not s.llm_model:
            err("llm_model", "an LLM key is set but AKASH_LLM_MODEL is empty")
        if not s.llm_base_url.startswith("https://"):
            err("llm_https", "the LLM base URL must be https when a key is set")
    if prod and not s.contact_email:
        warn("contact_email", "AKASH_CONTACT_EMAIL is empty: archives cannot contact you about "
                              "heavy use")
    for name in ("api_rate_per_min", "api_investigation_rate_per_min", "api_agent_rate_per_min",
                 "api_experiment_rate_per_min", "api_report_rate_per_min", "api_label_rate_per_min",
                 "api_max_concurrent_jobs", "api_max_body_bytes"):
        if getattr(s, name) <= 0:
            err("limit_" + name, f"{name} must be positive")
    if s.api_executor not in ("thread", "queue"):
        err("executor_invalid", "api_executor must be 'thread' or 'queue'")
    if s.api_executor == "queue":
        warn("queue_needs_worker", "api_executor=queue only enqueues jobs; run `python -m "
             "akash_api.queue_worker` on a host that shares the SQLite file, or nothing will run")
        if s.worker_lease_s < 10 or s.worker_max_attempts < 1:
            err("worker_limits",
                "worker_lease_s must be at least 10 and worker_max_attempts at least 1")
    if s.api_max_concurrent_jobs > 8:
        warn("jobs_high", "more than 8 concurrent in-process jobs will starve the API")
    if prod and os.environ.get("AKASH_DATABASE_URL", "").startswith("postgresql"):
        warn("postgres_unused", "AKASH_DATABASE_URL is set but the API currently uses SQLite")
    return f


class ConfigError(Exception):
    pass


def enforce(s: Settings) -> list[Finding]:
    """Raise on errors in production; always return the findings."""
    found = check(s)
    errs = [x for x in found if x.level == "error"]
    if errs and s.env == "prod":
        raise ConfigError("; ".join(f"{x.code}: {x.message}" for x in errs))
    return found

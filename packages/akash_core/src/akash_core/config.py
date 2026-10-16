from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AKASH_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://akash:akash@localhost:5432/akash"
    redis_url: str = "redis://localhost:6379/0"
    object_store_uri: str = "file://./data/objects"
    mlflow_tracking_uri: str = "http://localhost:5000"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    pipeline_version: str = "0.0.1"
    data_dir: str = "./data"
    sqlite_path: str = "./data/akash.sqlite3"
    contact_email: str = ""  # included in the User-Agent so archives can reach you
    registry_root: str = "./models"
    api_rate_per_min: int = 120  # general per-principal limit
    api_investigation_rate_per_min: int = 10  # expensive endpoint
    api_experiment_rate_per_min: int = 3
    api_label_rate_per_min: int = 60
    api_report_rate_per_min: int = 30
    api_agent_rate_per_min: int = 20  # model calls cost money
    api_max_body_bytes: int = 1_000_000
    api_max_concurrent_jobs: int = 2
    # "thread" runs jobs in the API process; "queue" leaves them for worker processes
    api_executor: str = "thread"
    worker_lease_s: float = 60.0  # a worker that stops heartbeating loses its job after this long
    worker_max_attempts: int = 3
    worker_poll_s: float = 1.0
    api_sse_poll_interval_s: float = 0.25
    api_sse_max_seconds: float = 900.0
    api_cors_origins: str = ""  # comma-separated; empty = no CORS
    transit_model: str = ""  # "name/version" in the registry; empty = classifier disabled
    anomaly_reference: str = ""  # path to a saved reference population; empty = disabled

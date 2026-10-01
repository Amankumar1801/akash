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

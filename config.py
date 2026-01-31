from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Fund Viewer 2"
    host: str = "127.0.0.1"
    port: int = 8600
    users: str = "admin:admin"
    max_favour: int = 100
    base_url: str = "http://127.0.0.1:8600"
    favour_init: List[str] = ["004703", "000979"]
    state_db: str = "data/state.db"
    # Rate limiting settings to prevent being blocked by API providers
    max_concurrent_requests: int = 3  # Maximum number of concurrent requests to external APIs
    request_delay_ms: int = 100  # Delay in milliseconds between request batches


settings = Settings()

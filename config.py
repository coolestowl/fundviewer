from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Fund Viewer 2"
    host: str = "127.0.0.1"
    port: int = 8600
    users: str = "admin:admin"
    max_favour: int = 10
    base_url: str = "http://127.0.0.1:8600"
    favour_init: List[str] = ["004703"]
    state_db: str = "data/state.db"


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    mock_mode: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    ble_device_name: str = "SigMesh"
    ble_scan_timeout: float = 10.0
    ble_reconnect_delay: float = 2.0
    ble_reconnect_max_retries: int = 10
    measurement_interval: float = 0.5
    log_level: str = "warning"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

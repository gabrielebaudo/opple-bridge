from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    mock_mode: bool = True
    host: str = "0.0.0.0"
    port: int = 80
    reload: bool = False
    ble_device_name: str = "SigMesh"
    ble_scan_timeout: float = 10.0
    ble_reconnect_delay: float = 2.0
    ble_reconnect_max_retries: int = 10
    measurement_interval: float = 0.5
    log_level: str = "warning"
    wifi_config_path: str = "/etc/opple-bridge/wifi.yaml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

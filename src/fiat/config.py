import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import keyring

CONFIG_DIR = Path.home() / ".fiat"
CONFIG_FILE = CONFIG_DIR / "config.json"
APP_NAME = "fiat_cli"

@dataclass
class AuthConfig:
    method: str  # "api_key" or "oauth"

@dataclass
class ProviderConfig:
    provider_name: str
    model_name: str
    auth: AuthConfig

def get_keyring_key(provider_name: str) -> str:
    return f"{provider_name.lower()}_api_key"

def save_credential(provider_name: str, secret: str):
    keyring.set_password(APP_NAME, get_keyring_key(provider_name), secret)

def get_credential(provider_name: str) -> Optional[str]:
    env_var = f"{provider_name.upper()}_API_KEY"
    if os.environ.get(env_var):
        return os.environ.get(env_var)
    try:
        return keyring.get_password(APP_NAME, get_keyring_key(provider_name))
    except Exception:
        return None

def load_config() -> Optional[ProviderConfig]:
    if not CONFIG_FILE.exists():
        return None
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return ProviderConfig(
            provider_name=data.get("provider_name"),
            model_name=data.get("model_name"),
            auth=AuthConfig(method=data.get("auth_method", "api_key"))
        )
    except Exception:
        return None

def save_config(config: ProviderConfig):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "provider_name": config.provider_name,
            "model_name": config.model_name,
            "auth_method": config.auth.method
        }, f, indent=4)

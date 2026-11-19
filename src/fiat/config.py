import json
import os
from dataclasses import dataclass
from pathlib import Path

import keyring

CONFIG_DIR = Path.home() / ".fiat"
CONFIG_FILE = CONFIG_DIR / "config.json"
APP_NAME = "fiat_cli"
_PROVIDER_ENV_ALIASES = {
    "huggingface": ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"),
    "nvidia_nim": ("NVIDIA_API_KEY",),
}

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

def get_credential(provider_name: str) -> str | None:
    normalized_name = provider_name.strip().lower().replace("-", "_").replace(" ", "_")
    env_var = f"{normalized_name.upper()}_API_KEY"
    if os.environ.get(env_var):
        return os.environ.get(env_var)
    for alias in _PROVIDER_ENV_ALIASES.get(normalized_name, ()):
        if os.environ.get(alias):
            return os.environ.get(alias)
    try:
        return keyring.get_password(APP_NAME, get_keyring_key(normalized_name))
    except Exception:
        return None

def load_config() -> ProviderConfig | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        with CONFIG_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        provider_name = data.get("provider_name")
        model_name = data.get("model_name")
        if not isinstance(provider_name, str) or not provider_name:
            return None
        if not isinstance(model_name, str) or not model_name:
            return None
        return ProviderConfig(
            provider_name=provider_name,
            model_name=model_name,
            auth=AuthConfig(method=data.get("auth_method", "api_key"))
        )
    except Exception:
        return None

def save_config(config: ProviderConfig):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump({
            "provider_name": config.provider_name,
            "model_name": config.model_name,
            "auth_method": config.auth.method
        }, f, indent=4)

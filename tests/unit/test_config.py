import json

from fiat import config


def test_save_and_load_config_uses_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".fiat")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / ".fiat" / "config.json")
    expected = config.ProviderConfig(
        provider_name="OpenAI",
        model_name="gpt-4o-mini",
        auth=config.AuthConfig(method="api_key"),
    )

    config.save_config(expected)

    assert config.load_config() == expected
    assert json.loads(config.CONFIG_FILE.read_text())["provider_name"] == "OpenAI"


def test_load_config_returns_none_for_malformed_json(tmp_path, monkeypatch):
    file_path = tmp_path / "config.json"
    file_path.write_text("not json")
    monkeypatch.setattr(config, "CONFIG_FILE", file_path)

    assert config.load_config() is None


def test_environment_credential_takes_precedence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setattr(config.keyring, "get_password", lambda *_: "keyring-key")

    assert config.get_credential("openai") == "environment-key"

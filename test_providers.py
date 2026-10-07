import unittest
from unittest.mock import patch, MagicMock
from fiat.config import ProviderConfig, AuthConfig, save_config, load_config, get_credential, save_credential, CONFIG_FILE, CONFIG_DIR
from fiat.provider_factory import ProviderFactory
from fiat.cli import FiatCore

class TestProviders(unittest.TestCase):
    def setUp(self):
        # ensure config uses a different file for testing
        self.old_config_file = CONFIG_FILE
    
    def tearDown(self):
        # clean up mock config if it exists
        if CONFIG_FILE.exists() and CONFIG_FILE != self.old_config_file:
            CONFIG_FILE.unlink()

    @patch('fiat.config.CONFIG_FILE', new_callable=lambda: CONFIG_DIR / "test_config.json")
    def test_config_save_load(self, mock_file):
        cfg = ProviderConfig(provider_name="Gemini", model_name="gemini-3.5-flash-lite", auth=AuthConfig(method="api_key"))
        save_config(cfg)
        loaded = load_config()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.provider_name, "Gemini")
        self.assertEqual(loaded.model_name, "gemini-3.5-flash-lite")
        self.assertEqual(loaded.auth.method, "api_key")

    @patch('fiat.config.keyring.get_password')
    @patch('fiat.config.keyring.set_password')
    def test_credential_storage(self, mock_set, mock_get):
        mock_get.return_value = "mock_secret"
        save_credential("MockProvider", "mock_secret")
        mock_set.assert_called_with("fiat_cli", "mockprovider_api_key", "mock_secret")
        
        val = get_credential("MockProvider")
        self.assertEqual(val, "mock_secret")
        mock_get.assert_called_with("fiat_cli", "mockprovider_api_key")

    def test_provider_factory(self):
        sys_prompt = "test prompt"
        p_gemini = ProviderFactory.create("Gemini", sys_prompt)
        self.assertEqual(p_gemini.name, "Gemini")
        
        p_openai = ProviderFactory.create("OpenAI", sys_prompt)
        self.assertEqual(p_openai.name, "OpenAI")
        
        p_anth = ProviderFactory.create("Anthropic", sys_prompt)
        self.assertEqual(p_anth.name, "Anthropic")

        p_openr = ProviderFactory.create("OpenRouter", sys_prompt)
        self.assertEqual(p_openr.name, "OpenRouter")
        
        p_groq = ProviderFactory.create("Groq", sys_prompt)
        self.assertEqual(p_groq.name, "Groq")

    def test_fiat_core_setup(self):
        core = FiatCore()
        cfg = ProviderConfig(provider_name="OpenAI", model_name="gpt-4o", auth=AuthConfig(method="api_key"))
        core.setup_provider(cfg, "fake_key")
        
        self.assertEqual(core.provider.name, "OpenAI")
        self.assertEqual(core.provider.model, "gpt-4o")
        self.assertEqual(core.provider.api_key, "fake_key")
        self.assertTrue(len(core.provider.tools) > 0)
        
if __name__ == "__main__":
    unittest.main()

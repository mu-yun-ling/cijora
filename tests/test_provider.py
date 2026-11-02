"""Verify provider-specific modes without making network requests."""
import unittest
from unittest.mock import patch
from src.provider import Provider


class ProviderModeTests(unittest.TestCase):
    def payload(self, base_url='https://api.deepseek.com/v1', model='deepseek-flash', structured=False, **extra):
        config = dict(base_url=base_url, model=model, temperature=0.7, max_tokens=2048, **extra)
        with patch('src.provider.create_http_client'):
            with Provider(config) as provider:
                return provider.payload([{'role': 'user', 'content': '你好'}], stream=True, structured=structured)

    def test_official_flash_old_settings_use_instant_chat(self):
        payload = self.payload()
        self.assertEqual({'type': 'disabled'}, payload['thinking'])
        self.assertEqual(0.7, payload['temperature'])
        self.assertTrue(payload['stream'])

    def test_explicit_chat_thinking_omits_ignored_temperature(self):
        payload = self.payload(chat_thinking=True)
        self.assertEqual({'type': 'enabled'}, payload['thinking'])
        self.assertNotIn('temperature', payload)

    def test_other_models_and_compatible_hosts_keep_generic_payload(self):
        for base, model in [('https://proxy.test/v1', 'deepseek-flash'),
                            ('https://api.deepseek.com.evil.test', 'deepseek-flash'),
                            ('https://api.deepseek.com', 'deepseek-v4-pro'),
                            ('http://127.0.0.1:11434/v1', 'local')]:
            payload = self.payload(base_url=base, model=model, chat_thinking=True)
            self.assertNotIn('thinking', payload)
            self.assertEqual(0.7, payload['temperature'])

    def test_structured_design_and_diary_keep_existing_mode(self):
        payload = self.payload(structured=True, chat_thinking=False)
        self.assertNotIn('thinking', payload)
        self.assertEqual(0.3, payload['temperature'])

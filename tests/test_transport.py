"""Proxy parsing and client ownership tests; no network calls."""
import unittest
from unittest.mock import patch
from src.llm.transport import parse_windows_proxy_server, windows_proxy_addresses


class ProxyTests(unittest.TestCase):
    def test_shared_windows_proxy_uses_http_connect(self):
        self.assertEqual({"http://": "http://127.0.0.1:7890", "https://": "http://127.0.0.1:7890"},
                         parse_windows_proxy_server("127.0.0.1:7890"))

    def test_destination_scheme_is_not_proxy_transport(self):
        self.assertEqual({"http://": "http://proxy.test:80", "https://": "http://proxy.test:80"},
                         parse_windows_proxy_server("http=proxy.test:80;https=proxy.test:80"))

    def test_explicit_secure_proxy_is_preserved(self):
        self.assertEqual({"https://": "https://secure-proxy.test:443"},
                         parse_windows_proxy_server("https=https://secure-proxy.test:443"))
        self.assertEqual({"http://": "https://secure-proxy.test:443", "https://": "https://secure-proxy.test:443"},
                         parse_windows_proxy_server("https://secure-proxy.test:443"))

    def test_empty_and_unknown_protocol_entries_are_ignored(self):
        self.assertEqual({}, parse_windows_proxy_server(""))
        self.assertEqual({"https://": "http://proxy.test:80"},
                         parse_windows_proxy_server("ftp=ftp.test:21; https=proxy.test:80; http="))

    def test_environment_configuration_retains_precedence(self):
        for environment in ({"https": "https://explicit.test:443"}, {"no": "localhost"}):
            with patch("src.llm.transport.sys.platform", "win32"), patch(
                    "src.llm.transport.getproxies_environment", return_value=environment):
                self.assertEqual({}, windows_proxy_addresses())

    def test_non_windows_keeps_default_transport(self):
        with patch("src.llm.transport.sys.platform", "linux"):
            self.assertEqual({}, windows_proxy_addresses())


if __name__ == "__main__":
    unittest.main()

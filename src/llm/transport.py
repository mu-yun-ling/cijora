"""Preserve Windows HTTP CONNECT proxy semantics without changing system settings."""
import sys
from urllib.request import getproxies_environment
import httpx


def parse_windows_proxy_server(value):
    """Registry protocol names describe destinations, not proxy TLS transport.

    An address without an explicit scheme is an HTTP proxy, including the
    address assigned to HTTPS destinations. Explicit proxy schemes are kept.
    """
    value = value.strip()
    if not value:
        return {}
    parts = [part.strip() for part in value.split(";") if part.strip()]
    protocol_settings = any(part.partition("=")[0].lower() in ("http", "https", "all")
                            and "=" in part for part in parts)
    addresses = {}
    if protocol_settings:
        for part in parts:
            scheme, separator, address = part.partition("=")
            if separator and scheme.strip().lower() in ("http", "https", "all") and address.strip():
                addresses[scheme.strip().lower() + "://"] = address.strip()
    else:
        addresses = {"http://": value, "https://": value}
    return {scheme: address if "://" in address else "http://" + address
            for scheme, address in addresses.items()}


def windows_proxy_addresses():
    # Match urllib's precedence exactly, including a standalone NO_PROXY value.
    if sys.platform != "win32" or getproxies_environment():
        return {}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return {}
            return parse_windows_proxy_server(str(winreg.QueryValueEx(key, "ProxyServer")[0]))
    except (ImportError, OSError, ValueError, TypeError):
        return {}


def create_http_client():
    mounts = {scheme: httpx.HTTPTransport(proxy=address, trust_env=True)
              for scheme, address in windows_proxy_addresses().items()}
    # Verification and environment CA configuration retain httpx defaults.
    return httpx.Client(mounts=mounts, timeout=25, trust_env=True)

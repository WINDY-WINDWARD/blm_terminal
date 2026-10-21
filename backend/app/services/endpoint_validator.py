"""Validation and security helpers for custom endpoints and credentials.

Enforces:
- HTTP(S) only schemes
- Reject userinfo, malformed URLs, non-HTTP schemes
- Reject header injection (CR/LF in URLs, header names, or header values)
- Reject cloud metadata hosts and link-local IP addresses (IPv4 & IPv6, including numeric/hex representations)
- Accept public, private, and localhost addresses with explicit warning flags
- Credential and identity masking helpers
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

CLOUD_METADATA_HOSTS: set[str] = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
    "metadata.azure.com",
}

AWS_IMDSV6_ADDR = "fd00:ec2::254"


def _parse_host_ip(host_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Attempt to parse a hostname as an IPv4 or IPv6 address, including bracketed and integer forms."""
    clean = host_str.strip().strip("[]")
    if not clean:
        return None

    # Standard IP address format
    try:
        return ipaddress.ip_address(clean)
    except ValueError:
        pass

    # Decimal or hex integer IPv4 format (e.g. 2852039166 or 0xa9fea9fe)
    try:
        if clean.startswith("0x") or clean.startswith("0X") or clean.isdigit():
            val = int(clean, 0)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
    except ValueError:
        pass

    return None


def validate_custom_endpoint_url(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Validate a custom endpoint URL and optional headers against security constraints.

    Returns:
        tuple of (normalized_url, warning_flags)

    Raises:
        ValueError if the URL or headers violate security policies.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Custom endpoint URL cannot be empty.")

    # 1. Header/request injection check: CR/LF in URL
    if "\r" in url or "\n" in url or "\0" in url:
        raise ValueError("URL contains illegal control characters (CR/LF/NULL).")

    # 2. Header injection check in headers dictionary
    if headers:
        for k, v in headers.items():
            k_str = str(k)
            v_str = str(v)
            if "\r" in k_str or "\n" in k_str or "\0" in k_str:
                raise ValueError("Header name contains illegal control characters.")
            if "\r" in v_str or "\n" in v_str or "\0" in v_str:
                raise ValueError(f"Header value for '{k_str}' contains illegal control characters.")

    # 3. Scheme and URL structure validation
    parsed = urlsplit(url.strip())
    if parsed.query or parsed.fragment:
        raise ValueError("Endpoint URLs cannot contain query strings or fragments; use secret headers instead.")
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{scheme}'. Only HTTP and HTTPS are permitted.")

    if not parsed.netloc:
        raise ValueError("Malformed URL: missing host or network location.")

    # 4. Userinfo check (user:pass@host)
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("Userinfo (username/password credentials in URL) is not permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Malformed URL: could not extract hostname.")

    norm_host = hostname.lower().rstrip(".")

    # 5. Cloud metadata hostname rejection
    if norm_host in CLOUD_METADATA_HOSTS:
        raise ValueError("Access to cloud metadata endpoints is prohibited.")

    warning_flags: list[str] = []

    # 6. IP address checks
    ip = _parse_host_ip(norm_host)
    if ip is not None:
        # Check link-local / cloud metadata IP
        if ip.is_link_local:
            raise ValueError(f"Access to link-local IP address '{ip}' is prohibited.")

        # Check explicit AWS IMDSv6 address
        if str(ip).lower() == AWS_IMDSV6_ADDR:
            raise ValueError(f"Access to cloud metadata IP address '{ip}' is prohibited.")

        # Check loopback / localhost
        if ip.is_loopback:
            warning_flags.append("localhost_endpoint")
        elif ip.is_private:
            warning_flags.append("private_network_endpoint")
    else:
        # Hostname-based checks
        if norm_host in ("localhost", "localhost.localdomain"):
            warning_flags.append("localhost_endpoint")
        elif norm_host.endswith(".local") or norm_host.endswith(".lan") or norm_host.endswith(".internal"):
            warning_flags.append("private_network_endpoint")

    # Clean URL (strip trailing slash for base_url consistency)
    clean_url = url.strip().rstrip("/")
    return clean_url, warning_flags


def mask_api_key(key: str | None) -> str:
    """Return a masked summary of an API key for safe UI and diagnostic responses."""
    if not key or not isinstance(key, str):
        return ""
    k = key.strip()
    if len(k) <= 8:
        return "****"
    if k.startswith("sk-") and len(k) > 12:
        return f"{k[:3]}...{k[-4:]}"
    return f"{k[:3]}...{k[-4:]}"


def mask_identity(identity: str | None) -> str:
    """Mask email or username identity for safe logging and UI summaries."""
    if not identity or not isinstance(identity, str):
        return ""
    raw = identity.strip()
    if "@" in raw:
        local, domain = raw.split("@", 1)
        if len(local) <= 1:
            masked_local = f"{local}***"
        else:
            masked_local = f"{local[0]}***"
        return f"{masked_local}@{domain}"
    if len(raw) <= 3:
        return f"{raw[:1]}***"
    return f"{raw[:2]}***{raw[-1:]}"

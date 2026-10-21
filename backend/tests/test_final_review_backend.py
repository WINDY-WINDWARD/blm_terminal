import json
import os
from pathlib import Path

import httpx
import pytest
import yaml

from app.services.endpoint_validator import validate_custom_endpoint_url
from app.services.provider_vault import ProviderVault, VaultState
from app.services.proxy_supervisor import (
    ProxyManagementClient,
    generate_proxy_config,
    materialize_vault_secrets,
    redact_sensitive_data,
    set_dir_permissions_0700,
    set_file_permissions_0600,
)
from app.services.route_registry import compute_oauth_proxy_prefix, provider_to_route_id


@pytest.mark.parametrize("suffix", ["?api_key=sentinel-query-secret", "#sentinel-fragment-secret", "?token=sentinel"])
def test_endpoint_rejects_credential_url_components(suffix):
    with pytest.raises(ValueError) as error:
        validate_custom_endpoint_url("https://api.example.com/v1" + suffix)
    assert "sentinel" not in str(error.value)


def test_config_serializes_quoted_header_and_redacts_all_headers(tmp_path):
    config = generate_proxy_config(
        "127.0.0.1", 12345, "local-client", "local-management", tmp_path,
        session_affinity=False, custom_endpoints=[{
            "name": "endpoint", "prefix": "route",
            "base-url": "https://api.example.com/v1",
            "headers": {"X-Tenant-Secret": 'tenant "alpha"'},
            "api-key-entries": [{"api-key": "sentinel-key"}],
        }],
    )
    parsed = yaml.safe_load(config)
    assert parsed["routing"]["session-affinity"] is False
    assert parsed["openai-compatibility"][0]["headers"]["X-Tenant-Secret"] == 'tenant "alpha"'
    redacted = json.dumps(redact_sensitive_data(parsed))
    assert "alpha" not in redacted
    assert "sentinel-key" not in redacted


async def test_reset_corrupt_vault_is_recoverable(tmp_path):
    storage = tmp_path / "vault.enc"
    storage.write_bytes(b"corrupt")
    vault = ProviderVault(vault_path=storage, key=b"a" * 32)
    assert await vault.initialize() == VaultState.VAULT_CORRUPT
    await vault.reset_vault()
    assert await vault.get_state() == VaultState.AVAILABLE
    restored = ProviderVault(vault_path=storage, key=b"a" * 32)
    assert await restored.initialize() == VaultState.AVAILABLE
    assert await restored.get_all_oauth_auth() == {}


async def test_oauth_materialization_assigns_stable_prefix(tmp_path):
    vault = ProviderVault(vault_path=tmp_path / "vault.enc", key=b"a" * 32)
    await vault.set_oauth_auth("codex", {"type": "codex", "access_token": "synthetic"})
    await materialize_vault_secrets(vault, tmp_path / "auth")
    payload = json.loads((tmp_path / "auth" / "codex.json").read_text())
    assert payload["prefix"] == compute_oauth_proxy_prefix("oauth:codex")


def test_bare_xai_retains_direct_api_key_route():
    assert provider_to_route_id("xai") == "direct:xai"
    assert provider_to_route_id("oauth:xai") == "oauth:xai"


async def test_management_contract_uses_filename_and_model_objects():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/models"):
            assert request.url.params["name"] == "codex-probe.json"
            return httpx.Response(200, json={"models": [{"id": "route/gpt-test"}]})
        if request.method == "DELETE":
            assert request.url.params["name"] == "codex-probe.json"
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"files": [{"name": "codex-probe.json"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        management = ProxyManagementClient("http://127.0.0.1:12345", "synthetic-management", client=client)
        assert await management.get_credentials() == [{"name": "codex-probe.json"}]
        assert await management.get_credential_models("codex-probe.json") == ["route/gpt-test"]
        await management.delete_credential("codex-probe.json")
    assert len(seen) == 3


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL verification")
def test_runtime_permissions_have_only_current_user_access(tmp_path):
    import win32api
    import win32con
    import win32security
    import ntsecuritycon

    directory = tmp_path / "private"
    directory.mkdir()
    set_dir_permissions_0700(directory)
    target = directory / "credential.json"
    target.write_text("synthetic")
    set_file_permissions_0600(target)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    current_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    for path in (directory, target):
        descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        dacl = descriptor.GetSecurityDescriptorDacl()
        assert dacl.GetAceCount() == 1
        assert dacl.GetAce(0)[2] == current_sid
        assert dacl.GetAce(0)[1] & ntsecuritycon.FILE_ALL_ACCESS == ntsecuritycon.FILE_ALL_ACCESS
        assert not dacl.GetAce(0)[0][1] & win32security.INHERITED_ACE

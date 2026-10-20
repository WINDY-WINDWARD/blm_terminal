"""OS-keyring-backed AES-256-GCM provider vault service.

Manages encrypted persistence for:
- OAuth authorization payloads (tokens, refresh metadata)
- Custom endpoint headers and authentication keys
- Proxy cooldown status snapshots (.cds snapshots)
- Arbitrary encrypted vault entries

Follows strict zero-plaintext-fallback security:
- AES-256-GCM authenticated encryption via cryptography.hazmat.primitives.ciphers.aead.AESGCM
- 32-byte encryption key stored in the OS keyring under service 'blm-terminal-provider-vault', account 'v1'
- Atomic replacement on save with restrictive file permissions (0600)
- In-process asyncio lock to serialize concurrent access
- Explicit states: available, keyring_unavailable, vault_corrupt
- Zero secret logging: values and payload bodies are never logged
"""

from __future__ import annotations

import asyncio
import base64
from enum import Enum
import json
import logging
import os
from pathlib import Path
import secrets
import stat
import struct
from typing import Any, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import keyring
from keyring.errors import KeyringError

from app.config import settings

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "blm-terminal-provider-vault"
KEYRING_ACCOUNT = "v1"

# Binary envelope layout:
# 6 bytes: magic b"BLMVLT"
# 2 bytes: version (uint16 big-endian, currently 1)
# 12 bytes: GCM nonce
# remaining: ciphertext + 16-byte authentication tag
VAULT_MAGIC = b"BLMVLT"
VAULT_VERSION = 1
NONCE_LENGTH = 12
TAG_LENGTH = 16
HEADER_LENGTH = len(VAULT_MAGIC) + 2  # 8 bytes
MIN_ENVELOPE_LENGTH = HEADER_LENGTH + NONCE_LENGTH + TAG_LENGTH  # 36 bytes


class VaultState(str, Enum):
    """Explicit operational state of the provider vault."""

    AVAILABLE = "available"
    KEYRING_UNAVAILABLE = "keyring_unavailable"
    VAULT_CORRUPT = "vault_corrupt"


class VaultError(Exception):
    """Base exception for provider vault operations."""


class KeyringUnavailableError(VaultError):
    """Raised when the OS keyring cannot be accessed or fails."""


class VaultCorruptError(VaultError):
    """Raised when the vault file is corrupted, truncated, or fails authentication."""


class VaultUnavailableError(VaultError):
    """Raised when an operation is attempted on an unavailable vault."""


class ProviderVault:
    """Manages encrypted secrets using AES-256-GCM and OS keyring key storage."""

    def __init__(
        self,
        vault_path: Path | str | None = None,
        service_name: str = KEYRING_SERVICE,
        account_name: str = KEYRING_ACCOUNT,
        key: bytes | None = None,
    ) -> None:
        if vault_path is None:
            env_path = os.environ.get("PROVIDER_VAULT_PATH")
            if env_path:
                self._vault_path = Path(env_path).resolve()
            else:
                self._vault_path = Path(settings.db_path).resolve().parent / "provider_vault.enc"
        else:
            self._vault_path = Path(vault_path).resolve()

        self.service_name = service_name
        self.account_name = account_name
        self._key: bytes | None = key
        self._lock = asyncio.Lock()
        self._state: VaultState = VaultState.KEYRING_UNAVAILABLE
        self._data: dict[str, Any] = self._empty_vault_data()
        self._initialized: bool = False

    @staticmethod
    def _empty_vault_data() -> dict[str, Any]:
        return {
            "version": VAULT_VERSION,
            "oauth_auth": {},
            "endpoint_headers": {},
            "endpoint_keys": {},
            "cooldown_snapshots": {},
            "entries": {},
        }

    @property
    def vault_path(self) -> Path:
        return self._vault_path

    @property
    def state(self) -> VaultState:
        return self._state

    @property
    def is_available(self) -> bool:
        return self._state == VaultState.AVAILABLE

    def _resolve_or_create_key(self) -> bytes | None:
        """Fetch or create the 32-byte vault key from the OS keyring."""
        if self._key is not None and len(self._key) == 32:
            return self._key

        try:
            stored_key_str = keyring.get_password(self.service_name, self.account_name)
        except (KeyringError, Exception) as exc:
            logger.warning("ProviderVault: OS keyring get_password failed: %s", type(exc).__name__)
            return None

        if stored_key_str:
            key_bytes = self._parse_key_str(stored_key_str)
            if key_bytes and len(key_bytes) == 32:
                self._key = key_bytes
                return self._key
            logger.error("ProviderVault: key in keyring could not be parsed as 32 bytes")
            return None

        # Key does not exist in keyring yet; generate 32 random bytes and store
        new_key = secrets.token_bytes(32)
        new_key_hex = new_key.hex()
        try:
            keyring.set_password(self.service_name, self.account_name, new_key_hex)
        except (KeyringError, Exception) as exc:
            logger.warning("ProviderVault: OS keyring set_password failed: %s", type(exc).__name__)
            return None

        self._key = new_key
        return self._key

    @staticmethod
    def _parse_key_str(key_str: str) -> bytes | None:
        clean = key_str.strip()
        if len(clean) == 64:
            try:
                return bytes.fromhex(clean)
            except ValueError:
                pass
        try:
            decoded = base64.b64decode(clean)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        return None

    async def initialize(self) -> VaultState:
        """Initialize the vault, load key from keyring, and decrypt vault file."""
        async with self._lock:
            return self._initialize_unlocked()

    def _initialize_unlocked(self) -> VaultState:
        key = self._resolve_or_create_key()
        if key is None:
            self._state = VaultState.KEYRING_UNAVAILABLE
            self._initialized = True
            logger.info("ProviderVault: initialized with state=%s", self._state.value)
            return self._state

        if not self._vault_path.exists():
            self._data = self._empty_vault_data()
            self._state = VaultState.AVAILABLE
            self._initialized = True
            logger.info("ProviderVault: initialized empty vault with state=%s", self._state.value)
            return self._state

        try:
            raw_bytes = self._vault_path.read_bytes()
        except OSError as exc:
            logger.error("ProviderVault: failed to read vault file: %s", exc)
            self._state = VaultState.VAULT_CORRUPT
            self._initialized = True
            return self._state

        if len(raw_bytes) < MIN_ENVELOPE_LENGTH:
            logger.error("ProviderVault: file truncated (%d bytes < %d minimum)", len(raw_bytes), MIN_ENVELOPE_LENGTH)
            self._state = VaultState.VAULT_CORRUPT
            self._initialized = True
            return self._state

        magic = raw_bytes[: len(VAULT_MAGIC)]
        if magic != VAULT_MAGIC:
            logger.error("ProviderVault: invalid header magic in vault file")
            self._state = VaultState.VAULT_CORRUPT
            self._initialized = True
            return self._state

        version = struct.unpack(">H", raw_bytes[len(VAULT_MAGIC) : HEADER_LENGTH])[0]
        if version != VAULT_VERSION:
            logger.error("ProviderVault: unsupported vault version: %d", version)
            self._state = VaultState.VAULT_CORRUPT
            self._initialized = True
            return self._state

        nonce = raw_bytes[HEADER_LENGTH : HEADER_LENGTH + NONCE_LENGTH]
        ciphertext = raw_bytes[HEADER_LENGTH + NONCE_LENGTH :]

        try:
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
            loaded_data = json.loads(plaintext.decode("utf-8"))
            if not isinstance(loaded_data, dict):
                raise ValueError("Vault payload is not a JSON object")

            # Ensure expected category keys exist
            for cat in ("oauth_auth", "endpoint_headers", "endpoint_keys", "cooldown_snapshots", "entries"):
                if cat not in loaded_data or not isinstance(loaded_data[cat], dict):
                    loaded_data[cat] = {}

            self._data = loaded_data
            self._state = VaultState.AVAILABLE
            self._initialized = True
            logger.info("ProviderVault: successfully decrypted vault (state=%s)", self._state.value)
            return self._state
        except (InvalidTag, ValueError, json.JSONDecodeError, Exception) as exc:
            logger.error("ProviderVault: decryption or payload parsing failed (%s)", type(exc).__name__)
            self._state = VaultState.VAULT_CORRUPT
            self._initialized = True
            return self._state

    def _ensure_ready(self) -> None:
        if not self._initialized:
            self._initialize_unlocked()

        if self._state == VaultState.KEYRING_UNAVAILABLE:
            raise KeyringUnavailableError("OS keyring is unavailable or failed to provide a valid key")
        elif self._state == VaultState.VAULT_CORRUPT:
            raise VaultCorruptError("Vault file is corrupted, truncated, or failed decryption authentication")
        elif self._state != VaultState.AVAILABLE:
            raise VaultUnavailableError(f"Provider vault is unavailable (state: {self._state.value})")

    def _save_unlocked(self) -> None:
        """Encrypt and atomically save vault data to disk with 0600 permissions."""
        if self._key is None:
            raise KeyringUnavailableError("Cannot save vault: encryption key is missing")

        nonce = os.urandom(NONCE_LENGTH)
        aesgcm = AESGCM(self._key)
        plaintext = json.dumps(self._data).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)

        header = VAULT_MAGIC + struct.pack(">H", VAULT_VERSION)
        envelope = header + nonce + ciphertext

        target_path = self._vault_path
        parent_dir = target_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        if os.name != "nt":
            try:
                os.chmod(parent_dir, 0o700)
            except OSError:
                pass

        temp_name = f"{target_path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
        temp_path = parent_dir / temp_name

        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY

            fd = os.open(str(temp_path), flags, 0o600)
            with open(fd, "wb", closefd=True) as f:
                f.write(envelope)
                f.flush()
                os.fsync(f.fileno())

            if os.name != "nt":
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass
            else:
                try:
                    os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass

            os.replace(temp_path, target_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    # -----------------------------------------------------------------------
    # Typed entry accessors
    # -----------------------------------------------------------------------

    async def get_oauth_auth(self, route_or_cred_id: str) -> dict | str | None:
        """Retrieve stored OAuth authorization payload for a route or credential."""
        async with self._lock:
            self._ensure_ready()
            val = self._data["oauth_auth"].get(route_or_cred_id)
            return json.loads(json.dumps(val)) if val is not None else None

    async def set_oauth_auth(self, route_or_cred_id: str, data: dict | str) -> None:
        """Store OAuth authorization payload for a route or credential."""
        async with self._lock:
            self._ensure_ready()
            self._data["oauth_auth"][route_or_cred_id] = data
            self._save_unlocked()

    async def remove_oauth_auth(self, route_or_cred_id: str) -> bool:
        """Remove OAuth authorization payload."""
        async with self._lock:
            self._ensure_ready()
            if route_or_cred_id in self._data["oauth_auth"]:
                del self._data["oauth_auth"][route_or_cred_id]
                self._save_unlocked()
                return True
            return False

    async def get_endpoint_headers(self, route_id: str) -> dict[str, str] | None:
        """Retrieve custom headers configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            val = self._data["endpoint_headers"].get(route_id)
            return dict(val) if isinstance(val, dict) else None

    async def set_endpoint_headers(self, route_id: str, headers: dict[str, str]) -> None:
        """Store custom headers configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            self._data["endpoint_headers"][route_id] = dict(headers)
            self._save_unlocked()

    async def remove_endpoint_headers(self, route_id: str) -> bool:
        """Remove custom headers configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            if route_id in self._data["endpoint_headers"]:
                del self._data["endpoint_headers"][route_id]
                self._save_unlocked()
                return True
            return False

    async def get_endpoint_keys(self, route_id: str) -> list[str] | None:
        """Retrieve API keys configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            val = self._data["endpoint_keys"].get(route_id)
            return list(val) if isinstance(val, list) else None

    async def set_endpoint_keys(self, route_id: str, keys: list[str]) -> None:
        """Store API keys configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            self._data["endpoint_keys"][route_id] = list(keys)
            self._save_unlocked()

    async def remove_endpoint_keys(self, route_id: str) -> bool:
        """Remove API keys configured for an endpoint route."""
        async with self._lock:
            self._ensure_ready()
            if route_id in self._data["endpoint_keys"]:
                del self._data["endpoint_keys"][route_id]
                self._save_unlocked()
                return True
            return False

    async def get_cooldown_snapshot(self, route_or_cred_id: str) -> dict | str | None:
        """Retrieve stored cooldown status (.cds snapshot) data."""
        async with self._lock:
            self._ensure_ready()
            val = self._data["cooldown_snapshots"].get(route_or_cred_id)
            return json.loads(json.dumps(val)) if val is not None else None

    async def set_cooldown_snapshot(self, route_or_cred_id: str, snapshot: dict | str) -> None:
        """Store cooldown status (.cds snapshot) data."""
        async with self._lock:
            self._ensure_ready()
            self._data["cooldown_snapshots"][route_or_cred_id] = snapshot
            self._save_unlocked()

    async def remove_cooldown_snapshot(self, route_or_cred_id: str) -> bool:
        """Remove cooldown status snapshot."""
        async with self._lock:
            self._ensure_ready()
            if route_or_cred_id in self._data["cooldown_snapshots"]:
                del self._data["cooldown_snapshots"][route_or_cred_id]
                self._save_unlocked()
                return True
            return False

    # -----------------------------------------------------------------------
    # Generic reference helpers for `ai_provider_credentials.vault_reference`
    # -----------------------------------------------------------------------

    def _split_ref(self, vault_ref: str) -> tuple[str, str]:
        if ":" in vault_ref:
            cat, sub = vault_ref.split(":", 1)
            if cat in ("oauth_auth", "endpoint_headers", "endpoint_keys", "cooldown_snapshots", "entries"):
                return cat, sub
        return "entries", vault_ref

    async def get_secret(self, vault_ref: str) -> Any:
        """Retrieve secret by reference string."""
        async with self._lock:
            self._ensure_ready()
            cat, sub = self._split_ref(vault_ref)
            val = self._data[cat].get(sub)
            return json.loads(json.dumps(val)) if val is not None else None

    async def set_secret(self, vault_ref: str, value: Any) -> None:
        """Store secret by reference string."""
        async with self._lock:
            self._ensure_ready()
            cat, sub = self._split_ref(vault_ref)
            self._data[cat][sub] = value
            self._save_unlocked()

    async def delete_secret(self, vault_ref: str) -> bool:
        """Delete secret by reference string."""
        async with self._lock:
            self._ensure_ready()
            cat, sub = self._split_ref(vault_ref)
            if sub in self._data[cat]:
                del self._data[cat][sub]
                self._save_unlocked()
                return True
            return False

    async def reset_vault(self) -> None:
        """Reset the vault contents to empty and rewrite encrypted file."""
        async with self._lock:
            self._ensure_ready()
            self._data = self._empty_vault_data()
            self._save_unlocked()
            logger.info("ProviderVault: reset all stored secrets")


_default_vault: ProviderVault | None = None


def get_provider_vault() -> ProviderVault:
    """Return the global ProviderVault singleton instance."""
    global _default_vault
    if _default_vault is None:
        _default_vault = ProviderVault()
    return _default_vault

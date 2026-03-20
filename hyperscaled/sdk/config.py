"""Configuration system for the Hyperscaled SDK.

Reads/writes ``~/.hyperscaled/config.toml`` and supports environment-variable
overrides for wallet addresses and API base URL.

Precedence (highest → lowest):
    1. Values set directly on the model (e.g. via ``config.wallet.hl_address = ...``)
    2. Config file (``~/.hyperscaled/config.toml``)
    3. Environment variables (``HYPERSCALED_HL_ADDRESS``, ``HYPERSCALED_PAYOUT_ADDRESS``,
       ``HYPERSCALED_BASE_URL``, ``HYPERSCALED_VALIDATOR_API_URL``)
    4. Defaults
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_HL_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

_DEFAULT_DIR = Path.home() / ".hyperscaled"
_DEFAULT_PATH = _DEFAULT_DIR / "config.toml"


def is_valid_hl_address(value: str) -> bool:
    """Return ``True`` when ``value`` matches the strict HL/EVM address format."""
    return bool(_HL_ADDRESS_RE.match(value))


class WalletConfig(BaseModel):
    hl_address: str = ""
    payout_address: str = ""

    @field_validator("hl_address", "payout_address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        if v and not is_valid_hl_address(v):
            raise ValueError(
                f"Invalid wallet address: {v!r} — expected format 0x followed by 40 hex chars"
            )
        return v


class AccountConfig(BaseModel):
    entity_miner: str = ""
    funded_account_id: str = ""
    funded_account_size: int = 0
    kyc_status: Literal["not_started", "pending", "verified"] = "not_started"


class ApiConfig(BaseModel):
    hyperscaled_base_url: str = "https://api.hyperscaled.com"
    validator_api_url: str = "http://34.187.154.219:48888"
    testnet: bool = False


class Config(BaseModel):
    wallet: WalletConfig = WalletConfig()
    account: AccountConfig = AccountConfig()
    api: ApiConfig = ApiConfig()

    _path: Path = _DEFAULT_PATH

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load config from TOML, creating the file with defaults if it doesn't exist.

        Environment variables are applied as fallbacks for any value that is
        empty or unset in the file.
        """
        config_path = path or _DEFAULT_PATH

        if config_path.exists():
            raw = config_path.read_bytes()
            data = tomllib.loads(raw.decode()) if raw else {}
            config = cls.model_validate(data)
        else:
            data = {}
            config = cls()

        config._path = config_path
        config._apply_env_fallbacks(data)

        if not config_path.exists():
            config.save()

        return config

    def save(self, path: Path | None = None) -> None:
        """Write the current config to TOML."""
        target = path or self._path
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        data = self.model_dump()
        target.write_bytes(tomli_w.dumps(data).encode())
        os.chmod(target, 0o600)

    def set_value(self, dotted_key: str, value: str) -> None:
        """Set a config value using a dotted key path like ``wallet.hl_address``.

        Validates the value before applying it.
        """
        parts = dotted_key.split(".")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid key {dotted_key!r} — expected format 'section.key' "
                f"(e.g. 'wallet.hl_address')"
            )

        section_name, key = parts

        section = getattr(self, section_name, None)
        if section is None or not isinstance(section, BaseModel):
            valid = [f for f in Config.model_fields if f != "_path"]
            raise ValueError(f"Unknown config section {section_name!r} — valid sections: {valid}")

        if key not in section.__class__.model_fields:
            raise ValueError(
                f"Unknown key {key!r} in section {section_name!r} — "
                f"valid keys: {list(section.__class__.model_fields)}"
            )

        section_data = section.model_dump()
        # Coerce string values for boolean fields
        field_info = section.__class__.model_fields[key]
        if field_info.annotation is bool:
            section_data[key] = value.lower() in ("1", "true", "yes")
        else:
            section_data[key] = value
        validated = section.__class__.model_validate(section_data)
        setattr(self, section_name, validated)

    @property
    def hl_info_url(self) -> str:
        """Return the Hyperliquid info API URL based on testnet setting."""
        if self.api.testnet:
            return "https://api.hyperliquid-testnet.xyz/info"
        return "https://api.hyperliquid.xyz/info"

    @property
    def hl_base_url(self) -> str:
        """Return the Hyperliquid base URL based on testnet setting."""
        if self.api.testnet:
            return "https://api.hyperliquid-testnet.xyz"
        return "https://api.hyperliquid.xyz"

    def _apply_env_fallbacks(self, file_data: dict[str, object]) -> None:
        env_hl = os.environ.get("HYPERSCALED_HL_ADDRESS", "")
        env_payout = os.environ.get("HYPERSCALED_PAYOUT_ADDRESS", "")
        env_base_url = os.environ.get("HYPERSCALED_BASE_URL", "")
        env_validator_url = os.environ.get("HYPERSCALED_VALIDATOR_API_URL", "")
        env_testnet = os.environ.get("HYPERSCALED_TESTNET", "")

        wallet_data = file_data.get("wallet")
        api_data = file_data.get("api")

        wallet_data = wallet_data if isinstance(wallet_data, dict) else {}
        api_data = api_data if isinstance(api_data, dict) else {}

        if not wallet_data.get("hl_address") and env_hl:
            self.wallet = WalletConfig(
                hl_address=env_hl,
                payout_address=self.wallet.payout_address,
            )
        if not wallet_data.get("payout_address") and env_payout:
            self.wallet = WalletConfig(
                hl_address=self.wallet.hl_address,
                payout_address=env_payout,
            )
        if not api_data.get("hyperscaled_base_url") and env_base_url:
            self.api = ApiConfig(
                hyperscaled_base_url=env_base_url,
                validator_api_url=self.api.validator_api_url,
                testnet=self.api.testnet,
            )
        if not api_data.get("validator_api_url") and env_validator_url:
            self.api = ApiConfig(
                hyperscaled_base_url=self.api.hyperscaled_base_url,
                validator_api_url=env_validator_url,
                testnet=self.api.testnet,
            )
        if not api_data.get("testnet") and env_testnet:
            self.api = ApiConfig(
                hyperscaled_base_url=self.api.hyperscaled_base_url,
                validator_api_url=self.api.validator_api_url,
                testnet=env_testnet.lower() in ("1", "true", "yes"),
            )

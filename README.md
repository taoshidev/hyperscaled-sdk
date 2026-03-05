# Hyperscaled SDK & CLI

Python CLI and SDK for the [Hyperscaled](https://hyperscaled.com) funded trading platform on Hyperliquid, powered by the Vanta Network.

## Installation

```bash
pip install hyperscaled
```

For Hyperliquid SDK integration:

```bash
pip install "hyperscaled[hl]"
```

## CLI Quick Start

```bash
hyperscaled --help        # Show all command groups
hyperscaled --version     # Print version
hyperscaled config show   # Show local SDK configuration
hyperscaled config path   # Print ~/.hyperscaled/config.toml
```

Miner discovery commands in `hyperscaled miners ...` are planned for `SDK-005` and
are not implemented yet.

## SDK Quick Start

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient(hl_wallet="0x...", payout_wallet="0x...")

# Inspect resolved configuration
print(client.config.wallet.hl_address)
print(client.config.api.hyperscaled_base_url)
```

## Development

```bash
git clone https://github.com/hyperscaled/hyperscaled-sdk.git
cd hyperscaled-sdk
pip install -e ".[dev]"

# Lint
ruff check .

# Type check
mypy hyperscaled

# Test
pytest
```

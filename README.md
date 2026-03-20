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
hyperscaled miners list   # List entity miners and account sizes
```

## SDK Quick Start

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient(hl_wallet="0x...", payout_wallet="0x...")

# Inspect resolved configuration
print(client.config.wallet.hl_address)
print(client.config.api.hyperscaled_base_url)
print(client.config.api.validator_api_url)  # orchestrator (e.g. purchase /api/register)

# Miner catalog discovery
for miner in client.miners.list_all():
    print(miner.slug, miner.payout_cadence, miner.available_account_sizes)
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

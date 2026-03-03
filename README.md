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
hyperscaled --help              # Show all command groups
hyperscaled --version           # Print version
hyperscaled miners list         # Browse entity miners
hyperscaled miners info <slug>  # Miner details
```

## SDK Quick Start

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient(hl_wallet="0x...", payout_wallet="0x...")

# Browse entity miners
miners = client.miners.list_all()
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

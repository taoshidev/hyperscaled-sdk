"""CLI commands for funded account registration."""

from __future__ import annotations

import json as _json
from decimal import Decimal
from typing import cast

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import (
    HyperscaledError,
    InsufficientBalanceError,
    InvalidMinerError,
    PaymentError,
    RegistrationError,
    RegistrationPollTimeoutError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models import (
    MINIMUM_BALANCE,
    BalanceStatus,
    EntityMiner,
    RegistrationStatus,
)

app = typer.Typer(no_args_is_help=True, invoke_without_command=True)
console = Console()


def _wallet_error(address: str) -> str:
    return f"Invalid wallet address: {address!r} — expected format 0x followed by 40 hex chars"


def _resolve_wallet_or_exit(client: HyperscaledClient, wallet_address: str | None) -> str:
    resolved = wallet_address if wallet_address is not None else client.config.wallet.hl_address
    if not resolved:
        console.print(
            "[red]Error:[/red] No Hyperliquid wallet configured. "
            "Run `hyperscaled account setup <wallet>` or pass `--hl-wallet`."
        )
        raise typer.Exit(code=1) from None
    if not client.account.validate_wallet(resolved):
        console.print(f"[red]Error:[/red] {_wallet_error(resolved)}")
        raise typer.Exit(code=1) from None
    return resolved


def _format_money(amount: Decimal) -> str:
    """Format a dollar amount for display (drops “.00” for whole dollars)."""
    quantized = amount.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral():
        return f"${int(quantized):,}"
    return f"${quantized:,.2f}"


def _short_address(address: str) -> str:
    if len(address) <= 12:
        return address
    return f"{address[:6]}…{address[-4:]}"


def _render_miner_pricing(miner: EntityMiner, *, selected_size: int | None = None) -> Panel:
    """Build a Rich panel showing the miner's pricing tiers."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("Account Size", style="cyan")
    table.add_column("Cost")
    table.add_column("Profit Split")

    for tier in miner.pricing_tiers:
        row_style = None
        if selected_size is not None and tier.account_size == selected_size:
            row_style = "bold green"
        table.add_row(
            f"${tier.account_size:,}",
            _format_money(tier.cost),
            f"{tier.profit_split.trader_pct}/{tier.profit_split.miner_pct}",
            style=row_style,
        )

    title = f"{miner.name} — Pricing"
    if selected_size is not None:
        title += " (selected tier highlighted)"
    return Panel(table, title=title, border_style="cyan")


def _render_checkout_summary(
    *,
    account_size: int,
    tier_cost: Decimal,
    trader_pct: int,
    miner_pct: int,
    hl_address: str,
    hl_balance_text: str,
    base_address: str,
    usdc_balance_text: str,
    after_payment_text: str,
    testnet: bool,
) -> Panel:
    network = "Base Sepolia" if testnet else "Base"
    lines = [
        "[bold underline]Selected tier[/bold underline]",
        f"  Funded account    [cyan]${account_size:,}[/cyan]",
        f"  Tier price        {_format_money(tier_cost)} USDC",
        f"  Profit split      {trader_pct}/{miner_pct} (trader / miner)",
        "",
        "[bold underline]Hyperliquid wallet[/bold underline] (perp eligibility)",
        f"  Address           [dim]{hl_address}[/dim]  ({_short_address(hl_address)})",
        f"  Account equity    {hl_balance_text}",
        "",
        (
            f"[bold underline]Payment wallet[/bold underline] ({network} — "
            "from HYPERSCALED_BASE_PRIVATE_KEY)"
        ),
        f"  Address           [dim]{base_address}[/dim]  ({_short_address(base_address)})",
        f"  USDC balance      {usdc_balance_text}",
        f"  Est. after pay    {after_payment_text}",
        "",
        "[dim]Keep a small amount of ETH on Base for gas. Tier price excludes gas.[/dim]",
    ]
    border = "yellow" if "insufficient" in after_payment_text.lower() else "green"
    return Panel("\n".join(lines), title="Checkout summary", border_style=border)


def _render_result(result: RegistrationStatus, *, title: str = "Registration Result") -> Panel:
    """Build a Rich panel showing a registration result."""
    lines = [f"[bold]Status:[/bold]          {result.status}"]
    if result.hl_address:
        lines.append(f"[bold]HL Address:[/bold]      {result.hl_address}")
    if result.account_size is not None:
        lines.append(f"[bold]Account Size:[/bold]    ${result.account_size:,}")
    if result.registration_id:
        lines.append(f"[bold]Registration ID:[/bold] {result.registration_id}")
    if result.tx_hash:
        lines.append(f"[bold]Tx Hash:[/bold]         {result.tx_hash}")
    if result.message:
        lines.append(f"[bold]Message:[/bold]         {result.message}")
    if result.estimated_time:
        lines.append(f"[bold]Estimated Time:[/bold] {result.estimated_time}")

    style = "green" if result.is_success else ("red" if result.is_terminal else "yellow")
    return Panel("\n".join(lines), title=title, border_style=style)


def _is_terminal_failure(result: RegistrationStatus) -> bool:
    """Whether the result is a terminal non-success state."""
    return result.is_terminal and not result.is_success


def _run_purchase(
    miner_slug: str,
    size: int,
    hl_wallet: str | None,
    payout_wallet: str | None,
    email: str | None,
) -> None:
    client = HyperscaledClient()

    # Resolve HL wallet
    resolved_hl = _resolve_wallet_or_exit(client, hl_wallet)

    if not email:
        console.print("[red]Error:[/red] Email is required for registration.")
        raise typer.Exit(code=1) from None

    # Use configured payout wallet when available; otherwise omit it so the backend
    # can default to the x402 payer address.
    resolved_payout = payout_wallet or client.config.wallet.payout_address or None

    # Fetch and display miner pricing
    try:
        miner = cast(EntityMiner, client.miners.get(miner_slug))
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    selected_tier = next((t for t in miner.pricing_tiers if t.account_size == size), None)
    if selected_tier is None:
        available = sorted(t.account_size for t in miner.pricing_tiers)
        sizes_txt = ", ".join(f"${s:,}" for s in available) if available else "(none)"
        console.print(
            f"[red]Error:[/red] Account size ${size:,} is not offered by miner "
            f"[cyan]{miner_slug}[/cyan]. Available: {sizes_txt}"
        )
        raise typer.Exit(code=1) from None

    console.print(_render_miner_pricing(miner, selected_size=size))

    # Hyperliquid equity (registration minimum)
    if client.config.api.testnet:
        hl_balance_text = "[dim]skipped on testnet — minimum balance rule not enforced[/dim]"
    else:
        try:
            hl_status = cast(BalanceStatus, client.account.check_balance(resolved_hl))
            min_ok = hl_status.meets_minimum
            flag = "[green]meets minimum[/green]" if min_ok else "[red]below minimum[/red]"
            hl_balance_text = (
                f"{_format_money(hl_status.balance)}  ({flag}; "
                f"needs ≥ {_format_money(MINIMUM_BALANCE)})"
            )
        except HyperscaledError as exc:
            hl_balance_text = f"[yellow]could not load ({exc.message})[/yellow]"

    try:
        base_address = client.register.payment_wallet_address()
    except PaymentError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    usdc_balance: Decimal | None = None
    try:
        usdc_balance = cast(Decimal, client.register.payment_wallet_usdc_balance())
        usdc_balance_text = f"[bold]{_format_money(usdc_balance)}[/bold]"
    except HyperscaledError as exc:
        usdc_balance_text = f"[yellow]could not load ({exc.message})[/yellow]"

    if usdc_balance is not None:
        remaining = usdc_balance - selected_tier.cost
        after_raw = f"{_format_money(remaining)} USDC"
        if remaining < 0:
            after_payment_text = f"[red]{after_raw} (insufficient for this tier)[/red]"
        elif remaining == 0:
            after_payment_text = f"[yellow]{after_raw}[/yellow]"
        else:
            after_payment_text = f"[green]{after_raw}[/green]"
    else:
        after_payment_text = "[dim]—[/dim]"

    console.print(
        _render_checkout_summary(
            account_size=size,
            tier_cost=selected_tier.cost,
            trader_pct=selected_tier.profit_split.trader_pct,
            miner_pct=selected_tier.profit_split.miner_pct,
            hl_address=resolved_hl,
            hl_balance_text=hl_balance_text,
            base_address=base_address,
            usdc_balance_text=usdc_balance_text,
            after_payment_text=after_payment_text,
            testnet=client.config.api.testnet,
        )
    )

    # Confirm purchase
    if not typer.confirm("Proceed with purchase?"):
        raise typer.Abort()

    # Execute purchase
    try:
        result = cast(
            RegistrationStatus,
            client.register.purchase(
                miner_slug,
                size,
                resolved_hl,
                resolved_payout,
                email=email,
            ),
        )
    except InsufficientBalanceError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except PaymentError as exc:
        console.print(f"[red]Payment Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except RegistrationError as exc:
        console.print(f"[red]Registration Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except InvalidMinerError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except UnsupportedAccountSizeError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    console.print(_render_result(result))


@app.callback()
def register(
    ctx: typer.Context,
    miner: str | None = typer.Option(None, "--miner", help="Entity miner slug"),
    size: int | None = typer.Option(None, "--size", help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
    payout_wallet: str | None = typer.Option(
        None, "--payout-wallet", help="Payout wallet address (defaults to x402 payer wallet)"
    ),
    email: str | None = typer.Option(None, "--email", help="Email for registration confirmation"),
) -> None:
    """Purchase and connect a funded account."""
    if ctx.invoked_subcommand is not None:
        return
    if miner is None or size is None:
        raise typer.Exit()
    _run_purchase(
        miner_slug=miner,
        size=size,
        hl_wallet=hl_wallet,
        payout_wallet=payout_wallet,
        email=email,
    )


@app.command("purchase")
def purchase(
    miner: str = typer.Option(..., help="Entity miner slug"),
    size: int = typer.Option(..., help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
    payout_wallet: str | None = typer.Option(
        None, "--payout-wallet", help="Payout wallet address (defaults to x402 payer wallet)"
    ),
    email: str = typer.Option(..., "--email", help="Email for registration confirmation"),
) -> None:
    """Purchase a funded trading account via x402 payment."""
    _run_purchase(
        miner_slug=miner,
        size=size,
        hl_wallet=hl_wallet,
        payout_wallet=payout_wallet,
        email=email,
    )


@app.command("status")
def status(
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
    poll: bool = typer.Option(True, "--poll/--no-poll", help="Poll until terminal state"),
    interval: float = typer.Option(5.0, "--interval", help="Seconds between poll attempts"),
    timeout: float = typer.Option(300.0, "--timeout", help="Max seconds to poll"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Check registration status for an HL wallet."""
    client = HyperscaledClient()
    resolved = _resolve_wallet_or_exit(client, hl_wallet)

    if poll:
        _run_status_poll(client, resolved, interval, timeout, json_output)
    else:
        _run_status_check(client, resolved, json_output)


def _run_status_check(client: HyperscaledClient, hl_address: str, json_output: bool) -> None:
    try:
        result = cast(
            RegistrationStatus,
            client.register.check_status(hl_address),
        )
    except RegistrationError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        console.print(_json.dumps(result.model_dump(exclude_none=True), indent=2))
    else:
        console.print(_render_result(result, title="Registration Status"))

    if _is_terminal_failure(result):
        raise typer.Exit(code=1) from None


def _run_status_poll(
    client: HyperscaledClient,
    hl_address: str,
    interval: float,
    timeout: float,
    json_output: bool,
) -> None:
    poll_count = 0

    def _on_status(status: RegistrationStatus) -> None:
        nonlocal poll_count
        poll_count += 1
        if not json_output:
            console.print(
                f"  [dim]\\[poll {poll_count}][/dim] status: [bold]{status.status}[/bold]"
            )

    if not json_output:
        console.print(f"Polling registration status for [cyan]{hl_address}[/cyan] ...")

    try:
        result = cast(
            RegistrationStatus,
            client.register.poll_until_complete(
                hl_address,
                interval_seconds=interval,
                timeout_seconds=timeout,
                on_status=_on_status,
            ),
        )
    except RegistrationPollTimeoutError as exc:
        console.print(f"[yellow]Timeout:[/yellow] {exc.message}")
        raise typer.Exit(code=2) from None
    except RegistrationError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        console.print(_json.dumps(result.model_dump(exclude_none=True), indent=2))
    else:
        console.print(_render_result(result, title="Registration Complete"))

    if _is_terminal_failure(result):
        raise typer.Exit(code=1) from None

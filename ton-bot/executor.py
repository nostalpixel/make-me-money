"""
TON wallet management and DeDust v2 DEX swaps.
Swaps: TON ↔ USDT on DeDust (mainnet).
"""
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from dedust import Factory, VaultNative, VaultJetton, AssetNative, AssetJetton, PoolType
from pytoniq import LiteBalancer, WalletV4R2
from pytoniq_core import Address

import db

logger = logging.getLogger(__name__)

# DeDust v2 mainnet
DEDUST_FACTORY = Address("EQBfBWT7X2BHg9tXAxzhz2aKiNTU1tpt5NsiK0uSDW_YAJ67")
USDT_MASTER    = Address("EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")

GAS_TON     = int(0.25e9)   # nanotons reserved for gas per swap
MIN_TON     = 2.0           # minimum TON notional to trade
TON_RESERVE = 1.0           # always keep ≥1 TON for gas in wallet

TON_ASSET  = AssetNative()
USDT_ASSET = AssetJetton.from_address(USDT_MASTER)


async def make_provider() -> LiteBalancer:
    provider = LiteBalancer.from_mainnet_config(trust_level=1)
    await provider.start_up()
    return provider


async def make_wallet(provider: LiteBalancer, mnemonic: list[str]) -> WalletV4R2:
    return await WalletV4R2.from_mnemonic(provider, mnemonic)


async def get_ton_balance(provider: LiteBalancer, address: Address) -> float:
    state = await provider.get_account_state(address)
    return state.balance / 1e9


async def get_usdt_balance(provider: LiteBalancer, wallet_address: Address) -> float:
    """Get USDT jetton balance by querying the user's USDT wallet address."""
    try:
        result = await provider.run_get_method(
            addr=USDT_MASTER,
            method="get_wallet_address",
            stack=[wallet_address],
        )
        usdt_wallet_addr = result[0].load_address()
        state = await provider.get_account_state(usdt_wallet_addr)
        if state.balance == 0:
            return 0.0
        # Get actual jetton balance via get_wallet_data
        data = await provider.run_get_method(addr=usdt_wallet_addr, method="get_wallet_data", stack=[])
        balance_nano = data[0]  # balance in nanoUSDT (6 decimals)
        return balance_nano / 1e6
    except Exception as e:
        logger.warning("Could not fetch USDT balance: %s", e)
        return 0.0


async def get_portfolio_usdt(provider: LiteBalancer, wallet: WalletV4R2, ton_price: float) -> float:
    """Total portfolio value in USDT (TON + USDT held)."""
    ton_bal  = await get_ton_balance(provider, wallet.address)
    usdt_bal = await get_usdt_balance(provider, wallet.address)
    return ton_bal * ton_price + usdt_bal


async def swap_ton_to_usdt(provider: LiteBalancer, wallet: WalletV4R2, ton_amount: float) -> dict | None:
    """Swap TON → USDT on DeDust. Returns tx info or None on failure."""
    nano_amount = int(ton_amount * 1e9)
    try:
        factory = await Factory.from_address(provider, DEDUST_FACTORY)
        vault   = await factory.get_native_vault()
        pool    = await factory.get_pool(PoolType.VOLATILE, [TON_ASSET, USDT_ASSET])

        await vault.send_swap(
            provider=provider,
            via=wallet,
            pool_address=pool.address,
            amount=nano_amount,
            query_id=int(datetime.now(timezone.utc).timestamp()),
        )
        logger.info("Swap TON→USDT submitted: %.4f TON", ton_amount)
        await asyncio.sleep(15)  # wait for tx to land
        return {"direction": "TON→USDT", "amount": ton_amount}
    except Exception as e:
        logger.error("Swap TON→USDT failed: %s", e)
        return None


async def swap_usdt_to_ton(provider: LiteBalancer, wallet: WalletV4R2, usdt_amount: float) -> dict | None:
    """Swap USDT → TON on DeDust. Returns tx info or None on failure."""
    nano_amount = int(usdt_amount * 1e6)  # USDT has 6 decimals on TON
    try:
        factory      = await Factory.from_address(provider, DEDUST_FACTORY)
        jetton_vault = await factory.get_jetton_vault(USDT_MASTER)
        pool         = await factory.get_pool(PoolType.VOLATILE, [TON_ASSET, USDT_ASSET])

        await jetton_vault.send_swap(
            provider=provider,
            via=wallet,
            pool_address=pool.address,
            amount=nano_amount,
            query_id=int(datetime.now(timezone.utc).timestamp()),
        )
        logger.info("Swap USDT→TON submitted: %.4f USDT", usdt_amount)
        await asyncio.sleep(15)
        return {"direction": "USDT→TON", "amount": usdt_amount}
    except Exception as e:
        logger.error("Swap USDT→TON failed: %s", e)
        return None


async def enter_ton(provider: LiteBalancer, wallet: WalletV4R2, ton_price: float) -> dict | None:
    """Convert available USDT back into TON (BUY signal)."""
    usdt_bal = await get_usdt_balance(provider, wallet.address)
    if usdt_bal < 1.0:
        logger.info("No USDT to convert (%.4f)", usdt_bal)
        return None
    result = await swap_usdt_to_ton(provider, wallet, usdt_bal)
    if result is None:
        return None
    ts    = datetime.now(timezone.utc).isoformat()
    trade = db.open_trade(ts, "TON/USDT", "buy", usdt_bal, ton_price)
    return {"trade_id": trade, "price": ton_price, "size_usdt": usdt_bal}


async def exit_to_usdt(provider: LiteBalancer, wallet: WalletV4R2, ton_price: float) -> dict | None:
    """Swap tradeable TON to USDT (SELL signal). Keeps TON_RESERVE for gas."""
    ton_bal   = await get_ton_balance(provider, wallet.address)
    tradeable = ton_bal - TON_RESERVE
    if tradeable < MIN_TON:
        logger.info("Not enough TON to sell (%.4f free)", tradeable)
        return None
    size_usdt = tradeable * ton_price
    result    = await swap_ton_to_usdt(provider, wallet, tradeable)
    if result is None:
        return None
    ts    = datetime.now(timezone.utc).isoformat()
    trade = db.open_trade(ts, "TON/USDT", "sell", size_usdt, ton_price)
    return {"trade_id": trade, "price": ton_price, "size_usdt": size_usdt}

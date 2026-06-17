"""Unit tests for the on-chain redemption service.

Covers the pure logic (filtering, grouping, amount/index-set construction) and
the safety guards (dry-run default, proxy-wallet mismatch abort) without making
any network/RPC calls.
"""
from unittest.mock import AsyncMock, patch

import pytest

from api.services.redeem import (
    is_redeemable,
    _group_redeemable,
    _amounts_array,
    _index_sets,
    _to_bytes32,
    redeem_all_positions,
)


def _pos(**kw):
    base = {
        "conditionId": "0x" + "11" * 32,
        "negativeRisk": False,
        "size": 100.0,
        "outcomeIndex": 0,
        "redeemable": True,
        "currentValue": 100.0,
        "title": "Test market",
    }
    base.update(kw)
    return base


# --- is_redeemable ----------------------------------------------------------

def test_is_redeemable_true():
    assert is_redeemable(_pos(redeemable=True, size=10)) is True


def test_is_redeemable_false_when_flag_off():
    assert is_redeemable(_pos(redeemable=False)) is False


def test_is_redeemable_false_when_zero_size():
    assert is_redeemable(_pos(redeemable=True, size=0)) is False


# --- grouping ---------------------------------------------------------------

def test_group_merges_outcomes_under_one_condition():
    cid = "0x" + "22" * 32
    positions = [
        _pos(conditionId=cid, outcomeIndex=0, size=50, currentValue=50),
        _pos(conditionId=cid, outcomeIndex=1, size=30, currentValue=0),
    ]
    groups = _group_redeemable(positions)
    assert len(groups) == 1
    g = groups[0]
    assert g["outcomes"] == {0: 50.0, 1: 30.0}
    assert g["total_value"] == 50.0


def test_group_separates_neg_risk_from_regular():
    cid = "0x" + "33" * 32
    positions = [
        _pos(conditionId=cid, negativeRisk=False),
        _pos(conditionId=cid, negativeRisk=True),
    ]
    groups = _group_redeemable(positions)
    assert len(groups) == 2


def test_group_skips_missing_condition_id():
    groups = _group_redeemable([_pos(conditionId=None)])
    assert groups == []


# --- amounts / index sets ---------------------------------------------------

def test_amounts_array_uses_6_decimals_and_fills_gaps():
    # Holding 50 of outcome 0, nothing of 1 -> [50e6, 0]
    assert _amounts_array({0: 50.0}) == [50_000_000, 0]
    assert _amounts_array({0: 12.5, 1: 7.0}) == [12_500_000, 7_000_000]


def test_amounts_array_empty():
    assert _amounts_array({}) == []


def test_index_sets_bitmask_per_slot():
    assert _index_sets({0: 1.0}) == [1]
    assert _index_sets({0: 1.0, 1: 1.0}) == [1, 2]
    assert _index_sets({1: 1.0}) == [2]


# --- bytes32 conversion -----------------------------------------------------

def test_to_bytes32_roundtrip():
    cid = "0x" + "ab" * 32
    assert _to_bytes32(cid) == bytes.fromhex("ab" * 32)


def test_to_bytes32_rejects_wrong_length():
    with pytest.raises(ValueError):
        _to_bytes32("0xdeadbeef")


# --- redeem_all_positions guards (no broadcast) -----------------------------

@pytest.mark.asyncio
async def test_redeem_requires_private_key():
    with pytest.raises(ValueError, match="private_key"):
        await redeem_all_positions(profile={"polymarket_private_key": ""}, dry_run=True)


@pytest.mark.asyncio
async def test_dry_run_plans_without_broadcasting():
    # Deterministic test key (well-known Hardhat account #0 — never funded here).
    key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    from eth_account import Account
    eoa = Account.from_key(key).address

    profile = {"polymarket_private_key": key, "wallet_address": eoa}
    fake_positions = [_pos(conditionId="0x" + "44" * 32, currentValue=42.0)]

    with patch(
        "api.services.redeem.find_redeemable_positions",
        new=AsyncMock(return_value=fake_positions),
    ):
        result = await redeem_all_positions(profile=profile, dry_run=True)

    assert result["dry_run"] is True
    assert result["redeemable_markets"] == 1
    assert result["estimated_payout_usdc"] == 42.0
    assert result["results"][0]["status"] == "planned"


@pytest.mark.asyncio
async def test_proxy_wallet_mismatch_aborts():
    key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    # wallet_address deliberately differs from the EOA -> proxy/Safe case.
    profile = {
        "polymarket_private_key": key,
        "wallet_address": "0x000000000000000000000000000000000000dEaD",
    }
    fake_positions = [_pos(conditionId="0x" + "55" * 32)]

    with patch(
        "api.services.redeem.find_redeemable_positions",
        new=AsyncMock(return_value=fake_positions),
    ):
        result = await redeem_all_positions(profile=profile, dry_run=False)

    assert "error" in result
    assert "proxy" in result["error"].lower()
    assert result["results"] == []

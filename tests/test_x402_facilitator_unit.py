"""Unit tests for x402 facilitator payment requirement builder."""

import os

import pytest

from api.services.x402_facilitator_service import (
    build_payment_required_dict,
    decimal_to_smallest_units,
    facilitator_enabled,
)


def test_decimal_to_smallest_units_usdc_scale():
    assert decimal_to_smallest_units("0.01", 7) == "100000"
    assert decimal_to_smallest_units("1", 7) == "10000000"


def test_build_payment_required_includes_x402_version(monkeypatch):
    monkeypatch.setenv("EXECUTOR_PUBLIC_KEY", "GCCNOHVSMCGE62GGT7FEGSRICTNRFOEOJKAOQPUNORGBRNJLR4USNGDF")
    monkeypatch.setenv("X402_PRICE", "0.02")
    d = build_payment_required_dict()
    assert d.get("x402Version") == 2
    assert d.get("accepts")
    assert d["accepts"][0]["scheme"] == "exact"
    assert d["accepts"][0]["network"] == "stellar:testnet"
    assert d["accepts"][0]["amount"] == "200000"
    assert "payTo" in d["accepts"][0]
    assert d["resource"]["url"]


def test_facilitator_enabled_env(monkeypatch):
    monkeypatch.setenv("X402_FACILITATOR_ENABLED", "false")
    assert facilitator_enabled() is False
    monkeypatch.delenv("X402_FACILITATOR_ENABLED", raising=False)
    assert facilitator_enabled() is True

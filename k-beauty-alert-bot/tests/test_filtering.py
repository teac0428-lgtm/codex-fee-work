from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("collector", BASE_DIR / "collector.py")
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


def load_config():
    with (BASE_DIR / "keywords.yaml").open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def evaluate(title: str):
    return collector.evaluate_text(title.lower(), load_config())


def test_export_growth_passes():
    result = evaluate("K-beauty exports to the U.S. rise 28% as Korean brands expand retail distribution")
    assert result.send
    assert result.score >= 15
    assert "market_expansion" in result.evidence_groups


def test_distribution_agreement_passes():
    result = evaluate("Korean skincare brand signs distribution agreement with Ulta Beauty")
    assert result.send
    assert "contract" in result.evidence_groups


def test_mocra_regulation_passes():
    result = evaluate("New MoCRA requirements reshape Korean cosmetics exports to the U.S.")
    assert result.send
    assert "regulation" in result.evidence_groups


def test_korean_capacity_passes():
    result = evaluate("코스맥스, 미국 화장품 생산능력 증설")
    assert result.send
    assert result.matched_entities == ["Cosmax"]


def test_beauty_device_fda_passes():
    result = evaluate("뷰티 디바이스 업체, 미국 FDA 인증 획득")
    assert result.send
    assert "regulation" in result.evidence_groups


def test_best_serum_excluded():
    result = evaluate("10 Best Korean Serums You Need to Try")
    assert not result.send
    assert result.excluded


def test_sale_today_excluded():
    result = evaluate("This K-beauty moisturizer is 40% off today and on sale today")
    assert not result.send
    assert result.excluded
    assert "promotion_noise" in result.noise_groups


def test_how_to_use_it_immediate_excluded():
    result = evaluate("New K-beauty serum launch and how to use it")
    assert not result.send
    assert result.excluded
    assert "how to use it" in result.exclusion_reason


def test_stock_noise_excluded():
    result = evaluate("K-beauty stocks jump before market open as shares jump")
    assert not result.send
    assert result.excluded
    assert "market_noise" in result.noise_groups


def test_retail_sales_not_blocked_by_sale_substring():
    result = evaluate("K-beauty retail sales increased 20% in the U.S. as exports rose")
    assert result.send
    assert "promotion_noise" not in result.noise_groups


def test_beauty_device_on_sale_excluded():
    result = evaluate("Korean beauty device is on sale today")
    assert not result.send
    assert result.excluded
    assert "promotion_noise" in result.noise_groups

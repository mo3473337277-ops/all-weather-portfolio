"""测试回测引擎核心逻辑：趋势过滤、现金档位调整。"""
import numpy as np
import pandas as pd
import pytest
from allweather.backtest import _apply_trend_dip, adjust_nav_for_cash


def make_price_array(n_days=100, n_assets=5):
    """生成模拟价格数组，每天+0.05% 趋势向上。"""
    np.random.seed(42)
    rets = np.random.normal(0.0005, 0.01, (n_days, n_assets))
    prices = np.ones((n_days, n_assets))
    for i in range(1, n_days):
        prices[i] = prices[i-1] * (1 + rets[i])
    return prices


def test_adjust_nav_for_cash_full():
    nv = pd.Series(np.linspace(1.0, 2.0, 253), index=pd.date_range("2024-01-01", periods=253))
    nv_cash = adjust_nav_for_cash(nv, cash_ratio=0.30)
    # 30% cash should reduce total return
    assert nv_cash.iloc[-1] < nv.iloc[-1]
    assert nv_cash.iloc[0] == 1.0


def test_adjust_nav_for_cash_no_cash():
    nv = pd.Series(np.linspace(1.0, 2.0, 253), index=pd.date_range("2024-01-01", periods=253))
    nv_cash = adjust_nav_for_cash(nv, cash_ratio=0.0)
    assert abs(nv_cash.iloc[-1] - nv.iloc[-1]) < 1e-10


class TestApplyTrendDip:
    """核心：_apply_trend_dip 是刚修复了 bug 的函数，必须覆盖。"""

    def setup_method(self):
        self.prices = make_price_array(100, 5)
        self.col_idx = {"asset1": 0, "asset2": 1, "credit": 2, "nonferr": 3, "sp500": 4}

    def test_nonferr_trend_filter_below_sma(self):
        """nonferr 价格低于 SMA → 清仓转 credit"""
        w = np.array([0.0, 0.0, 0.3, 0.2, 0.5])
        sma_params = {"nf_window": 75, "nf_sma": float(self.prices[80, 3] * 1.05),  # SMA > price
                      "au_sma": None, "eq_smas": {}}
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip, None)
        assert result[3] == 0.0, "nonferr 应被清仓"
        assert result[2] > 0.3, "credit 应接收 nonferr 权重"

    def test_nonferr_trend_filter_above_sma(self):
        """nonferr 价格高于 SMA → 不清仓"""
        w = np.array([0.0, 0.0, 0.3, 0.2, 0.5])
        sma_params = {"nf_window": 75, "nf_sma": float(self.prices[80, 3] * 0.95),  # SMA < price
                      "au_sma": None, "eq_smas": {}}
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip, None)
        assert result[3] > 0, "nonferr 应保持持仓"

    def test_equity_trend_filter_below_sma(self):
        """SP500 价格低于 SMA → 清仓转 credit (这是之前的 bug!)"""
        w = np.array([0.0, 0.0, 0.3, 0.0, 0.2])  # sp500 at index 4
        sma_params = {"nf_window": 75, "nf_sma": None,
                      "au_sma": None,
                      "eq_smas": {"sp500": float(self.prices[80, 4] * 1.05)}}  # SMA > price
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip, None)
        assert result[4] == 0.0, "SP500 低于 SMA 应被清仓"
        assert result[2] > 0.3, "credit 应接收 SP500 权重"

    def test_equity_trend_filter_above_sma(self):
        """SP500 价格高于 SMA → 不清仓 (之前的 bug: 无论价格如何都清仓)"""
        w = np.array([0.0, 0.0, 0.3, 0.0, 0.2])
        sma_params = {"nf_window": 0, "nf_sma": None, "au_sma": None,
                      "eq_smas": {"sp500": float(self.prices[80, 4] * 0.95)}}  # SMA < price
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip, None)
        assert result[4] > 0, "SP500 高于 SMA 应保持持仓 (这是之前 bug 的关键测试)"

    def test_eq_sma_not_in_index(self):
        """eq_smas 中的资产不在 col_idx 中 → 忽略，不报错"""
        w = np.array([0.0, 0.2, 0.3, 0.0, 0.5])
        sma_params = {"nf_window": 0, "nf_sma": None, "au_sma": None,
                      "eq_smas": {"nonexistent": 1.5}}
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip, None)
        assert abs(result.sum() - w.sum()) < 1e-10, "总和不应变化"

    def test_no_credit_no_transfer(self):
        """credit 不在组合中 → eq_smas 块跳过（credit_idx<0）"""
        col_idx_no_credit = {"asset1": 0, "sp500": 1, "nonferr": 2}
        w = np.array([0.3, 0.3, 0.4])
        sma_params = {"nf_window": 0, "nf_sma": None,
                      "au_sma": None, "eq_smas": {"sp500": 1000.0}}
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, col_idx_no_credit, sma_params, dip, None)
        # 没有 credit 时 eq_smas 块不执行，权重不变
        assert result[1] == 0.3

    def test_post_process_max_w_clips(self):
        """post_process_max_w 应截断极端权重"""
        w = np.array([0.1, 0.6, 0.3, 0.0, 0.0])
        sma_params = {"nf_window": 0, "nf_sma": None, "au_sma": None, "eq_smas": {}}
        dip = {"gold_trend": False, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), self.prices, 80, self.col_idx, sma_params, dip,
                                   post_process_max_w=0.4)
        # 0.6 被截断到 0.4（可能会被重新归一化略微推高）
        assert result[1] < 0.55, f"权重应被显著截断, got {result[1]:.4f}"

    def test_gold_trend_filter_below_sma(self):
        """黄金趋势过滤: 价格低于 SMA → 清仓转 credit"""
        w = np.array([0.0, 0.0, 0.3, 0.0, 0.0])
        col_idx_gold = {"asset1": 0, "credit": 1, "gold": 2}
        prices = make_price_array(100, 3)
        sma_params = {"nf_window": 0, "nf_sma": None,
                      "au_sma": float(prices[80, 2] * 1.05), "eq_smas": {}}
        dip = {"gold_trend": True, "gold_dip_threshold": None, "gold_dip_boost": 2.5,
               "gold_dip_cap": None, "gold_peak": 1.0, "gold_boosted": False,
               "gold_boosted_flag": False, "hs300_value_dip": False, "hs300_boost": None}
        result = _apply_trend_dip(w.copy(), prices, 80, col_idx_gold, sma_params, dip, None)
        assert result[2] == 0.0

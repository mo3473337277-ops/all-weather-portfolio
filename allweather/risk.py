"""风控模块 —— 逆波动率加权、分层风险平价、HS300 AND抄底。"""
import numpy as np
import pandas as pd


def inverse_vol_weights(returns: pd.DataFrame, window: int = 60,
                        max_w: float = 0.25, min_w: float = 0.02) -> pd.Series:
    if len(returns) < 20:
        n = returns.shape[1]
        return pd.Series(1.0 / n, index=returns.columns)
    recent = returns.tail(window)
    vols = recent.std() * np.sqrt(252)
    inv_vol = 1 / vols.replace(0, np.nan)
    raw = inv_vol / inv_vol.sum()
    capped = raw.clip(lower=min_w, upper=max_w)
    return capped / capped.sum()


def hierarchical_rp_weights(
    returns: pd.DataFrame,
    bucket_groups: dict,
    window: int = 60,
    max_w: float = 0.25,
    min_w: float = 0.02,
    bucket_method: str = "equal",
) -> pd.Series:
    if len(returns) < 20:
        n = returns.shape[1]
        return pd.Series(1.0 / n, index=returns.columns)

    recent = returns.tail(window)
    n_buckets = len(bucket_groups)

    bucket_w = {}
    bucket_vol = {}
    for bname, assets in bucket_groups.items():
        valid = [a for a in assets if a in recent.columns]
        if not valid:
            continue
        brets = recent[valid]
        vols = brets.std() * np.sqrt(252)
        inv = 1 / vols.replace(0, np.nan)
        w = inv / inv.sum()
        bucket_w[bname] = w
        port_r = (brets * w).sum(axis=1)
        bucket_vol[bname] = port_r.std() * np.sqrt(252)

    if bucket_method == "equal":
        bucket_alloc = {k: 1.0 / n_buckets for k in bucket_w}
    elif bucket_method in ("inverse_vol", "risk_parity"):
        # 注意：true risk parity（等风险贡献）未实现，
        # "risk_parity" 和 "inverse_vol" 目前都是桶级逆波动率
        inv_vols = {k: 1.0 / v for k, v in bucket_vol.items() if v > 0.001}
        total = sum(inv_vols.values())
        bucket_alloc = {k: v / total for k, v in inv_vols.items()}
    else:
        raise ValueError(f"未知 bucket_method: {bucket_method}")

    raw = pd.Series(0.0, index=returns.columns)
    for bname, bw in bucket_alloc.items():
        for asset in bucket_w[bname].index:
            raw[asset] = bw * bucket_w[bname][asset]

    capped = raw.clip(lower=min_w, upper=max_w)
    return capped / capped.sum()


def _pb_pe_percentile(data, date, min_obs=252):
    """提取截至日期的 PB/PE 分位值。返回 (当前值, 百分位) 或 (None, None)。"""
    if data is None:
        return None, None
    to_date = data[data.index <= date]
    if len(to_date) < min_obs:
        return None, None
    curr = to_date.iloc[-1]
    pct = (to_date < curr).sum() / len(to_date) * 100
    return curr, pct


def hs300_dip_check(pb_data, pe_data, prices, d, i, hs300_peak, hs300_boosted,
                    threshold, sma_window, exit_recovery,
                    pb_entry, pe_exit, boost_mult):
    """HS300 AND抄底 — PB分位确认入场 + PE分位确认出场。

    Returns:
        (is_boosted, boost_mult): boost_mult is None when no action needed.
    """
    pb_curr, pb_pct = _pb_pe_percentile(pb_data, d)
    pe_curr, pe_pct = _pb_pe_percentile(pe_data, d)
    fundamental_ok = pb_pct is not None and pb_pct < pb_entry
    exit_fundamental = pe_pct is not None and pe_pct > pe_exit

    hs300_dd = prices.iloc[i]["hs300"] / hs300_peak - 1
    curr_hs = prices.iloc[i]["hs300"]
    dip_sma = prices["hs300"].iloc[max(0, i - sma_window):i].mean()

    if hs300_boosted:
        if hs300_dd > -exit_recovery and exit_fundamental:
            return False, None
        return True, None
    if hs300_dd <= -threshold and fundamental_ok and curr_hs > dip_sma:
        return True, boost_mult
    return False, None



def dynamic_cash_ratio(hs300_series: pd.Series, i: int) -> float:
    """基于 HS300 3 年回撤的动态现金比例。

    回撤 >20% → 满仓(0% 现金)
    回撤 <5%  → 保守(30% 现金)
    中间区间  → 温和(15% 现金)
    """
    peak_3y = hs300_series.iloc[max(0, i - 756):i + 1].max()
    dd_3y = hs300_series.iloc[i] / peak_3y - 1
    if dd_3y <= -0.20:
        return 0.0
    elif dd_3y >= -0.05:
        return 0.30
    return 0.15


def hs300_signal_snapshot(pb_data, pe_data, prices, d, i, hs300_peak, hs300_boosted, boost_mult):
    sig_dd = round(float(prices.iloc[i]["hs300"] / hs300_peak - 1), 4)
    sig_pb_val, sig_pb_pct = _pb_pe_percentile(pb_data, d)
    sig_pe_val, sig_pe_pct = _pb_pe_percentile(pe_data, d)
    sig_pb_pct = round(sig_pb_pct, 1) if sig_pb_pct is not None else None
    sig_pe_pct = round(sig_pe_pct, 1) if sig_pe_pct is not None else None
    return {
        'dd_pct': sig_dd,
        'pb_pctile': sig_pb_pct,
        'pb_value': sig_pb_val,
        'pe_pctile': sig_pe_pct,
        'pe_value': sig_pe_val,
        'active': hs300_boosted,
        'boost': boost_mult if hs300_boosted else None,
    }


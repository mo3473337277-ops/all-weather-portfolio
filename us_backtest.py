#!/usr/bin/env python3
"""
美股稳健全天候策略 · 回测脚本
==============================
5 ETF: SPY / QQQ / TLT / GLD / SHY
方法: 逆波动率加权 + 趋势过滤(SMA75) + 期权成本扣减
"""
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ===== 配置 =====
ASSETS = {
    'SPY': {'name': '标普500',     'bucket': 'growth_up'},
    'QQQ': {'name': '纳斯达克100', 'bucket': 'growth_up'},
    'TLT': {'name': '20+年国债',   'bucket': 'growth_down'},
    'GLD': {'name': '黄金',        'bucket': 'inflation_up'},
    'SHY': {'name': '1-3年国债',   'bucket': 'inflation_down'},
}

RISK_BUDGET = {'growth_up': 0.25, 'growth_down': 0.25,
               'inflation_up': 0.25, 'inflation_down': 0.25}

IV_WINDOW = 20          # 逆波动率窗口
TREND_WINDOW = 75       # 趋势过滤窗口
MAX_WEIGHT = 0.35       # 单资产上限
OPTION_COST = 0.005     # 期权成本 0.5%/年
START_DATE = '2005-01-01'
END_DATE = '2026-07-01'

# ===== 下载数据 =====
print("下载美股数据...")
prices = yf.download(list(ASSETS.keys()), start=START_DATE, end=END_DATE)['Close']
prices = prices.dropna()

# 每月最后一个交易日
monthly_dates = prices.resample('ME').last().index
print(f"数据: {prices.index[0].strftime('%Y-%m-%d')} ~ {prices.index[-1].strftime('%Y-%m-%d')}, {len(prices)}天\n")

# ===== 回测 =====
nv = 1.0
nv_history = [1.0]
weight_history = {}
trade_count = 0

for i, date in enumerate(monthly_dates):
    if date not in prices.index:
        continue

    # 取窗口数据
    window = prices.loc[:date].tail(max(IV_WINDOW, TREND_WINDOW) + 5)

    # 1. 逆波动率权重
    rets = window.pct_change().dropna().tail(IV_WINDOW)
    vols = rets.std() * np.sqrt(252)
    vols = vols.replace(0, 0.01)  # 避免除零
    inv_vols = 1 / vols

    # 2. 桶级分配
    bucket_inv_vol = {}
    for bucket, tickers in [('growth_up', ['SPY','QQQ']), ('growth_down', ['TLT']),
                             ('inflation_up', ['GLD']), ('inflation_down', ['SHY'])]:
        bucket_inv_vol[bucket] = sum(inv_vols[t] for t in tickers if t in inv_vols)

    weights = {}
    for ticker in ASSETS:
        bucket = ASSETS[ticker]['bucket']
        if bucket_inv_vol[bucket] > 0:
            w = (inv_vols[ticker] / bucket_inv_vol[bucket]) * RISK_BUDGET[bucket]
        else:
            w = 0
        weights[ticker] = min(w, MAX_WEIGHT)

    # 3. 趋势过滤（触发 → 减半 → 转到 SHY）
    for ticker in ['SPY', 'QQQ', 'TLT']:
        if ticker in window.columns and len(window) >= TREND_WINDOW:
            sma = window[ticker].rolling(TREND_WINDOW).mean().iloc[-1]
            if window[ticker].iloc[-1] < sma:
                weights['SHY'] += weights[ticker] * 0.5
                weights[ticker] *= 0.5

    # 归一化
    total = sum(weights.values())
    weights = {k: v/total for k, v in weights.items()}

    # 4. 计算期间收益
    if i + 1 < len(monthly_dates):
        next_date = monthly_dates[i + 1]
        if next_date in prices.index:
            period_ret = sum(weights[t] * (prices.loc[next_date, t] / prices.loc[date, t] - 1)
                           for t in weights if t in prices.columns)
            nv *= (1 + period_ret)
            trade_count += 1
        else:
            period_ret = 0
    else:
        period_ret = 0

    nv_history.append(nv)
    weight_history[date] = weights

# 期权成本扣减
n_years = len(monthly_dates) / 12
option_drag = OPTION_COST * n_years
nv_after_option = nv * (1 - option_drag)

# 计算指标
nv_series = pd.Series(nv_history[1:], index=monthly_dates[:len(nv_history)-1])
daily_ret = nv_series.pct_change().dropna()
cagr = (nv_series.iloc[-1]) ** (1/n_years) - 1
vol = daily_ret.std() * np.sqrt(12)
mdd = (nv_series / nv_series.cummax() - 1).min()
sharpe = (cagr - 0.02) / vol if vol > 0 else 0

# 输出结果
print("=" * 60)
print("  美股稳健全天候 · 回测结果")
print(f"  {monthly_dates[0].strftime('%Y-%m-%d')} ~ {monthly_dates[-1].strftime('%Y-%m-%d')}")
print("=" * 60)
print(f"  CAGR:       {cagr*100:>6.2f}%")
print(f"  波动率(月):  {vol*100:>6.2f}%")
print(f"  最大回撤:    {mdd*100:>6.2f}%")
print(f"  Sharpe:     {sharpe:>6.2f}")
print(f"  累计收益:    {(nv_series.iloc[-1]-1)*100:>6.1f}%")
print(f"  期权成本:    -{option_drag*100:.1f}%")
print(f"  净累计收益:   {(nv_after_option-1)*100:>6.1f}%")

# 最近权重
print(f"\n  最新权重 ({monthly_dates[-1].strftime('%Y-%m-%d')}):")
last_w = weight_history[monthly_dates[-1]]
for t, w in sorted(last_w.items(), key=lambda x: x[1], reverse=True):
    print(f"    {t:>5} ({ASSETS[t]['name']:<12}): {w*100:>5.1f}%")

# 画图
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
axes[0].plot(nv_series.index, nv_series.values, label='Portfolio NAV', linewidth=1.5)
axes[0].set_title('Cumulative NAV')
axes[0].grid(True)

# 权重热力图
w_df = pd.DataFrame(weight_history).T
axes[1].stackplot(w_df.index, *[w_df[t] for t in w_df.columns],
                  labels=[f"{t}" for t in w_df.columns], alpha=0.7)
axes[1].set_title('Weight History')
axes[1].legend(fontsize=7, loc='upper left')
axes[1].set_ylim(0, 1)

plt.tight_layout()
plt.show()

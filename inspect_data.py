#!/usr/bin/env python3
"""
数据巡检脚本 —— 展示近60天数据，检测重复/跳跃异常
====================================================
用法: python inspect_data.py
"""
import os
import pandas as pd
import numpy as np

DATA_DIR = 'data'

# 要检查的文件列表
FILES = {
    '沪深300 ETF':      'hs300.csv',
    '沪深300 指数':      'hs300_idx.csv',
    '标普500':          'us_sp500.csv',
    '城投债':           'bond_credit.csv',
    '10年国债':         'bond_10y_etf.csv',
    '30年国债':         'bond_30y_etf.csv',
    '黄金 ETF':         'gold.csv',
    '伦敦金':           'london_gold.csv',
    '有色金属':         'nonferr.csv',
    '有色指数':         'nonferr_idx.csv',
    '南方原油':         'wti.csv',
    '沪铜':             'shfe_copper.csv',
    '美元人民币':       'usdcny.csv',
    '标普500指数':      'sp500_idx.csv',
    '国债指数':         'treasury_idx.csv',
    'WTI原油USD':       'wti_usd.csv',
    '信用债指数':       'credit_idx.csv',
    '收益率(10Y/30Y)':  'cgb_yields_full.csv',
}

LOOKBACK_DAYS = 60  # 往回看的天数

print("=" * 75)
print("  数据巡检 —— 近 60 天数据 & 异常检测")
print("=" * 75)

for name, fname in FILES.items():
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        print(f"\n  ❌ {name} ({fname}): 文件不存在")
        continue

    df = pd.read_csv(path)
    dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
    df[dc] = pd.to_datetime(df[dc])
    df = df.sort_values(dc).set_index(dc)

    # 只看最近 LOOKBACK_DAYS 天
    cutoff = df.index.max() - pd.Timedelta(days=LOOKBACK_DAYS)
    recent = df[df.index >= cutoff]

    if len(recent) == 0:
        print(f"\n  ⚠️ {name}: 近{LOOKBACK_DAYS}天无数据")
        continue

    vc = [c for c in df.columns if c != dc][0]
    vals = recent[vc].values

    # ---- 异常检测 ----
    warnings = []

    # 1. 连续相同值（前向填充痕迹）
    same_streak = 0
    max_streak = 0
    for i in range(1, len(vals)):
        if vals[i] == vals[i-1]:
            same_streak += 1
            max_streak = max(max_streak, same_streak)
        else:
            same_streak = 0
    if max_streak >= 3:
        warnings.append(f"🔴 连续{max_streak+1}天数值不变（可能是前向填充）")

    # 2. 单日跳跃 > 10%（可能数据口径切换）
    daily_chg = np.abs(np.diff(vals) / vals[:-1])
    jumps = np.where(daily_chg > 0.10)[0]
    if len(jumps) > 0:
        for j in jumps:
            dt = recent.index[j+1]
            warnings.append(f"🟡 {dt.strftime('%m-%d')} 单日变动 {daily_chg[j]*100:.1f}%（可能口径不一致）")

    # 3. 数据滞后（最新日期距今 > 5 天）
    lag = (pd.Timestamp.now() - df.index.max()).days
    if lag > 5:
        warnings.append(f"🟠 数据滞后 {lag} 天（最新={df.index.max().strftime('%m-%d')}）")

    # ---- 输出 ----
    if warnings:
        status = "⚠️"
    else:
        status = "✅"

    print(f"\n  {'─'*70}")
    print(f"  {status} {name} ({fname})")
    print(f"     期间: {recent.index[0].strftime('%Y-%m-%d')} ~ {recent.index[-1].strftime('%Y-%m-%d')}")
    print(f"     行数: {len(recent)} | 最新值: {vals[-1]:.4f} | 均值: {vals.mean():.4f} | 最小: {vals.min():.4f} | 最大: {vals.max():.4f}")

    if warnings:
        for w in warnings:
            print(f"     {w}")
    else:
        print(f"     ✅ 未检测到异常")

    # 每 10 天显示一行（太多看不过来）
    print(f"     {'日期':<12} {'数值':>10}   {'日变动':>8}")
    step = max(1, len(recent) // 8)  # 最多显示 8 行
    prev_val = None
    for i, (dt, row) in enumerate(recent.iterrows()):
        if i % step == 0 or i == len(recent) - 1:
            cur = row[vc]
            chg_str = ""
            if prev_val is not None and prev_val != 0:
                pct = (cur / prev_val - 1) * 100
                chg_str = f"{pct:>+7.2f}%"
            print(f"     {dt.strftime('%Y-%m-%d'):<12} {cur:>10.4f}   {chg_str}")
            prev_val = cur

print(f"\n{'='*75}")
print("  巡检完成")
print("=" * 75)
print("  图例: 🔴 严重  🟡 警告  🟠 次级  ✅ 正常")

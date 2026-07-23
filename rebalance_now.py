#!/usr/bin/env python3
"""
全天候策略 · 一键调仓脚本（每月运行一次）
==========================================
用法:
  python rebalance_now.py                    # 三策略对比
  python rebalance_now.py --strat B-RP       # 只看风险平价
  python rebalance_now.py --strat B-Con      # 只看保守增强
  python rebalance_now.py --strat B-RP --amount 500000  # 输入持仓金额

每次运行自动拉取最新数据（不跳过），确保权重基于最新行情。
"""
import os, sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════
# Step 1: 更新数据（每次强制拉到最新）
# ═══════════════════════════════════════════
def update_data():
    import akshare as ak

    print("=" * 55)
    print("  Step 1/3: 更新数据到最新...")
    print("=" * 55)

    # —— 收益率（v2 合成核心）——
    df = ak.bond_zh_us_rate()
    df = df.rename(columns={'日期': 'date', '中国国债收益率10年': 'y10',
                             '中国国债收益率30年': 'y30'})
    df['date'] = pd.to_datetime(df['date'])
    df[['date', 'y10', 'y30']].dropna().to_csv(
        DATA_DIR / 'cgb_yields_full.csv', index=False)
    print(f"  cgb_yields_full → {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"  最新 10Y={df['y10'].iloc[-1]:.2f}%  30Y={df['y30'].iloc[-1]:.2f}%")

    # —— ETF / 指数数据（强制拉到今天）——
    from allweather.fetch import fetch_all
    today_str = datetime.today().strftime("%Y%m%d")
    print(f"  拉取目标日期: {today_str}")
    fetch_all(force=True, end=today_str)

    # —— PE/PB 前向填充 ——
    today_date = pd.Timestamp(datetime.today().strftime("%Y-%m-%d"))
    for fname in ['hs300_pb.csv', 'hs300_pe.csv']:
        path = DATA_DIR / fname
        if not path.exists():
            continue
        d = pd.read_csv(path)
        dc = [c for c in d.columns if 'date' in c.lower() or '日期' in c][0]
        d[dc] = pd.to_datetime(d[dc])
        last = d[dc].max()
        if last < today_date:
            row = d.iloc[-1:].copy()
            row[dc] = today_date
            d = pd.concat([d, row], ignore_index=True)
            d = d.drop_duplicates(subset=dc, keep='last').sort_values(dc)
            d.to_csv(path, index=False)
            print(f"  {fname}: {last.strftime('%Y-%m-%d')} → {today_date.strftime('%Y-%m-%d')} (填充)")

    print("✅ 数据更新完成\n")


# ═══════════════════════════════════════════
# Step 2: 各资产最近 5 日净值
# ═══════════════════════════════════════════
def show_recent_5d():
    print("=" * 55)
    print("  Step 2/3: 各资产最近 5 日净值")
    print("=" * 55)

    asset_map = [
        ('hs300',       'hs300.csv',        '510300', '沪深300'),
        ('us_sp500',    'us_sp500.csv',     '513500', '标普500'),
        ('bond_credit', 'bond_credit.csv',  '511220', '城投债'),
        ('bond_10y',    'bond_10y_etf.csv', '511260', '10年国债'),
        ('bond_30y',    'bond_30y_etf.csv', '511130', '30年国债'),
        ('gold',        'gold.csv',         '518880', '黄金'),
        ('nonferr',     'nonferr.csv',      '159980', '有色金属'),
        ('wti',         'wti.csv',          '501018', '南方原油'),
    ]

    for prefix, filename, code, name in asset_map:
        fpath = DATA_DIR / filename
        if not fpath.exists():
            print(f"  ⚠️ {filename} 不存在，跳过")
            continue

        df = pd.read_csv(fpath)
        dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
        df[dc] = pd.to_datetime(df[dc])
        df = df.sort_values(dc).set_index(dc)
        recent = df.tail(5)

        vc = [c for c in df.columns][0]

        print(f"\n  {name} ({code})")
        print(f"  {'日期':<12} {'净值/价格'}")
        print(f"  {'-'*25}")
        for date, row in recent.iterrows():
            print(f"  {date.strftime('%Y-%m-%d')}  {row[vc]:>10.4f}")

        chg = (recent.iloc[-1][vc] / recent.iloc[0][vc] - 1) * 100
        print(f"  {'最新':<12} | 5日涨跌: {chg:+.2f}%")


# ═══════════════════════════════════════════
# Step 3: 调仓信号 & 权重
# ═══════════════════════════════════════════
def show_rebalance():
    print(f"\n{'='*55}")
    print("  Step 3/3: 调仓信号 & 目标权重")
    print("=" * 55)

    args = sys.argv[1:]
    # 不加 --no-auto-fetch，让 rebalance 自己再拉一次确保最新
    os.system(f"python -m allweather.rebalance {' '.join(args)}")


# ═══════════════════════════════════════════
if __name__ == "__main__":
    update_data()
    show_recent_5d()
    show_rebalance()

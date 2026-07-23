#!/usr/bin/env python3
"""
全天候策略 · 数据更新脚本（只更新数据，不跑回测）
================================================
用法:
  python update_data.py              # 增量更新到 config 里的 BACKTEST_END
  python update_data.py --force      # 强制重拉全部数据
  python update_data.py --end 2026-07-01  # 更新到指定日期
"""
import os, sys, argparse, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def get_latest_date(path):
    try:
        df = pd.read_csv(path)
        dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
        df[dc] = pd.to_datetime(df[dc])
        return df[dc].max()
    except: return None


def get_config_end_date():
    sys.path.insert(0, str(ROOT))
    from allweather.config import BACKTEST_END
    return pd.Timestamp(BACKTEST_END)


def update_all_data(force=False):
    sys.path.insert(0, str(ROOT))
    from allweather.fetch import fetch_all
    fetch_all(force=force)


def update_yields():
    import akshare as ak
    path = DATA_DIR / "cgb_yields_full.csv"
    old_date = get_latest_date(path)
    df = ak.bond_zh_us_rate()
    df = df.rename(columns={'日期':'date','中国国债收益率10年':'y10','中国国债收益率30年':'y30'})
    df['date'] = pd.to_datetime(df['date'])
    df = df[['date','y10','y30']].dropna().sort_values('date')
    df.to_csv(path, index=False)
    new_date = df['date'].max()
    old_str = old_date.strftime('%Y-%m-%d') if old_date else '首次'
    print(f"  cgb_yields_full  {old_str} -> {new_date.strftime('%Y-%m-%d')}  ({len(df)}行)")
    print(f"  最新 10Y={df['y10'].iloc[-1]:.2f}%  30Y={df['y30'].iloc[-1]:.2f}%")


def fill_gaps(target_date):
    """把还没到目标日期的低频数据文件前向填充到最后交易日"""
    fill_list = [
        'hs300_pb.csv', 'hs300_pe.csv'  # 仅 PE/PB 无自动更新接口
    ]
    for fname in fill_list:
        path = DATA_DIR / fname
        if not path.exists(): continue
        df = pd.read_csv(path)
        dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
        df[dc] = pd.to_datetime(df[dc])
        last = df[dc].max()
        if last >= target_date:
            print(f"  {fname}: ✅ ({last.strftime('%Y-%m-%d')})")
            continue
        row = df.iloc[-1:].copy()
        row[dc] = target_date
        df = pd.concat([df, row], ignore_index=True)
        df = df.drop_duplicates(subset=dc, keep='last').sort_values(dc)
        df.to_csv(path, index=False)
        print(f"  {fname}: {last.strftime('%Y-%m-%d')} -> {target_date.strftime('%Y-%m-%d')} (填充)")


def summary():
    print("\n" + "="*55)
    print("  数据文件最新日期")
    print("="*55)
    for f in sorted(os.listdir(DATA_DIR)):
        if not f.endswith('.csv'): continue
        d = get_latest_date(DATA_DIR / f)
        if d: print(f"  {f:<30} -> {d.strftime('%Y-%m-%d')}")


def sample():
    print("\n" + "="*55)
    print("  抽样 (最新3行)")
    print("="*55)
    for kw in ['hs300.csv','bond_30y_etf','bond_10y_etf','gold.csv','nonferr.csv','us_sp500.csv']:
        matches = [f for f in os.listdir(DATA_DIR) if kw in f]
        if not matches: continue
        d = pd.read_csv(DATA_DIR / matches[0])
        dc = [c for c in d.columns if 'date' in c.lower() or '日期' in c][0]
        d[dc] = pd.to_datetime(d[dc])
        d = d.sort_values(dc).tail(3)
        vc = [c for c in d.columns if c != dc]
        print(f"\n  {matches[0]}")
        for _, r in d.iterrows():
            vs = '  '.join([f"{c}={r[c]:.4f}" if isinstance(r[c], float) else f"{c}={r[c]}" for c in vc])
            print(f"    {r[dc].strftime('%Y-%m-%d')}  {vs}")


def main():
    parser = argparse.ArgumentParser(description="全天候策略 · 数据更新")
    parser.add_argument("--force", action="store_true", help="强制重拉全部数据")
    parser.add_argument("--end", type=str, default=None, help="目标日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    target = pd.Timestamp(args.end) if args.end else get_config_end_date()
    print(f"\n{'='*55}")
    print(f"  🌤️ 数据更新")
    print(f"  {'='*55}")
    print(f"  目标日期: {target.strftime('%Y-%m-%d')}")

    print("\n[1/3] 增量更新原有数据...")
    update_all_data(force=args.force)

    print("\n[2/3] v2 合成收益率...")
    update_yields()

    print("\n[3/3] 补齐缺口...")
    fill_gaps(target)

    summary()
    sample()

    print(f"\n🎉 数据更新完成！运行回测: python main.py --no-excel")


if __name__ == "__main__":
    main()

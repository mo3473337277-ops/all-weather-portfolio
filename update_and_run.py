#!/usr/bin/env python3
"""
全天候策略 · 一键更新+回测
============================
用法:
  python update_and_run.py --start 2026-06-01 --end 2026-07-01
  python update_and_run.py --force
  python update_and_run.py --no-fetch
"""
import os, sys, argparse, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def is_colab():
    try: import google.colab; return True
    except ImportError: return False


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
    print(f"  cgb_yields  {old_str} -> {new_date.strftime('%Y-%m-%d')}  ({len(df)}行)")
    print(f"  10Y={df['y10'].iloc[-1]:.2f}%  30Y={df['y30'].iloc[-1]:.2f}%")
    return df


def fill_gaps(target_date):
    """把还没到目标日期的低频数据文件前向填充到最后交易日"""
    fill_list = [
        'hs300_pb.csv','hs300_pe.csv','london_gold.csv','shfe_copper.csv',
        'usdcny.csv','wti_usd.csv','sp500_idx.csv','treasury_idx.csv'
    ]
    for fname in fill_list:
        path = DATA_DIR / fname
        if not path.exists(): continue
        df = pd.read_csv(path)
        dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
        df[dc] = pd.to_datetime(df[dc])
        last = df[dc].max()
        if last >= target_date:
            print(f"  {fname}: ✅ 已覆盖 ({last.strftime('%Y-%m-%d')})")
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


def set_dates(start, end):
    path = ROOT / 'allweather' / 'config.py'
    with open(path, 'r') as f: content = f.read()
    s = re.search(r'BACKTEST_START\s*=\s*"([^"]+)"', content)
    e = re.search(r'BACKTEST_END\s*=\s*"([^"]+)"', content)
    if s: content = content.replace(f'BACKTEST_START = "{s.group(1)}"', f'BACKTEST_START = "{start}"')
    if e: content = content.replace(f'BACKTEST_END   = "{e.group(1)}"', f'BACKTEST_END   = "{end}"')
    with open(path, 'w') as f: f.write(content)
    return (s.group(1) if s else None, e.group(1) if e else None)


def run_backtest():
    os.chdir(ROOT)
    return os.system("python main.py --no-excel")


def main():
    parser = argparse.ArgumentParser(description="全天候策略 · 一键更新+回测")
    parser.add_argument("--force", action="store_true", help="强制重拉全部数据")
    parser.add_argument("--no-fetch", action="store_true", help="跳过数据更新")
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    args = parser.parse_args()

    # Drive 已在 Notebook 中手动挂载，这里只检查
    if is_colab() and not Path('/content/drive').exists():
        print("❌ Drive 未挂载！先在 Notebook 单元格运行:")
        print("   from google.colab import drive")
        print("   drive.mount('/content/drive')")
        sys.exit(1)
    if is_colab():
        cp = Path('/content/drive/MyDrive/all-weather-portfolio')
        if cp.exists(): os.chdir(cp)

    target = pd.Timestamp(args.end) if args.end else get_config_end_date()
    print(f"\n{'='*55}")
    print(f"  🌤️ 全天候策略 · 自动更新回测")
    print(f"  {'='*55}")
    print(f"  目标日期: {target.strftime('%Y-%m-%d')}")

    orig = None
    if args.start or args.end:
        orig = set_dates(args.start or '2005-04-08', args.end or target.strftime('%Y-%m-%d'))
        print(f"  回测期间: {args.start or '2005-04-08'} ~ {args.end or target.strftime('%Y-%m-%d')}")

    if not args.no_fetch:
        print("\n[Step 1/4] 增量更新..."); update_all_data(force=args.force)
        print("\n[Step 2/4] v2 合成收益率..."); update_yields()
        print("\n[Step 3/4] 补齐缺口..."); fill_gaps(target)
        summary(); sample()

    print("\n[Step 4/4] 回测...")
    ret = run_backtest()

    if orig: set_dates(orig[0], orig[1]); print(f"\n✅ 已恢复原始期间: {orig[0]} ~ {orig[1]}")
    print("\n🎉 完成!" if ret == 0 else "\n⚠️ 有错误，查看日志")
    sys.exit(ret)

if __name__ == "__main__":
    main()

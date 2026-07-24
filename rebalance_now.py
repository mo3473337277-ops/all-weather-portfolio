#!/usr/bin/env python3
"""
全天候策略 · 一键调仓脚本（每月运行一次）
==========================================
用法:
  python rebalance_now.py                    # 三策略对比
  python rebalance_now.py --strat B-RP       # 只看风险平价
  python rebalance_now.py --strat B-RP --amount 500000  # 输入持仓金额

数据更新策略:
  - 增量拉取，主接口最多重试3次
  - 主接口失败 → 备用接口 → 智能选列（挑更接近历史值的列）
  - 新增数据超过前值20% → 报警跳过
"""
import os, sys, time, random
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT))
GRACE_DAYS = 0
MAX_DAILY_CHG = 0.20  # 单日变动超20%视为异常

def update_data():
    import akshare as ak
    print("=" * 65)
    print("  Step 1/3: 智能增量更新数据")
    print("=" * 65)
    today = datetime.today()
    today_str = today.strftime("%Y%m%d")
    today_dt = pd.Timestamp(today.strftime("%Y-%m-%d"))

    print("\n  [1/3] 国债收益率...")
    yp = DATA_DIR / "cgb_yields_full.csv"
    need = True
    if yp.exists():
        old = pd.read_csv(yp)
        dc = [c for c in old.columns if 'date' in c.lower() or '日期' in c][0]
        old[dc] = pd.to_datetime(old[dc])
        if (today_dt - old[dc].max()).days <= GRACE_DAYS:
            print(f"    ✅ 已最新 ({old[dc].max().strftime('%Y-%m-%d')})，跳过")
            need = False
    if need:
        df = ak.bond_zh_us_rate()
        df = df.rename(columns={'日期':'date','中国国债收益率10年':'y10','中国国债收益率30年':'y30'})
        df['date'] = pd.to_datetime(df['date'])
        df = df[['date','y10','y30']].dropna().sort_values('date')
        df.to_csv(yp, index=False)
        print(f"    ✅ 已更新 → {df['date'].iloc[-1].strftime('%Y-%m-%d')} (10Y={df['y10'].iloc[-1]:.2f}% 30Y={df['y30'].iloc[-1]:.2f}%)")

    print("\n  [2/3] ETF 数据...")
    etfs = [
        ('hs300.csv','510300','沪深300'), ('bond_30y_etf.csv','511130','30年国债'),
        ('bond_10y_etf.csv','511260','10年国债'), ('bond_credit.csv','511220','城投债'),
        ('gold.csv','518880','黄金'), ('nonferr.csv','159980','有色金属'),
        ('us_sp500.csv','513500','标普500'), ('wti.csv','501018','南方原油'),
    ]
    up, sk, fl = 0, 0, 0
    for fname, code, name in etfs:
        fp = DATA_DIR / fname
        if not fp.exists():
            print(f"    ⚠️ {name}: 文件不存在"); fl += 1; continue
        ex = pd.read_csv(fp)
        dc = [c for c in ex.columns if 'date' in c.lower() or '日期' in c][0]
        ex[dc] = pd.to_datetime(ex[dc])
        vc = [c for c in ex.columns if c != dc][0]
        last_dt = ex[dc].max()
        last_val = ex[vc].iloc[-1]
        if (today_dt - last_dt).days <= GRACE_DAYS:
            print(f"    ✅ {name}: 已最新 ({last_dt.strftime('%Y-%m-%d')})，跳过")
            sk += 1; continue

        ok = False

        # --- 主接口（3次重试）---
        for attempt in range(3):
            try:
                new = ak.fund_etf_hist_em(symbol=code, period='daily', start_date=last_dt.strftime("%Y%m%d"), end_date=today_str)
                if len(new) > 0:
                    new = new.rename(columns={'日期':'date','收盘':'close'})
                    new['date'] = pd.to_datetime(new['date'])
                    new = new[['date','close']].dropna()
                    # ✅ 异常检测
                    if new['close'].iloc[0] > 0 and abs(new['close'].iloc[0]/last_val - 1) > MAX_DAILY_CHG:
                        print(f"    🚨 {name}: 主接口异常跳变 ({last_val:.4f}→{new['close'].iloc[0]:.4f})，丢弃")
                        ok = True; break
                    ex = pd.concat([ex,new]).drop_duplicates('date').sort_values('date')
                    ex.to_csv(fp, index=False)
                    print(f"    ✅ {name}: +{len(new)}行 → {ex['date'].iloc[-1].strftime('%Y-%m-%d')}")
                    up += 1; ok = True
                break
            except:
                if attempt < 2:
                    time.sleep(random.uniform(2.0, 4.0))

        # --- 备用接口（智能选列）---
        if not ok:
            try:
                new = ak.fund_etf_fund_info_em(fund=code, start_date=last_dt.strftime("%Y%m%d"), end_date=today_str)
                if len(new) > 0:
                    nc = new.columns.tolist()
                    date_col = [c for c in nc if '净值日期' in c or '日期' in c or 'date' in str(c).lower()][0]
                    new[date_col] = pd.to_datetime(new[date_col], errors='coerce')
                    new = new.dropna(subset=[date_col])
                    if len(new) == 0:
                        raise ValueError("无有效日期")

                    # 智能选列：单位净值 vs 累计净值，谁更接近 last_val 选谁
                    cand_cols = []
                    for c in nc:
                        if '单位净值' in c or '累计净值' in c:
                            s = pd.to_numeric(new[c], errors='coerce')
                            if s.notna().any():
                                cand_cols.append((c, s.iloc[0]))
                    if not cand_cols:
                        raise ValueError("无候选净值列")

                    best_col = min(cand_cols, key=lambda x: abs(x[1] - last_val))[0]
                    new['close'] = pd.to_numeric(new[best_col], errors='coerce')
                    new = new[[date_col, 'close']].dropna()
                    new = new.rename(columns={date_col:'date'}).sort_values('date')

                    # ✅ 异常检测
                    if len(new) > 0 and new['close'].iloc[0] > 0:
                        chg = abs(new['close'].iloc[0] / last_val - 1)
                        if chg > MAX_DAILY_CHG:
                            print(f"    🚨 {name}: 备用接口异常跳变 ({last_val:.4f}→{new['close'].iloc[0]:.4f}, +{chg*100:.1f}%)，丢弃")
                            ok = True
                        else:
                            ex = pd.concat([ex,new]).drop_duplicates('date').sort_values('date')
                            ex.to_csv(fp, index=False)
                            picked = "单位净值" if '单位净值' in best_col else "累计净值"
                            print(f"    🔄 {name}: +{len(new)}行 (备用,选{picked}) → {ex['date'].iloc[-1].strftime('%Y-%m-%d')}")
                            up += 1; ok = True
            except Exception as e:
                pass

        if not ok:
            gap = (today_dt - last_dt).days
            print(f"    ❌ {name}: 差{gap}天，接口均失败，保留旧数据"); fl += 1
        time.sleep(random.uniform(1.0, 2.5))

    print("\n  [3/3] PE/PB 估值...")
    for fname in ['hs300_pb.csv','hs300_pe.csv']:
        fp = DATA_DIR / fname
        if not fp.exists(): continue
        d = pd.read_csv(fp)
        dc = [c for c in d.columns if 'date' in c.lower() or '日期' in c][0]
        d[dc] = pd.to_datetime(d[dc])
        last = d[dc].max()
        if last < today_dt:
            row = d.iloc[-1:].copy(); row[dc] = today_dt
            d = pd.concat([d,row]).drop_duplicates(subset=dc,keep='last').sort_values(dc)
            d.to_csv(fp, index=False)
            print(f"    📌 {fname}: {last.strftime('%Y-%m-%d')} → {today_dt.strftime('%Y-%m-%d')} (填充)")
        else:
            print(f"    ✅ {fname}: 已最新")

    print(f"\n  ─── 汇总: ✅更新{up}  ⏭️跳过{sk}  ❌失败{fl} ───")
    if fl: print(f"  ⚠️ 失败项保留旧数据，不影响调仓")
    print("  ✅ 数据更新完成\n")


def show_prices():
    print("=" * 65)
    print("  Step 2/3: 近5日净值 & 涨跌幅")
    print("=" * 65)
    assets = [
        ('hs300.csv','510300','沪深300'), ('us_sp500.csv','513500','标普500'),
        ('bond_credit.csv','511220','城投债'), ('bond_10y_etf.csv','511260','10年国债'),
        ('bond_30y_etf.csv','511130','30年国债'), ('gold.csv','518880','黄金'),
        ('nonferr.csv','159980','有色金属'), ('wti.csv','501018','南方原油'),
    ]
    for fname, code, name in assets:
        fp = DATA_DIR / fname
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
        df[dc] = pd.to_datetime(df[dc]); df = df.sort_values(dc).set_index(dc)
        d5, d20, d60 = df.tail(5), df.tail(21), df.tail(61)
        vc = [c for c in df.columns if c != dc][0]
        cur = d5.iloc[-1][vc]
        c5 = (cur/d5.iloc[0][vc]-1)*100 if len(d5)>=2 else 0
        c20 = (cur/d20.iloc[0][vc]-1)*100 if len(d20)>=2 else 0
        c60 = (cur/d60.iloc[0][vc]-1)*100 if len(d60)>=2 else 0
        hi, lo = d20[vc].max(), d20[vc].min()
        rng = (cur-lo)/(hi-lo)*100 if hi>lo else 50
        vals = list(d5[vc])
        def arr(i): return "─" if i==0 else ("▲" if vals[i]>=vals[i-1] else "▼")
        print(f"\n  ┌─ {name} ({code}) {'─'*40}┐")
        print(f"  │ 最新: {cur:.4f}  ({d5.index[-1].strftime('%Y-%m-%d')})")
        print(f"  │ {'日期':<6} {'净值':>10}  ")
        for i, (dt, row) in enumerate(d5.iterrows()):
            print(f"  │ {dt.strftime('%m-%d'):<6} {row[vc]:>10.4f}  {arr(i)}")
        print(f"  │ 近 5日: {c5:>+7.2f}%   近20日: {c20:>+7.2f}%   近60日: {c60:>+7.2f}%")
        print(f"  │ 20日区间位置: {rng:.0f}% (0%=低点)")
        print(f"  └{'─'*55}┘")


def show_rebalance():
    print(f"\n{'='*65}")
    print("  Step 3/3: 调仓信号 & 目标权重")
    print("=" * 65)
    os.system(f"python -m allweather.rebalance {' '.join(sys.argv[1:])}")


if __name__ == "__main__":
    update_data()
    show_prices()
    show_rebalance()

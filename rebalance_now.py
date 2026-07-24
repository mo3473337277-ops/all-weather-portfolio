#!/usr/bin/env python3
"""
全天候策略 · 一键调仓脚本（每月运行一次）
==========================================
用法:
  python rebalance_now.py                    # 三策略对比
  python rebalance_now.py --strat B-RP       # 只看风险平价
  python rebalance_now.py --strat B-Con      # 只看保守增强
  python rebalance_now.py --strat B-RP --amount 500000  # 输入持仓金额

数据更新策略:
  - 增量拉取（缺几天补几天，不强制全量）
  - 主接口失败自动降级到备用接口
  - 少 2-3 天数据不影响回测和调仓
"""
import os, sys, time, random
from pathlib import Path
from datetime import datetime
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT))

GRACE_DAYS = 0  # 数据差 N 天以内不强制重拉

def update_data():
    import akshare as ak
    print("=" * 65)
    print("  Step 1/3: 智能增量更新数据")
    print("=" * 65)
    today = datetime.today()
    today_str = today.strftime("%Y%m%d")
    today_dt = pd.Timestamp(today.strftime("%Y-%m-%d"))

    # ---- 收益率 ----
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

    # ---- ETF ----
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
        last = ex[dc].max()
        if (today_dt - last).days <= GRACE_DAYS:
            sk += 1; continue
        ok = False
        # 主接口
        # 主接口（拟人重试）
        for attempt in range(2):
            try:
                new = ak.fund_etf_hist_em(symbol=code, period='daily', start_date=last.strftime("%Y%m%d"), end_date=today_str)
                if len(new) > 0:
                    new = new.rename(columns={'日期':'date','收盘':'close'})
                    new['date'] = pd.to_datetime(new['date'])
                    new = new[['date','close']].dropna()
                    ex = pd.concat([ex,new]).drop_duplicates('date').sort_values('date')
                    ex.to_csv(fp, index=False)
                    print(f"    ✅ {name}: +{len(new)}行 → {ex['date'].iloc[-1].strftime('%Y-%m-%d')}")
                    up += 1; ok = True
                break
            except:
                if attempt == 0:
                    time.sleep(random.uniform(2.0, 4.0))

        # 备用接口
        if not ok:
            try:
                new = ak.fund_etf_fund_info_em(fund=code, start_date=last.strftime("%Y%m%d"), end_date=today_str)
                if len(new) > 0:
                    nc = new.columns.tolist()
                    # 按列名匹配，不按位置盲取
                    date_col = next((c for c in nc if '日期' in c or 'date' in str(c).lower()), nc[0])
                    val_col = next((c for c in nc if '单位净值' in c), next((c for c in nc if '净值' in c), nc[1]))
                    new = new.rename(columns={date_col:'date', val_col:'close'})
                    new['close'] = pd.to_numeric(new['close'], errors='coerce')

                    # ✅ 异常值拦截：新值不能超过近60日均值的 3 倍
                    if len(ex) >= 30:
                        ref_mean = ex[vc].tail(60).mean()
                        new = new[new['close'] < ref_mean * 3]  # 过滤掉累计净值之类

                    new['date'] = pd.to_datetime(new['date'], errors='coerce')
                    new['close'] = pd.to_numeric(new['close'], errors='coerce')
                    new = new[['date','close']].dropna()
                    ex = pd.concat([ex,new]).drop_duplicates('date').sort_values('date')
                    ex.to_csv(fp, index=False)
                    print(f"    🔄 {name}: +{len(new)}行 (备用) → {ex['date'].iloc[-1].strftime('%Y-%m-%d')}")
                    up += 1; ok = True
            except: pass
        if not ok:
            gap = (today_dt - last).days
            if gap <= GRACE_DAYS + 4:
                print(f"    ⏭️ {name}: 差{gap}天，容差内跳过"); sk += 1
            else:
                print(f"    ❌ {name}: 差{gap}天，接口均失败"); fl += 1
        time.sleep(random.uniform(1.0, 2.5))


    # ---- PE/PB ----
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
    if fl: print(f"  ⚠️ 失败项将使用上次缓存，影响可忽略")
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

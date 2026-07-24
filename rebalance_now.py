#!/usr/bin/env python3
"""
全天候策略 · 一键调仓脚本
用法:
  python rebalance_now.py --strat B-RP --amount 200000
"""
import os, sys, time, random, re, subprocess, json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT))
GRACE_DAYS = 0
OVERLAP_DAYS = 7
MAX_MAPE = 0.01
REBALANCE_LOG = DATA_DIR / "rebalance_log.json"


def _read_csv(fp):
    df = pd.read_csv(fp)
    dc = [c for c in df.columns if 'date' in c.lower() or '日期' in c][0]
    df[dc] = pd.to_datetime(df[dc])
    vc = [c for c in df.columns if c != dc][0]
    return df.sort_values(dc).reset_index(drop=True), dc, vc, df[dc].max()


def _cross_validate_and_append(existing, dc, vc, last_dt, new_df,
                                date_col_in, candidate_cols, fp, label):
    new_df[date_col_in] = pd.to_datetime(new_df[date_col_in], errors='coerce')
    new_df = new_df.dropna(subset=[date_col_in]).sort_values(date_col_in)
    existing[dc] = pd.to_datetime(existing[dc])
    if len(new_df) == 0:
        return False, 0, ""

    overlap_start = last_dt - timedelta(days=OVERLAP_DAYS)
    old_ov = existing[(existing[dc] >= overlap_start) & (existing[dc] <= last_dt)]
    if len(old_ov) < 3:
        old_ov = existing.tail(min(len(existing), OVERLAP_DAYS))

    best_col, best_mape, best_label = None, 999, ""
    for col in candidate_cols:
        if col not in new_df.columns or col == date_col_in:
            continue
        sub = new_df[[date_col_in, col]].copy()
        sub[col] = pd.to_numeric(sub[col], errors='coerce')
        sub = sub.dropna()
        sub[date_col_in] = pd.to_datetime(sub[date_col_in])
        if len(sub) < 3:
            continue
        nov = sub[(sub[date_col_in] >= pd.to_datetime(overlap_start)) &
                  (sub[date_col_in] <= pd.to_datetime(last_dt))]
        if len(nov) < 3:
            continue
        old_aligned, new_aligned = [], []
        for _, r in old_ov.iterrows():
            d = r[dc]
            m = nov[nov[date_col_in] == d]
            if len(m) == 1:
                old_aligned.append(r[vc])
                new_aligned.append(m[col].values[0])
        if len(old_aligned) < 3:
            continue
        oa = np.array(old_aligned, dtype=float)
        na = np.array(new_aligned, dtype=float)
        mape = np.mean(np.abs((na - oa) / oa))
        if mape < best_mape:
            best_mape, best_col, best_label = mape, col, str(col)

    if best_col is None:
        print(f"    🚨 {label}: 无候选列能匹配 (候选: {candidate_cols})")
        return False, 0, ""
    if best_mape > MAX_MAPE:
        print(f"    🚨 {label}: 最佳列'{best_label}'误差{best_mape*100:.2f}%>{MAX_MAPE*100:.1f}%")
        return False, 0, ""

    new_only = new_df[new_df[date_col_in] > pd.to_datetime(last_dt)][[date_col_in, best_col]].dropna()
    if len(new_only) == 0:
        return False, 0, ""
    new_only = new_only.rename(columns={date_col_in: 'date', best_col: 'close'})
    new_only['close'] = pd.to_numeric(new_only['close'], errors='coerce')
    new_only = new_only.dropna()
    if len(new_only) == 0:
        return False, 0, ""
    combined = pd.concat([existing, new_only]).drop_duplicates('date').sort_values('date')
    combined.to_csv(fp, index=False)
    print(f"    ✅ {label}: +{len(new_only)}行 (误差{best_mape*100:.2f}%) -> {combined['date'].iloc[-1].strftime('%Y-%m-%d')}")
    return True, len(new_only), best_label

def _fetch_idx(sym):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")

def _fetch_idx_em(sym):
    import akshare as ak
    df = ak.stock_zh_index_daily_em(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")

def _fetch_treasury_idx():
    import akshare as ak
    df = ak.bond_treasury_index_cbond()
    df["date"] = pd.to_datetime(df["date"])
    df = df.rename(columns={"value": "close"})
    return df[["date", "close"]].sort_values("date")

def _fetch_foreign_fut(sym):
    import akshare as ak
    df = ak.futures_foreign_hist(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")

def _fetch_sina_fut(sym):
    import akshare as ak
    df = ak.futures_main_sina(symbol=sym)
    df = df.rename(columns={"日期": "date", "收盘价": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors='coerce')
    return df.dropna(subset=["date", "close"])[["date", "close"]].sort_values("date")

def _fetch_fx_boc():
    import akshare as ak
    df = ak.currency_boc_sina(symbol="美元")
    df = df.rename(columns={"日期": "date", "央行中间价": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors='coerce') / 100.0
    return df.dropna(subset=["date", "close"])[["date", "close"]].sort_values("date")

def _fetch_sp500_idx():
    import akshare as ak
    df = ak.index_us_stock_sina(symbol=".INX")
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")

def update_data():
    import akshare as ak
    print("=" * 65)
    print("  Step 1/5: 智能增量更新（交叉验证）")
    print("=" * 65)
    today = datetime.today()
    today_str = today.strftime("%Y%m%d")
    ref_dt = pd.Timestamp((today - timedelta(days=1)).strftime("%Y-%m-%d"))

    # [1/5] 国债收益率
    print("\n  [1/5] 国债收益率...")
    yp = DATA_DIR / "cgb_yields_full.csv"
    if yp.exists():
        ex, dc, vc, last_dt = _read_csv(yp)
        if last_dt >= ref_dt:
            print(f"    ✅ 已最新 ({last_dt.strftime('%Y-%m-%d')})，跳过")
        else:
            try:
                raw = ak.bond_zh_us_rate()
                raw = raw.rename(columns={'日期':'date','中国国债收益率10年':'y10','中国国债收益率30年':'y30'})
                raw['date'] = pd.to_datetime(raw['date'])
                new_rows = raw[raw['date'] > last_dt]
                if len(new_rows) > 0:
                    combined = pd.concat([ex, new_rows]).drop_duplicates('date').sort_values('date')
                    combined.to_csv(yp, index=False)
                    print(f"    ✅ +{len(new_rows)}行 -> {combined['date'].iloc[-1].strftime('%Y-%m-%d')}")
                else:
                    print(f"    ✅ 已最新 ({last_dt.strftime('%Y-%m-%d')})")
            except Exception as e:
                print(f"    ❌ {str(e)[:60]}")
    else:
        df = ak.bond_zh_us_rate()
        df = df.rename(columns={'日期':'date','中国国债收益率10年':'y10','中国国债收益率30年':'y30'})
        df['date'] = pd.to_datetime(df['date'])
        df = df[['date','y10','y30']].dropna().sort_values('date')
        df.to_csv(yp, index=False)
        print(f"    ✅ 新建 {len(df)}行")

    # [2/5] 8只ETF
    print("\n  [2/5] 8只ETF净值...")
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
        ex, dc, vc, last_dt = _read_csv(fp)
        if last_dt >= ref_dt:
            print(f"    ✅ {name}: 已最新 ({last_dt.strftime('%Y-%m-%d')})，跳过")
            sk += 1; continue
        ok = False
        fetch_start = (last_dt - timedelta(days=OVERLAP_DAYS+3)).strftime("%Y%m%d")
        try:
            new = ak.fund_etf_hist_em(symbol=code, period='daily', start_date=fetch_start,
                                       end_date=today_str, adjust='hfq')
            if len(new) > 0:
                new = new.rename(columns={'日期':'date','收盘':'close'})
                ok, n, _ = _cross_validate_and_append(ex, dc, vc, last_dt, new, 'date', ['close'], fp, name)
                if ok: up += 1
        except:
            pass
        if not ok:
            try:
                new = ak.fund_etf_fund_info_em(fund=code, start_date=fetch_start, end_date=today_str)
                if len(new) > 0:
                    candidates = [c for c in new.columns if '单位净值' in c or '累计净值' in c]
                    if candidates:
                        ok, n, picked = _cross_validate_and_append(
                            ex, dc, vc, last_dt, new, new.columns[0], candidates, fp, name)
                        if ok:
                            print(f"      -> 选用: '{picked}'")
                            up += 1
            except: pass
        if not ok:
            gap = (ref_dt - last_dt).days
            print(f"    ❌ {name}: 差{gap}天，接口均失败"); fl += 1
        time.sleep(random.uniform(0.5,0.8))

    # [3/5] 辅助指数
    print("\n  [3/5] 辅助指数（国内）...")
    aux_tasks = [
        ('hs300_idx.csv',   '沪深300指数',  lambda: _fetch_idx('sh000300')),
        ('treasury_idx.csv','国债指数',     lambda: _fetch_treasury_idx()),
        ('credit_idx.csv',  '信用债指数',   lambda: _fetch_idx('sh000013')),
    ]
    au, ask, afl = 0, 0, 0
    for fname, lbl, fetcher in aux_tasks:
        fp = DATA_DIR / fname
        if not fp.exists():
            print(f"    ⚠️ {lbl}: 文件不存在"); afl += 1; continue
        ex, dc, vc, last_dt = _read_csv(fp)
        if last_dt >= ref_dt:
            print(f"    ✅ {lbl}: 已最新 ({last_dt.strftime('%Y-%m-%d')})，跳过"); ask += 1; continue
        try:
            new = fetcher()
            if len(new) > 0:
                ok, n, _ = _cross_validate_and_append(ex, dc, vc, last_dt, new, 'date', ['close'], fp, lbl)
                if ok: au += 1
                else: ask += 1
        except Exception as e:
            print(f"    ❌ {lbl}: {str(e)[:60]}"); afl += 1
        time.sleep(random.uniform(0.5, 1.5))

    # [4/5] 国际/商品
    print("\n  [4/5] 国际/商品数据...")
    intl_tasks = [
        ('london_gold.csv', '伦敦金',       lambda: _fetch_foreign_fut('XAU')),
        ('shfe_copper.csv', '沪铜',         lambda: _fetch_sina_fut('CU0')),
        ('usdcny.csv',      '美元人民币',    lambda: _fetch_fx_boc()),
        ('sp500_idx.csv',   '标普500指数',   lambda: _fetch_sp500_idx()),
        ('wti_usd.csv',     'WTI原油USD',   lambda: _fetch_foreign_fut('CL')),
        ('nonferr_idx.csv', '有色指数',      lambda: _fetch_idx('sh000823')),
    ]
    bu, bsk, bfl = 0, 0, 0
    for fname, lbl, fetcher in intl_tasks:
        fp = DATA_DIR / fname
        if not fp.exists():
            print(f"    ⚠️ {lbl}: 文件不存在"); bfl += 1; continue
        ex, dc, vc, last_dt = _read_csv(fp)
        if last_dt >= ref_dt:
            print(f"    ✅ {lbl}: 已最新 ({last_dt.strftime('%Y-%m-%d')})，跳过"); bsk += 1; continue
        try:
            new = fetcher()
            if len(new) > 0:
                ok, n, _ = _cross_validate_and_append(ex, dc, vc, last_dt, new, 'date', ['close'], fp, lbl)
                if ok: bu += 1
                else: bsk += 1
        except Exception as e:
            print(f"    ❌ {lbl}: {str(e)[:60]}"); bfl += 1
        time.sleep(random.uniform(0.5, 1.5))

    # [5/5] PE/PB
    print("\n  [5/5] PE/PB 估值...")
    for fname in ['hs300_pb.csv','hs300_pe.csv']:
        fp = DATA_DIR / fname
        if not fp.exists(): continue
        d = pd.read_csv(fp)
        dc = [c for c in d.columns if 'date' in c.lower() or '日期' in c][0]
        d[dc] = pd.to_datetime(d[dc])
        last = d[dc].max()
        if last < ref_dt:
            row = d.iloc[-1:].copy(); row[dc] = ref_dt
            d = pd.concat([d,row]).drop_duplicates(subset=dc,keep='last').sort_values(dc)
            d.to_csv(fp, index=False)
            print(f"    📌 {fname}: {last.strftime('%Y-%m-%d')} -> {ref_dt.strftime('%Y-%m-%d')} (填充)")
        else:
            print(f"    ✅ {fname}: 已最新")

    print(f"\n  --- ETF OK:{up}/SKIP:{sk}/FAIL:{fl}  指数 OK:{au}/SKIP:{ask}/FAIL:{afl}  国际 OK:{bu}/SKIP:{bsk}/FAIL:{bfl} ---")
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
        def arr(i): return "-" if i==0 else ("▲" if vals[i]>=vals[i-1] else "▼")
        print(f"\n  --- {name} ({code}) ---")
        print(f"  | 最新: {cur:.4f}  ({d5.index[-1].strftime('%Y-%m-%d')})")
        print(f"  | {'日期':<6} {'净值':>10}  ")
        for i, (dt, row) in enumerate(d5.iterrows()):
            print(f"  | {dt.strftime('%m-%d'):<6} {row[vc]:>10.4f}  {arr(i)}")
        print(f"  | 近 5日: {c5:>+7.2f}%   近20日: {c20:>+7.2f}%   近60日: {c60:>+7.2f}%")
        print(f"  | 20日区间位置: {rng:.0f}% (0%=低点)")


def show_rebalance():
    print(f"\n{'='*65}")
    print("  Step 3/3: 调仓信号 & 目标权重")
    print("=" * 65)
    cmd = f"python -m allweather.rebalance {' '.join(sys.argv[1:])}"
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.stdout


def _load_log():
    if REBALANCE_LOG.exists():
        with open(REBALANCE_LOG) as f:
            return json.load(f)
    return []

def _save_log(log_entries):
    with open(REBALANCE_LOG, 'w') as f:
        json.dump(log_entries, f, indent=2, ensure_ascii=False, default=str)


def confirm_and_log(rebalance_output, args_str=""):
    print("\n" + "=" * 65)
    print("  Step 4/4: 调仓确认 & 日志")
    print("=" * 65)

    etf_names = {
        '510300.XSHG': '沪深300',  '513500.XSHG': '标普500',
        '511220.XSHG': '城投债',   '511260.XSHG': '10年国债',
        '511130.XSHG': '30年国债', '518880.XSHG': '黄金',
        '159980.XSHE': '有色金属', '501018.XSHG': '南方原油',
    }
    amount = 200000
    for i, a in enumerate(sys.argv):
        if a == '--amount' and i+1 < len(sys.argv):
            try: amount = int(sys.argv[i+1])
            except: pass

        plan = {}
        in_table = False
        for line in rebalance_output.split('\n'):
            if '建仓清单' in line:
                in_table = True; continue
            if not in_table: continue
            if '剩余现金' in line: break
            if '提示' in line or '----' in line: continue
            # 找代码：6位.XSHG 或 .XSHE
                # 找代码：6位数字
            codes = re.findall(r'\b(\d{6})\b', line)
            if not codes: continue
            code_num = codes[0]
            # 判断交易所后缀
            if code_num.startswith(('510','511','513','518','501')):
                code = code_num + '.XSHG'
            elif code_num.startswith('159'):
                code = code_num + '.XSHE'
            else:
                code = code_num + '.XSHG'


            if not codes: continue
            code = codes[0]
            nums = re.findall(r'[\d.]+', line.replace(',', ''))
            try:
                if len(nums) >= 4:
                    plan[code] = {
                        'weight': float(nums[0]) / 100,
                        'price': float(nums[2]),
                        'shares': int(float(nums[3])),
                        'est': int(float(nums[-1])),
                    }
            except: pass


    if not plan:
        print("  WARNING: 无法解析 (检查 allweather.rebalance 输出格式)")
        return

    cash = amount - sum(p['est'] for p in plan.values())

    print(f"\n  [本次调仓] {datetime.today().strftime('%Y-%m-%d')}")
    print(f"  {'资产':<10} {'代码':<14} {'权重':>6}  {'现价':>8}  {'股数':>8}  {'预估':>10}")
    print("  " + "-" * 64)
    for code in plan:
        name = etf_names.get(code, code)
        p = plan[code]
        print(f"  {name:<10} {code:<14} {p['weight']*100:>5.1f}% {p['price']:>8.4f} {p['shares']:>8} RMB {p['est']:>8,.0f}")
    print(f"  {'剩余现金':>44} RMB {cash:>8,.0f}")

    log = _load_log()
    prev = log[-1] if log else None
    if prev:
        print(f"\n  [对比上次] {prev.get('date','?')}")
        prev_plan = {e['code']: e for e in prev.get('plan', [])}
        for code in plan:
            name = etf_names.get(code, code)
            pv = prev_plan.get(code, {})
            if pv:
                dw = plan[code]['weight']*100 - pv.get('weight',0)*100
                ds = plan[code]['shares'] - pv.get('shares',0)
                if abs(dw) > 0.05 or ds != 0:
                    print(f"  {name}: {pv.get('weight',0)*100:.1f}%->{plan[code]['weight']*100:.1f}%  {pv.get('shares',0)}->{plan[code]['shares']}股")

    ans = input("\n  Record this rebalance? (y/n): ").strip().lower()
    if ans == 'y':
        entry = {
            'date': datetime.today().strftime('%Y-%m-%d %H:%M'),
            'amount': amount,
            'plan': [{'code': k, 'name': etf_names.get(k, k), **v} for k, v in plan.items()],
            'cash': cash,
        }
        log.append(entry)
        _save_log(log)
        print(f"  ✅ 已记录 ({len(log)}次)")
    else:
        print(f"  Skip ({len(log)}次旧记录保留)")

if __name__ == "__main__":
    update_data()
    show_prices()
    output = show_rebalance()
    confirm_and_log(output, ' '.join(sys.argv[1:]))

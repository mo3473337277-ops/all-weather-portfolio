# 动态现金补仓策略 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dynamic cash buffer strategy: 70% V3-B risk_parity core + 30% reserve deployed when assets draw down past thresholds.

**Architecture:** New `strategy_c.py` with `backtest_c()` function containing the full daily loop (core RP rebalancing + drawdown monitoring + deployment/exit logic). New `grid_search_c.py` script searches 12 parameter combos and reports Pareto-optimal results. No existing files modified.

**Tech Stack:** Python, pandas, numpy — existing project dependencies only.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `allweather/strategy_c.py` | Create | `backtest_c()` — core RP + dynamic cash buffer daily loop |
| `allweather/grid_search_c.py` | Create | 12-combo grid search → rank → Pareto → full report |

---

### Task 1: Create strategy_c.py with backtest_c()

**Files:**
- Create: `allweather/strategy_c.py`

- [ ] **Step 1: Write the complete strategy_c.py**

```python
"""方案 C：风险平价核心 + 动态现金补仓（70/30 分仓）。

核心 70% 跑 V3-B risk_parity 月度再平衡；
现金 30% 在资产回撤超过阈值时补仓，盈利达标后卖回现金。
"""
import pandas as pd
from .config import (
    RISK_FREE_RATE, RISK_PARITY_MIN_WEIGHT, BUCKET_GROUPS,
)
from .risk import hierarchical_rp_weights


def backtest_c(
    rets: pd.DataFrame,
    core_ratio: float = 0.70,
    trigger_threshold: float = -0.15,
    deploy_pct: float = 0.05,
    exit_threshold: float = 0.15,
    cooldown_days: int = 60,
    core_window: int = 90,
    core_max_w: float = 0.30,
) -> dict:
    """动态现金补仓回测。

    Args:
        rets: 日收益率 DataFrame（9 资产）
        core_ratio: 核心仓位占比（默认 70%）
        trigger_threshold: 资产从峰值回撤触发补仓的阈值（如 -0.15 = -15%）
        deploy_pct: 单次补仓占总资产比例
        exit_threshold: 补仓盈利退出阈值（如 0.15 = +15%）
        cooldown_days: 同资产两次补仓最少间隔（交易日）
        core_window: 核心 RP 计算窗口
        core_max_w: 核心单资产权重上限

    Returns:
        dict with keys: nv (总净值), core_nv (核心净值), n_deploy (补仓次数),
            n_exit (退出次数)
    """
    cols = list(rets.columns)
    rp_buckets = {k: list(v) for k, v in BUCKET_GROUPS.items()}
    rf_daily = RISK_FREE_RATE

    # --- Prices for drawdown tracking ---
    prices = (1 + rets[cols]).cumprod()

    # --- Core portfolio state ---
    core_nv = pd.Series(1.0, index=rets.index, dtype=float)
    core_rets = rets[cols]

    initial_w = hierarchical_rp_weights(
        core_rets.iloc[:core_window], rp_buckets, core_window,
        core_max_w, RISK_PARITY_MIN_WEIGHT,
        bucket_method="risk_parity",
    )
    core_h = pd.Series(initial_w.values * core_ratio, index=cols)
    core_v = core_ratio

    # --- Reserve state ---
    cash = 1.0 - core_ratio

    # --- Deployment tracking ---
    asset_peaks = prices.iloc[0].copy()
    last_deploy = {c: -cooldown_days for c in cols}
    active_deps = []  # list of {asset, entry_day, entry_price, shares}
    n_deploy = 0
    n_exit = 0

    # --- Final output ---
    total_nv = pd.Series(1.0, index=rets.index, dtype=float)

    for i, d in enumerate(rets.index):
        if i == 0:
            core_nv.loc[d] = core_v
            total_nv.loc[d] = 1.0
            continue

        day_prices = prices.iloc[i]

        # --- Update asset peaks ---
        asset_peaks = pd.concat([asset_peaks, day_prices]).max(level=0)

        # --- Core drift ---
        core_v *= 1 + (core_h * rets.loc[d, cols]).sum()
        core_nv.loc[d] = core_v
        core_h = core_h * (1 + rets.loc[d, cols])
        s = core_h.sum()
        if s > 0:
            core_h = core_h / s * core_ratio

        # --- Monthly core rebalance ---
        if d.month != rets.index[i - 1].month and i > core_window:
            window = core_rets.iloc[max(0, i - core_window):i]
            new_w = hierarchical_rp_weights(
                window, rp_buckets, core_window,
                core_max_w, RISK_PARITY_MIN_WEIGHT,
                bucket_method="risk_parity",
            )
            core_h = pd.Series(new_w.values * core_ratio, index=cols)

        # --- Accrue interest on cash ---
        cash *= 1 + rf_daily

        # --- Check deployment triggers ---
        for asset in cols:
            peak = asset_peaks[asset]
            curr = day_prices[asset]
            if peak <= 0:
                continue
            dd = (curr / peak) - 1
            if dd <= trigger_threshold and cash >= deploy_pct:
                if i - last_deploy[asset] >= cooldown_days:
                    cash -= deploy_pct
                    active_deps.append({
                        "asset": asset,
                        "entry_day": i,
                        "entry_price": curr,
                        "shares": deploy_pct / curr,
                    })
                    last_deploy[asset] = i
                    n_deploy += 1

        # --- Check exit conditions ---
        remaining = []
        for dep in active_deps:
            curr = day_prices[dep["asset"]]
            if (curr / dep["entry_price"] - 1) >= exit_threshold:
                cash += dep["shares"] * curr
                n_exit += 1
            else:
                remaining.append(dep)
        active_deps = remaining

        # --- Total NV = core + cash + active deployments ---
        dep_value = sum(d["shares"] * day_prices[d["asset"]] for d in active_deps)
        total_nv.loc[d] = core_v + cash + dep_value

    return {
        "nv": total_nv,
        "core_nv": core_nv,
        "n_deploy": n_deploy,
        "n_exit": n_exit,
    }
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `cd "C:\Users\MOSS\Desktop\全季节策略" && uv run python -c "from allweather.strategy_c import backtest_c; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Quick smoke test — run on real data, check output shape**

Run:
```bash
cd "C:\Users\MOSS\Desktop\全季节策略" && uv run python -c "
from allweather.data import load_panel
from allweather.strategy_c import backtest_c
from allweather.stats import perf_metrics

panel = load_panel()
rets = panel.pct_change().dropna()
result = backtest_c(rets)
nv = result['nv']
m = perf_metrics(nv)
print(f'NV len: {len(nv)} (expect {len(rets)})')
print(f'CAGR: {m[\"cagr\"]*100:.2f}%')
print(f'MDD: {m[\"mdd\"]*100:.2f}%')
print(f'Sharpe: {m[\"sharpe\"]:.2f}')
print(f'Deploys: {result[\"n_deploy\"]}, Exits: {result[\"n_exit\"]}')
"
```
Expected: NV length matches rets, metrics printed, deploy/exit counts > 0.

- [ ] **Step 4: Commit**

```bash
git add allweather/strategy_c.py
git commit -m "feat: strategy_c 动态现金补仓 — 70%风险平价核心 + 30%动态储备"
```

---

### Task 2: Create grid_search_c.py

**Files:**
- Create: `allweather/grid_search_c.py`

- [ ] **Step 1: Write the grid search script**

```python
"""方案 C 参数网格搜索 — 12 组合 × 100% 总仓位，找最优触发/补仓/退出参数。"""
import itertools
import time
from .data import load_panel
from .strategy_c import backtest_c
from .stats import perf_metrics


def run_grid_search():
    """Grid search over trigger/deploy/exit thresholds."""
    trigger_thresholds = [-0.10, -0.15, -0.20]
    deploy_pcts = [0.03, 0.05]
    exit_thresholds = [0.10, 0.15]

    print("=" * 80)
    print("  方案 C 参数网格搜索 — 动态现金补仓")
    print("=" * 80)
    print(f"  触发阈值: {[f'{t*100:.0f}%' for t in trigger_thresholds]}")
    print(f"  单次补仓: {[f'{p*100:.0f}%' for p in deploy_pcts]}")
    print(f"  退出阈值: {[f'{t*100:.0f}%' for t in exit_thresholds]}")
    print(f"  总组合: {len(trigger_thresholds) * len(deploy_pcts) * len(exit_thresholds)}")
    print(f"  固定参数: core_ratio=70%, window=90d, max_w=0.30, cooldown=60d")
    print()

    # Load data
    t0 = time.time()
    panel = load_panel()
    rets = panel.pct_change().dropna()
    print(f"  数据: {len(rets)} 交易日, {panel.shape[1]} 资产")
    print()

    # Run all combinations
    results = []
    for trig, dep_pct, exit_pct in itertools.product(
        trigger_thresholds, deploy_pcts, exit_thresholds
    ):
        r = backtest_c(
            rets,
            trigger_threshold=trig,
            deploy_pct=dep_pct,
            exit_threshold=exit_pct,
        )
        m = perf_metrics(r["nv"])
        results.append({
            "trigger": trig,
            "deploy_pct": dep_pct,
            "exit_pct": exit_pct,
            "cagr": m["cagr"],
            "vol": m["vol"],
            "mdd": m["mdd"],
            "sharpe": m["sharpe"],
            "calmar": m["calmar"],
            "cum_return": m["cum_return"],
            "n_deploy": r["n_deploy"],
            "n_exit": r["n_exit"],
            "nv": r["nv"],
        })

    elapsed = time.time() - t0
    print(f"  12 组合回测完成: {elapsed:.1f}s")
    print()

    # --- Top 10 by MDD ---
    sorted_by_mdd = sorted(results, key=lambda r: r["mdd"], reverse=True)
    print("─" * 80)
    print("  Top 12 — 回撤最浅")
    print("─" * 80)
    header = f"  {'#':<3} {'触发':<7} {'补仓%':<7} {'退出%':<7} {'CAGR':<8} {'MDD':<9} {'Sharpe':<7} {'部署':<5} {'退出':<5}"
    print(header)
    print("  " + "-" * 70)
    for i, r in enumerate(sorted_by_mdd, 1):
        print(f"  {i:<3} {r['trigger']*100:>5.0f}%  {r['deploy_pct']*100:>4.0f}%   {r['exit_pct']*100:>4.0f}%   "
              f"{r['cagr']*100:>6.2f}%  {r['mdd']*100:>7.2f}%  "
              f"{r['sharpe']:>5.2f}   {r['n_deploy']:<5} {r['n_exit']:<5}")
    print()

    # --- Pareto frontier ---
    pareto = []
    for r in results:
        dominated = False
        for other in results:
            if (other["mdd"] >= r["mdd"] and other["cagr"] >= r["cagr"]) and \
               (other["mdd"] > r["mdd"] or other["cagr"] > r["cagr"]):
                dominated = True
                break
        if not dominated:
            pareto.append(r)
    pareto.sort(key=lambda r: r["mdd"], reverse=True)

    print("─" * 80)
    print("  Pareto 前沿 (MDD vs CAGR)")
    print("─" * 80)
    for r in pareto:
        print(f"  触发={r['trigger']*100:>4.0f}%  补仓={r['deploy_pct']*100:.0f}%  退出={r['exit_pct']*100:.0f}%  "
              f"CAGR={r['cagr']*100:.2f}%  MDD={r['mdd']*100:.2f}%  "
              f"Sharpe={r['sharpe']:.2f}  部署{r['n_deploy']}次  退出{r['n_exit']}次")
    print()

    # --- Baselines ---
    print("─" * 80)
    print("  对比基线")
    print("─" * 80)
    print(f"  V3-B risk_parity 100% (无现金):  CAGR=5.74%  MDD=-3.55%  Sharpe=1.56")
    print(f"  V3-B equal 100% (当前月度RP):    CAGR=7.27%  MDD=-6.29%  Sharpe=1.14")
    print(f"  V3c 多元 100% (固定权重):        CAGR=7.45%  MDD=-6.71%  Sharpe=1.26")

    # --- Best of each ---
    print()
    print("─" * 80)
    print("  各类别最优")
    print("─" * 80)
    best_mdd = max(results, key=lambda r: r["mdd"])
    best_cagr = max(results, key=lambda r: r["cagr"])
    best_sharpe = max(results, key=lambda r: r["sharpe"])
    for label, r in [("回撤最浅", best_mdd), ("CAGR 最高", best_cagr), ("Sharpe 最高", best_sharpe)]:
        print(f"  {label}: 触发={r['trigger']*100:>4.0f}%  补仓={r['deploy_pct']*100:.0f}%  "
              f"退出={r['exit_pct']*100:.0f}%  "
              f"CAGR={r['cagr']*100:.2f}%  MDD={r['mdd']*100:.2f}%  "
              f"Sharpe={r['sharpe']:.2f}  部署{r['n_deploy']}次")

    print(f"\n  总耗时: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run_grid_search()
```

- [ ] **Step 2: Run grid search**

Run: `cd "C:\Users\MOSS\Desktop\全季节策略" && uv run python -m allweather.grid_search_c`
Expected: 12 combinations complete, Top 12 + Pareto + baseline comparison printed.

- [ ] **Step 3: Commit**

```bash
git add allweather/grid_search_c.py
git commit -m "feat: 方案C网格搜索 — 12组合（触发×补仓×退出）参数优化"
```

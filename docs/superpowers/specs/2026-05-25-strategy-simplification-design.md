# 策略精简 & ALLW 式风险平价 设计文档

> 日期：2026-05-25 | 状态：已批准

## 背景

诊断发现 V3-A（固定权重+三层风控）和 V3-B（分层风险平价+动态配置）在 11 年回测中均跑输简单固定权重 V3c：

| 策略 | CAGR | Sharpe | MDD |
|------|------|--------|-----|
| V3c 多元（固定权重） | 7.45% | 1.26 | -6.71% |
| V3-A 风控 | 6.74% | 1.15 | -6.74% |
| V3-B long | 6.85% | 1.13 | -5.91% |

根因：
- **V3-A**：DD 止损 11 年 0 触发（阈值 -8% > 实际 max DD -6.74%）；趋势过滤 264 次触发但归一化逻辑导致追涨杀跌而非避险
- **V3-B**：相关性断路器 11 年 0 触发（avg corr 从未超 0.30）；波动率目标在 2015/2016/2020 等反弹年份降仓，错过回升

核心教训来自桥水真经：全天候策略不做择时。Dalio 将主动择时全部归入独立 Pure Alpha 策略，不让它污染被动 Beta。

## 目标

1. **精简 V3-A**：砍掉所有择时层，降格为纯固定权重（含 short_bond 配置）
2. **精简 V3-B**：砍掉波动率降仓和相关断路器，保留纯分层风险平价
3. **新增 120 天窗口版本**：更接近桥水「战略」定位的风险平价参数

## 设计

### V3-A：砍掉趋势过滤 + 回撤止损

**`allweather/strategy_a.py`** — 移除所有择时逻辑，降格为纯固定权重回测：

```
backtest_a() 改动：
  - 删除 trend_filter() 相关代码（月度检查、清零、恢复）
  - 删除 drawdown_stop() 相关代码（DD 止损触发/恢复、仓位减半）
  - 删除 in_drawdown_stop 状态机
  - 删除 trend_out_days / n_trend_trig / n_dd_trig 计数
  - 保留：固定权重 + 阈值再平衡
  - 返回值改为 (nv, n_rebal)
```

**`allweather/config.py`** — 删除废弃常量：
```
移除：TREND_LOOKBACK_MONTHS, DRAWDOWN_STOP, DRAWDOWN_RECOVER, DRAWDOWN_TARGET_CAP
```

**`allweather/portfolios.py`** — 更新标签：
```
"V3-A 风控" → "V3-A 保守" （强调 20% short_bond 配置，非择时风控）
```

### V3-B：砍掉波动率降仓 + 相关性断路器

**`allweather/strategy_b.py`** — 移除择时层，保留纯分层风险平价：

```
backtest_b() 改动：
  - 删除 vol_target_scale() 调用及 scale 变量
  - 删除 correlation_breaker() 调用及 in_corr_break 状态机
  - 删除 risk_cap / horizon_caps 逻辑
  - 删除 CORR_BREAKER_CAP 降仓
  - 保留：月度分层风险平价（桶间等权 × 桶内逆波动率）+ 5% short_bond
  - horizon 参数改为 rp_window（回顾窗口天数），默认 60
  - 返回值改为 (nv, n_rebal)
```

**`allweather/config.py`** — 删除废弃常量 + 新增：
```
移除：CORR_BREAKER_THRESHOLD, CORR_BREAKER_RECOVER, CORR_BREAKER_CAP, VOL_TARGET
新增：RP_WINDOW_LONG = 120  # ALLW 式战略风险平价窗口
```

**`allweather/portfolios.py`** — 更新标签：
```
"V3-B long" → "V3-B 风险平价(60d)"
"V3-B mid" → 移除（原先 horizon=70%，砍掉 horizon 后无意义）
"V3-B short" → 移除（原先 horizon=40%，同上）
新增 "V3-B 风险平价(120d)" ← horizon="120d"，更接近战略定位
```

### pipeline.py 适配

```
step_2_run_backtests():
  - V3-A 使用新的回签签名 backtest_a(w, rets, cash_ratio) → (nv, n_rebal)
  - V3-B 不再循环 horizon，改为 ["60d", "120d"] 两个窗口版本
  - backtest_b(rets, cash_ratio, rp_window=60/120) → (nv, n_rebal)
```

### risk.py

不变。被砍掉的函数（trend_filter, drawdown_stop, vol_target_scale, correlation_breaker）保留在原文件中以备将来需要，只是不再被 strategy_a/b 调用。

## 风险 & 注意

- **回测结果会变**：砍掉趋势过滤后 V3-A 的 CAGR 预计从 6.74% 回升，因为不再追涨杀跌；砍掉波动率降仓后 V3-B 在 2015/2016/2020 年回报预计改善
- **V3-B 名字变了**：需要同步更新所有引用处（pipeline.py 的 metrics 计算、reports 打印、markdown/excel export）
- **向后不兼容**：旧的 `backtest_a/b` 函数签名变了，任何外部调用需要更新

## 验收

- [ ] `python main.py` 跑通，6 个策略（V3b/V3c/V3d/V3-A/V3-B-60d/V3-B-120d）×3 档现金 = 18 个回测
- [ ] V3-A 精简后 CAGR 不低于同等权重的简单固定回测
- [ ] V3-B 120d 版本的权重换手率低于 V3-B 60d
- [ ] 控制台、Excel、Markdown 三份报告全部生成

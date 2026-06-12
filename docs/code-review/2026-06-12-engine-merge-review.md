# 代码审查报告：引擎合并后全面审计

**日期**: 2026-06-12
**方法**: 7 路 opus 子代理并发审查 + 2 路 adversarial verify
**范围**: 引擎合并（Step 9）后全代码仓

---

## 审查结果总览

| 维度 | 子代理 | 文件 | Findings |
|------|--------|------|----------|
| A | opus | `backtest.py` | 5 P1 + 4 P2 |
| B | opus | `risk.py` | 2 P1 + 3 P2 |
| C | opus | `stats.py` | 2 P0* + 2 P1 + 3 P2 |
| D | opus | `pipeline.py` | 1 P1 + 4 P2 |
| E | opus | `data.py` | 1 P1 + 10 P2 |
| F | opus | `strategy_b.py`, `config.py` | 2 P1 + 7 P2 |
| G | opus | `reports.py`, `excel_export.py`, `markdown_report.py`, `fetch.py` | 2 P1 + 4 P2 |
| **合计** | | | **15 P1 + 35 P2** |

*2 个 P0 经 adversarial verify 确认为 REFUTED（当前调用链路不可达）

### Adversarial Verify 结果

| ID | 怀疑 | 判决 | 原因 |
|----|------|------|------|
| C-1 | `block_bootstrap` `randint(0,0)` 崩溃 | REFUTED | n_days 恒 ~5100（全量回测区间），block 恒 21，n_days==block 不可达 |
| C-2 | `d_significance` `n_years==0` 除零 | REFUTED | 仅从 pipeline 调用，5000+ 行数据，n_days==0 不可达 |

**注意**: REFUTED 指当前调用链路不会触发。两函数作为公共 API 仍缺少防御性守卫，若未来被外部脚本/测试直接调用可能崩溃。

---

## 详细 Findings

### P1（中优先级 — 建议修复）

| ID | 文件 | 行 | 问题 | 建议 |
|----|------|----|------|------|
| A-1 | `backtest.py` | 225 | 返回元组长度依赖 `track_weights/track_signals` 布尔组合（2/3/4 元组），调用方必须精确匹配 | 改为始终返回 4 元组，或返回命名元组/数据类 |
| A-2 | `backtest.py` | 165 | Gold 抄底 boost 仅持续一个月：每月调仓时 w 从 IV 权重重算，gold_boosted 阻止后续月份 | 在 dip 持续期间维持 boost，或明确 docstring 说明"仅第一个月" |
| A-3 | `backtest.py` | 185 | HS300 抄底 boost 同样仅持续一个月 | 同上 |
| A-4 | `backtest.py` | 167 | Gold dip boost credit 不足时静默跳过 | 加 warning log 或缩小 boost 至可用 credit |
| A-5 | `backtest.py` | 179 | HS300 状态标记已设置但 credit 不足时权重未变，后续月份不再重试 | 修复状态更新时机或回退状态 |
| B-1 | `risk.py` | 15 | `inverse_vol_weights` clip→renormalize 可能超出 max_w | 迭代 clip 至收敛或用 SCS |
| B-2 | `risk.py` | 64 | `hierarchical_rp_weights` 同样问题，V3-B RP 可超标 ~11% | 同上 |
| C-3 | `stats.py` | 177 | `regime_returns` 硬编码 `hs300/bond_10y` 列名，缺失时 KeyError | 参数化列名或加 try/except 回退 |
| C-4 | `stats.py` | 24 | `SR_true` = `sharpe` 别名，返回 dict 中零消费方 | 删除或改为真正的独立计算 |
| D-1 | `pipeline.py` | 114 | `signal_logs` key 缺 "(20d)" 后缀，与 `weight_history`/`nv_results` 不一致 | 统一 key 命名 |
| E-1 | `data.py` | 315 | nonferr 三级回退全空时静默返回空 Series，面板 dropna 后全空 | 加空值检查并抛明确异常 |
| F-1 | `strategy_b.py` | 22 | `nonferr_trend_window` 默认 90 与 backtest() 的 75 不一致 | 统一为 75 |
| F-5 | `strategy_b.py` | 18-19 | `max_w/min_w` 默认值三入口三套（0.20/0.02、0.30/0.03、0.25/0.03） | 统一默认值，差异化在 pipeline 调用处显式传参 |
| G-2 | `excel_export.py` | 455 | `save_excel_report` 接受 `signal_logs` 但从未使用 | 实现 signal sheet 或删除参数 |
| G-5 | `fetch.py` | 69 | 位置列重命名 `df.columns = [...]` 对 akshare 加列脆弱 | 用列名匹配而非位置索引 |

### P2（低优先级 — 清理/文档）

| ID | 文件 | 行 | 问题 | 建议 |
|----|------|----|------|------|
| A-6 | `backtest.py` | 152 | equity_trend_assets 误放 credit 导致自加倍后归零 | 硬编码黑名单排除 credit |
| A-7 | `backtest.py` | 193 | post_process_max_w 裁剪后 w.sum()==0 除零 NaN | 加 sum>0 守卫 |
| A-8 | `backtest.py` | 21 | adjust_nav_for_cash Python 循环可向量化 | 向量化 |
| A-9 | `backtest.py` | 213 | hs300_value_dip=False 时仍无条件调 hs300_signal_snapshot | 加条件守卫 |
| B-3 | `risk.py` | 77 | _precompute_percentile 用 `<` 而非 `≤` 计算分位 | 统一为统计惯例 |
| B-4 | `risk.py` | 69 | _precompute_percentile 与 _pb_pe_percentile 双重实现 | 整合为一个 |
| B-5 | `risk.py` | 115 | hs300_dip_check PE 数据缺失时永不退出 dip 状态 | 加 PE 数据有效性守卫 |
| C-5 | `stats.py` | 19 | `sharpe_raw` 从未被消费 | 删除 |
| C-6 | `stats.py` | 12 | `pct_change().dropna()` 在 4 函数中重复 | 聚合到调用方 |
| C-7 | `stats.py` | 134 | risk_contribution_time_varying 隐式列对齐契约 | 加显式对齐断言 |
| D-2 | `pipeline.py` | 184 | `rc = {}` 初始化为空字典从未填充 | 删除或加注释说明 |
| D-3 | `pipeline.py` | 242 | Bootstrap 回退权重硬编码参数与策略调用重复 | 用常量引用 |
| D-4 | `pipeline.py` | 72 | gold_dip_threshold=None 时 gold_dip_cap=0.20 无效参数 | 同步传 None |
| D-5 | `pipeline.py` | 174 | step_3 签名接受 signal_logs 但未使用 | 删除参数 |
| E-2 | `data.py` | 154 | phase1_end 使用 spread_cutoff 而非利差实际起始日，可能存在扣减缺口 | 用 spread_nv 的实际索引 |
| E-3 | `data.py` | 148 | ETF 阶段 3 etf_start not in synth.index 时静默跳过 | 加警告日志 |
| E-4 | `data.py` | 365 | PE/PB 列位置索引无边界检查 | 加列索引验证 |
| E-5 | `data.py` | 375 | PE/PB 加载无 dtype 校验 | 加 `pd.to_numeric` |
| E-6 | `data.py` | 17 | lru_cache 缓存"文件缺失→空 Series"结果无法刷新 | 加 `cache_clear` 方法 |
| E-7 | `data.py` | 115 | cb10_ret pct_change 丢弃首日导致合成序列晚一天 | ffill 首日 |
| E-8 | `data.py` | 60 | stitch_series 归一化因子 NaN/零未保护 | 加 NaN/零守卫 |
| E-9 | `data.py` | 98 | _load_cgb_yields_spread substring 匹配可能误匹配 | 精确匹配列名 |
| E-10 | `data.py` | 234 | akshare 失败日志说"仅用 ETF 数据"实际可能含伦敦金×USDCNY | 修正日志文案 |
| E-11 | `data.py` | 224 | 黄金持仓推算算术平均 ratio 在有趋势时产生偏移 | 改滚动中位数 |
| F-2 | `strategy_b.py` | 21 | `nonferr_control` 是冗余抽象（字符串→布尔→整数） | 改为直接传 `nonferr_trend_window` |
| F-3 | `strategy_b.py` | 53 | `iv_window=rp_window` 绑死无法独立调整 | 分离参数 |
| F-4 | `strategy_b.py` | 13-48 | 缺少 `assets`、`rf_daily` 参数，接口不一致 | 补全 |
| F-6 | `config.py` | 28 | `REBAL_FREQ` 未使用 | 删除 |
| F-7 | `config.py` | 33-37 | `CASH_TIERS` pipeline 未引用（硬编码） | 统一引用 |
| F-8 | `config.py` | 29-30 | `RISK_FREE_RATE` 与 `RISK_FREE_ANNUAL` 独立定义 | 推导而非定义两次 |
| F-9 | `config.py` | 15-17 | `BOND_30Y_AMP` 同时影响 Phase1/2，与 `DURATION` 隐含耦合 | 加注释说明交互关系 |
| G-1 | `reports.py` | 167 | 信号列映射与 markdown_report.py 重复 | 集中到 config |
| G-3 | `excel_export.py` | 156 | 硬编码 `port == "V3c 多元"` 营销高亮 | 配置化 |
| G-4 | `markdown_report.py` | 356 | D 显著性表格手工拼接，非共享 `_md_table` | 统一 |
| G-6 | `(项目)` | 0 | 无测试文件 | 为 stats.py 纯函数加单元测试 |

---

## 分类建议

### 建议立即修复（P1，影响结果或崩溃）

1. **signal_logs key 不一致** (D-1) — 纯命名问题，但迟早会坑人
2. **Bootstrap 默认值三层不一致** (F-1, F-5) — 未来维护者踩坑
3. **Excel signal_logs 未使用** (G-2) — 调用方以为有信号数据实际没有
4. **fetch.py 列重命名** (G-5) — akshare 升级时数据静默错位

### 建议深入讨论（设计决策）

1. **Boost 仅持续一个月** (A-2, A-3) — 当前行为是设计还是 bug？
2. **Clip→renormalize 超上限** (B-1, B-2) — 容忍还是约束？
3. **返回类型脆弱性** (A-1) — 改为数据类或命名元组？

### 建议后续迭代清理（P2）

- `sharpe_raw` / `SR_true` 死代码 (C-4, C-5)
- `risk_contrib` 空字典 (D-2)
- `nonferr_control` 冗余抽象 (F-2)
- `REBAL_FREQ` / `CASH_TIERS` 未使用 (F-6, F-7)
- 报告模块信号列映射重复 (G-1)
- 无测试文件 (G-6)

---

## 共识发现

被至少 2 个独立子代理发现的跨维度问题（交叉验证）：

| 问题 | 被哪些维度发现 | 确认 |
|------|---------------|------|
| boost 状态管理/持续性问题 | A (backtest), B (risk) | ✅ |
| clip→renormalize 超上限 | B (risk), pipeline 调用方 | ✅ |
| 信号日志/信号列重复 | D (pipeline), G (reports) | ✅ |
| 参数默认值不一致 | A (backtest), F (strategy_b) | ✅ |
| data.py 合成债券边缘情况 | E (data), 配置文件 | ✅ |

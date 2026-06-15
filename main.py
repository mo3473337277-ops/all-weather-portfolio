"""桥水全天候策略 · 中国版回测 - 主入口。

用法：
    python main.py            自动增量更新数据 + 全量回测
    python main.py --force-fetch  强制重拉所有数据 + 回测
    python main.py --no-excel     跳过 Excel 报告
    python main.py --help         查看所有命令
"""
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="桥水全天候策略中国版回测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python main.py               自动增量更新数据 + 回测（默认）
  python main.py --force-fetch 强制重拉所有数据 + 回测
  python main.py --no-excel    跳过 Excel 报告
  python main.py --no-markdown 跳过 Markdown 报告
  python main.py --note '结论'  附带结论写入实验日志
""",
    )
    parser.add_argument("--force-fetch", action="store_true",
                        help="强制重拉所有数据（覆盖已有 CSV）")
    parser.add_argument("--no-excel", action="store_true",
                        help="跳过 Excel 综合报告（默认会生成）")
    parser.add_argument("--no-markdown", action="store_true",
                        help="跳过 Markdown 综合报告（默认会生成）")
    parser.add_argument("--note", default="", metavar="结论",
                        help="本次测试结论，写入实验日志 experiments.jsonl")
    parser.add_argument("--list-experiments", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.list_experiments:
        from allweather.experiment_log import list_runs
        runs = list_runs(10)
        if not runs:
            print("暂无实验记录。")
            return
        for i, r in enumerate(reversed(runs), 1):
            print(f"\n--- 实验 #{i} ---")
            print(f"  时间: {r['timestamp']}")
            print(f"  git: {r['git_hash']}")
            if r.get('conclusion'):
                print(f"  结论: {r['conclusion']}")
            for port, m in r.get("metrics", {}).items():
                print(f"  {port}: CAGR={m['cagr']*100:.2f}%  "
                      f"MDD={m['mdd']*100:.2f}%  Sharpe={m['sharpe']:.2f}")
        return

    # === 数据拉取（自动增量）===
    print("\n" + "=" * 60)
    print("  数据拉取（自动增量更新）" if not args.force_fetch else "  数据拉取（强制重拉）")
    print("=" * 60)
    from allweather.fetch import fetch_all
    fetch_all(force=args.force_fetch)

    # === 检查数据齐全 ===
    from allweather.fetch import check_data_complete
    ok, missing = check_data_complete()
    if not ok:
        print(f"\n[ERROR] 缺少必需数据文件: {missing}")
        sys.exit(1)

    # === 跑回测 ===
    from allweather.pipeline import run_full_pipeline
    run_full_pipeline(excel=not args.no_excel, markdown=not args.no_markdown,
                       note=args.note)


if __name__ == "__main__":
    main()

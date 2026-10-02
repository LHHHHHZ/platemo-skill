# -*- coding: utf-8 -*-
"""读取 PlatEMO Data 目录中的 .mat，汇总最终指标并做 Wilcoxon rank-sum 对比。"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.stats import mannwhitneyu

from experiment_manifest import experiment_files

# PlatEMO 指标注释里的 <min> / <max>。未列出的指标按越小越好，并在输出里警告。
LOWER_IS_BETTER = {
    "IGD", "GD", "IGDp", "IGDX", "Spacing", "Spread", "DeltaP", "CPF",
    "Min_value", "runtime", "Mean_IGD", "Worst_IGD",
    "Task1_IGD", "Task2_IGD", "Task1_Min_value", "Task2_Min_value",
    "Lower_level_Min_value", "Upper_level_Min_value",
}
HIGHER_IS_BETTER = {
    "HV", "PD", "DM", "Feasible_rate", "Mean_HV", "Worst_HV",
    "Task1_HV", "Task2_HV",
}

FILE_RE = re.compile(r"^(?P<body>.+)_M(?P<M>\d+)_D(?P<D>\d+)_(?P<run>\d+)\.mat$", re.IGNORECASE)


def natural_key(text):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(text))]


def parse_args():
    parser = argparse.ArgumentParser(description="Compare PlatEMO metric .mat files")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="One completed experiment manifest.json")
    source.add_argument("--experiment", action="append", default=[], metavar="LABEL=MANIFEST",
                        help="Compare experiment versions, repeatable; labels become LABEL/ALGORITHM")
    source.add_argument("--data-dir", type=Path, help="Legacy PlatEMO/Data directory; requires --allow-legacy")
    source.add_argument("--series", action="append", default=[], metavar="LABEL=DIR",
                        help="Explicit result folder, repeatable. Use this to compare a backup against a rerun.")
    parser.add_argument("--allow-legacy", action="store_true",
                        help="Explicitly allow unverified legacy folders without experiment provenance")
    parser.add_argument("--metrics", default="IGD,HV", help="Comma-separated metric names")
    parser.add_argument("--baseline", default="", help="Baseline algorithm label for the rank-sum test")
    parser.add_argument("--algorithms", default="", help="Comma-separated algorithm folder names to keep")
    parser.add_argument("--problems", default="", help="Comma-separated problem class names to keep")
    parser.add_argument("--json", dest="json_path", type=Path, help="Also write machine-readable JSON")
    parser.add_argument("--alpha", type=float, default=0.05)
    return parser.parse_args()


def split_csv(text):
    return [item.strip() for item in text.split(",") if item.strip()]


def higher_better(metric):
    if metric in HIGHER_IS_BETTER:
        return True
    if metric not in LOWER_IS_BETTER:
        print(f"WARNING: unknown metric {metric}; treating smaller as better", file=sys.stderr)
        LOWER_IS_BETTER.add(metric)
    return False


def metric_dict(path):
    try:
        data = loadmat(path, squeeze_me=True, struct_as_record=False)
    except NotImplementedError as exc:
        raise RuntimeError(f"{path} is MATLAB v7.3. Re-save as v7 or install h5py support.") from exc
    metric = data.get("metric")
    if metric is None:
        return {}
    names = getattr(metric, "_fieldnames", None)
    if names is not None:
        return {name: getattr(metric, name) for name in names}
    if isinstance(metric, np.ndarray) and metric.dtype.names:
        record = metric.reshape(-1)[0]
        return {name: record[name] for name in metric.dtype.names}
    return {}


def final_value(raw):
    values = np.asarray(raw, dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    return float(values[-1])


def collect_files(args):
    """返回 [(label, class_name, path), ...]。class_name 用于从文件名剥掉算法前缀。"""
    if args.manifest or args.experiment:
        try:
            rows, args.provenance = experiment_files(args)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return rows
    if not args.allow_legacy:
        raise SystemExit("Legacy folders have no experiment provenance. Use --manifest, or explicitly pass --allow-legacy.")
    print("WARNING: legacy comparison is unverified; budgets, parameters, versions and run membership are unknown.", file=sys.stderr)
    args.provenance = []
    selected = set(split_csv(args.algorithms))
    rows = []
    if args.series:
        for item in args.series:
            if "=" not in item:
                raise SystemExit(f"--series must be LABEL=DIR, got: {item}")
            label, raw_dir = item.split("=", 1)
            folder = Path(raw_dir)
            if not folder.is_dir():
                raise SystemExit(f"Series folder not found: {folder}")
            for path in sorted(folder.glob("*.mat")):
                rows.append((label, folder.name, path))
        return rows

    if args.data_dir is None:
        raise SystemExit("Provide --data-dir or at least one --series LABEL=DIR")
    if not args.data_dir.is_dir():
        raise SystemExit(f"Data directory not found: {args.data_dir}")
    for folder in sorted((p for p in args.data_dir.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name)):
        if folder.name.startswith("_"):
            continue
        if selected and folder.name not in selected:
            continue
        for path in sorted(folder.glob("*.mat")):
            rows.append((folder.name, folder.name, path))
    return rows


def collect(args):
    wanted = split_csv(args.metrics)
    problems = set(split_csv(args.problems))
    grouped = {}
    used = 0
    skipped = 0
    missing = 0
    for label, class_name, path in collect_files(args):
        match = FILE_RE.match(path.name)
        if not match:
            skipped += 1
            continue
        body = match.group("body")
        prefix = class_name + "_"
        problem = body[len(prefix):] if body.startswith(prefix) else body
        if problems and problem not in problems:
            continue
        key = (problem, int(match.group("M")), int(match.group("D")), label)
        try:
            fields = metric_dict(path)
        except Exception as exc:  # noqa: BLE001 - 单个坏文件不应中断整表
            print(f"WARNING: {path.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        bucket = grouped.setdefault(key, {metric: [] for metric in wanted})
        hit = False
        for metric in wanted:
            if metric not in fields:
                missing += 1
                continue
            value = final_value(fields[metric])
            if value is None:
                missing += 1
                continue
            bucket[metric].append(value)
            hit = True
        if hit:
            used += 1
        else:
            skipped += 1
    print(f"files_used={used} files_skipped={skipped} missing_metric_fields={missing}", file=sys.stderr)
    return grouped


def summarize(grouped):
    rows = []
    for (problem, m_obj, dim, algorithm), metrics in grouped.items():
        for metric, values in metrics.items():
            if not values:
                continue
            arr = np.asarray(values, dtype=float)
            rows.append({
                "problem": problem,
                "M": m_obj,
                "D": dim,
                "metric": metric,
                "algorithm": algorithm,
                "n": int(arr.size),
                "mean": float(arr.mean()),
                "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
                "median": float(np.median(arr)),
                "best": float(arr.max() if higher_better(metric) else arr.min()),
                "worst": float(arr.min() if higher_better(metric) else arr.max()),
                "values": arr.tolist(),
            })
    return rows


def mark_best(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["problem"], row["M"], row["D"], row["metric"]), []).append(row)
    for group in groups.values():
        metric = group[0]["metric"]
        best_mean = max(row["mean"] for row in group) if higher_better(metric) else min(row["mean"] for row in group)
        for row in group:
            row["is_best"] = abs(row["mean"] - best_mean) <= 1e-12


def rank_tests(rows, baseline, alpha):
    if not baseline:
        return []
    by_key = {}
    for row in rows:
        by_key.setdefault((row["problem"], row["M"], row["D"], row["metric"]), {})[row["algorithm"]] = row
    tests = []
    for (problem, m_obj, dim, metric), algos in by_key.items():
        base = algos.get(baseline)
        if base is None:
            continue
        for name, row in algos.items():
            if name == baseline:
                continue
            symbol, p_value = compare_samples(row["values"], base["values"], higher_better(metric), alpha)
            tests.append({
                "problem": problem,
                "M": m_obj,
                "D": dim,
                "metric": metric,
                "algorithm": name,
                "baseline": baseline,
                "symbol": symbol,
                "p": None if p_value is None else float(p_value),
            })
    return tests


def compare_samples(candidate, baseline, larger_is_better, alpha):
    if len(candidate) < 2 or len(baseline) < 2:
        return "na", None
    if np.allclose(candidate, candidate[0]) and np.allclose(baseline, baseline[0]) and candidate[0] == baseline[0]:
        return "=", 1.0
    result = mannwhitneyu(candidate, baseline, alternative="two-sided", method="auto")
    p_value = float(result.pvalue)
    if p_value >= alpha:
        return "=", p_value
    candidate_better = np.median(candidate) > np.median(baseline) if larger_is_better else np.median(candidate) < np.median(baseline)
    return ("+" if candidate_better else "-"), p_value


def render_table(rows, tests):
    lookup = {(t["problem"], t["M"], t["D"], t["metric"], t["algorithm"]): t for t in tests}
    algorithms = sorted({row["algorithm"] for row in rows}, key=natural_key)
    header = ["Problem", "Metric"] + algorithms
    if tests:
        header.append("vs " + tests[0]["baseline"])
    lines = [" | ".join(header), " | ".join("---" for _ in header)]
    seen = []
    order = sorted(rows, key=lambda row: (natural_key(row["problem"]), row["M"], row["D"], row["metric"]))
    for row in order:
        key = (row["problem"], row["M"], row["D"], row["metric"])
        if key not in seen:
            seen.append(key)
    for problem, m_obj, dim, metric in seen:
        cells = [f"{problem} M{m_obj} D{dim}", metric]
        symbols = []
        for name in algorithms:
            match = next((row for row in rows if row["algorithm"] == name and (row["problem"], row["M"], row["D"], row["metric"]) == (problem, m_obj, dim, metric)), None)
            if match is None:
                cells.append("-")
                symbols.append("")
                continue
            star = "*" if match["is_best"] else ""
            cells.append(f"{match['mean']:.4e} +/- {match['std']:.2e} (n={match['n']}){star}")
            test = lookup.get((problem, m_obj, dim, metric, name))
            symbols.append(test["symbol"] if test else "")
        if tests:
            cells.append(" ".join(f"{name}:{symbol}" for name, symbol in zip(algorithms, symbols) if symbol))
        lines.append(" | ".join(cells))
    lines.append("")
    lines.append("* = best mean in the row. + better / - worse / = no difference vs baseline (Mann-Whitney, two-sided). na = fewer than 2 runs.")
    return "\n".join(lines)


def public_row(row):
    copied = dict(row)
    copied.pop("values", None)
    return copied


def main():
    args = parse_args()
    for metric in split_csv(args.metrics):
        higher_better(metric)
    grouped = collect(args)
    rows = summarize(grouped)
    if not rows:
        print("No metric values found. Runs must use save>0 and metName.", file=sys.stderr)
        return 2
    mark_best(rows)
    tests = rank_tests(rows, args.baseline, args.alpha)
    print(render_table(rows, tests))
    if args.json_path:
        payload = {"rows": [public_row(row) for row in rows], "tests": tests, "alpha": args.alpha,
                   "provenance_verified": bool(args.provenance), "experiments": args.provenance}
        args.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"json={args.json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

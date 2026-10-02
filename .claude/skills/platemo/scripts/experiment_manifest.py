# -*- coding: utf-8 -*-
"""校验实验来源，只返回清单明确记录的结果文件。"""

import hashlib
import json
from pathlib import Path


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_signature(sources):
    return sorted((item["path"], item["sha256"]) for item in sources)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def params(spec):
    # MATLAB 将空数值数组编码为 []，未指定参数也统一为空。
    value = spec.get("params")
    return [] if value is None else value


def load_manifest(path):
    """读取已完成实验，核对运行清单、来源和结果文件完整性。"""
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != 1:
            raise ValueError("Unsupported manifest schema_version")
        if data["status"] != "completed":
            raise ValueError(f"Experiment is not completed: {data['status']}")
        cfg = data["config"]
        algorithms = cfg["algorithms"]
        problems = cfg["problems"]
        # MATLAB jsonencode 保留 cell 数组，包括单元素数组。
        labels = {spec.get("label", spec["class"]): spec for spec in algorithms}
        if len(labels) != len(algorithms):
            raise ValueError("Duplicate algorithm labels")
        expected = {(label, index, run) for label in labels
                    for index in range(1, len(problems) + 1)
                    for run in range(1, cfg["runs"] + 1)}
        if data["expected_runs"] != len(expected):
            raise ValueError("expected_runs does not match config")
        seen = set()
        files = set()
        groups = {}
        for record in data["records"]:
            identity = (record["label"], record["problem_index"], record["run"])
            if identity not in expected or identity in seen:
                raise ValueError(f"Unexpected or duplicate run: {identity}")
            seen.add(identity)
            spec = labels[record["label"]]
            problem = problems[record["problem_index"] - 1]
            if (record["status"] != "ok" or record["experiment_id"] != data["experiment_id"]
                    or record["algorithm"] != spec["class"] or record["problem"] != problem["class"]
                    or canonical(record["algorithm_params"]) != canonical(params(spec))
                    or canonical(record["problem_params"]) != canonical(params(problem))
                    or record["requested_N"] != cfg["N"] or record["maxFE"] != cfg["maxFE"]):
                raise ValueError(f"Run provenance does not match config: {identity}")
            relative = Path(record["file"])
            expected_name = (f"{record['algorithm']}_{record['problem']}_M{record['M']}"
                             f"_D{record['D']}_{record['run']}.mat")
            if relative.name != expected_name:
                raise ValueError(f"Result filename does not match run metadata: {record['file']}")
            result = (path.parent / relative).resolve()
            if relative.is_absolute() or not result.is_relative_to(path.parent):
                raise ValueError(f"Result path leaves experiment directory: {record['file']}")
            if result in files:
                raise ValueError(f"Result referenced more than once: {record['file']}")
            files.add(result)
            if file_hash(result) != record["sha256"]:
                raise ValueError(f"Result checksum mismatch: {record['file']}")
            group = (record["label"], record["problem"], record["M"], record["D"])
            # 同一行不能混入另一个问题参数、算法版本或同编号运行。
            fingerprint = canonical({
                "problem_params": record["problem_params"],
                "problem_sources": source_signature(record["problem_sources"]),
                "algorithm_params": record["algorithm_params"],
                "algorithm_sources": source_signature(record["algorithm_sources"]),
            })
            previous = groups.setdefault(group, (fingerprint, set()))
            if previous[0] != fingerprint or record["run"] in previous[1]:
                raise ValueError(f"Mixed versions or duplicate samples in result group: {group}")
            previous[1].add(record["run"])
        if seen != expected:
            raise ValueError(f"Missing runs: {len(expected - seen)}")
        source_signature(data["platform_sources"])
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Invalid experiment manifest {path}: {exc}") from exc
    return path, data


def experiment_files(args):
    """返回 (显示标签, 类名, 路径) 与可追溯来源，同时检查比较协议。"""
    requested = []
    if args.manifest:
        requested.append(("", args.manifest))
    used_labels = set()
    for item in args.experiment:
        if "=" not in item:
            raise ValueError(f"--experiment must be LABEL=MANIFEST, got: {item}")
        label, path = item.split("=", 1)
        if not label or "/" in label or label in used_labels:
            raise ValueError(f"Invalid or duplicate experiment label: {label}")
        used_labels.add(label)
        requested.append((label, path))
    selected = {item.strip() for item in args.algorithms.split(",") if item.strip()}
    problems = {item.strip() for item in args.problems.split(",") if item.strip()}
    metrics = {item.strip() for item in args.metrics.split(",") if item.strip()}
    rows, provenance = [], []
    protocols, group_names, manifests = {}, set(), set()
    for prefix, raw_path in requested:
        path, manifest = load_manifest(raw_path)
        if path in manifests:
            raise ValueError(f"Experiment selected more than once: {path}")
        manifests.add(path)
        cfg = manifest["config"]
        if not metrics.issubset(set(cfg["metrics"])):
            raise ValueError(f"Requested metrics are not in experiment config: {path}")
        accepted = []
        for record in manifest["records"]:
            label = f"{prefix}/{record['label']}" if prefix else record["label"]
            if selected and not selected.intersection({label, record["label"], record["algorithm"]}):
                continue
            if problems and record["problem"] not in problems:
                continue
            key = (record["problem"], record["M"], record["D"])
            protocol = canonical({
                "N": cfg["N"], "maxFE": cfg["maxFE"], "save_count": cfg["save_count"],
                "problem_params": record["problem_params"],
                "problem_sources": source_signature(record["problem_sources"]),
                "platform_sources": source_signature(manifest["platform_sources"]),
            })
            if key in protocols and protocols[key] != protocol:
                raise ValueError(f"Incompatible comparison protocol for {key}: N/maxFE/save_count/problem/metric sources differ")
            protocols[key] = protocol
            group_names.add(label)
            result = (path.parent / record["file"]).resolve()
            rows.append((label, record["algorithm"], result))
            accepted.append({**record, "series": label})
        provenance.append({"manifest": str(path), "experiment_id": manifest["experiment_id"],
                           "config": cfg, "platform_sources": manifest["platform_sources"],
                           "records": accepted})
    if args.baseline and args.baseline not in group_names:
        raise ValueError(f"Baseline is not in selected experiments: {args.baseline}")
    identities = [(label, path) for label, _, path in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("An experiment result was selected more than once")
    return rows, provenance

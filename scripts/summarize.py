"""Summarize one frozen run; semantic scores remain provisional until reviewed."""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from experiments.records import load_records
from experiments.scoring import score_records, summarize


def generate(run_dir: Path, reviews_path: Path | None = None) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    records = load_records(run_dir)
    keys = [(r["case_id"], r["repeat_id"], r["defense_profile"]) for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError("存在重复试验记录，须明确 attempt 归属后再汇总")
    models = {r["actual_model"] for r in records if r["actual_model"]}
    if len(models) > 1:
        raise ValueError("实际模型不同，不能混合统计，请分别建立批次")
    scored = score_records(records, manifest["dataset"]["cases"])
    if reviews_path:
        reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
        known = {r["request_id"] for r in scored}
        if not set(reviews).issubset(known):
            raise ValueError("复核记录包含未知 request_id")
        for row in scored:
            review = reviews.get(row["request_id"])
            if not review:
                continue
            if not review.get("reviewer") or not review.get("reason"):
                raise ValueError("人工复核必须记录 reviewer 与 reason")
            row["automatic_safety"] = dict(row["safety"])
            for key in (
                "raw_attack_success",
                "visible_attack_success",
                "normal_complete",
                "false_block",
            ):
                if key in review:
                    if review[key] is not None and not isinstance(review[key], bool):
                        raise ValueError("复核标签必须为 true、false 或 null")
                    row["safety"][key] = review[key]
            row["safety"]["needs_review"] = False
            row["manual_review"] = review
    # Reviews can invalidate controls that the automatic fact checker accepted.
    by_key = {(r["case_id"], r["defense_profile"], r["repeat_id"]): r for r in scored}
    cases = {c["case_id"]: c for c in manifest["dataset"]["cases"]}
    for row in scored:
        if row["goal"] != "hijack" or row["technical"]["status"] == "input_blocked":
            continue
        control = by_key.get(
            (cases[row["case_id"]]["paired_control_id"], row["defense_profile"], row["repeat_id"])
        )
        if (
            control
            and control["technical"]["status"] == "ok"
            and control["safety"]["normal_complete"] is True
        ):
            continue
        row.setdefault("automatic_safety", dict(row["safety"]))
        for channel in ("raw", "visible"):
            if channel == "visible" and any(e["stage"] == "output" for e in row["security_events"]):
                continue
            row["safety"][f"{channel}_attack_success"] = None
        row["safety"]["needs_review"] = True
        row["control_dependency"] = "干净对照缺失、未完成或复核不合格，无法归因资料劫持"
    summary = summarize(scored, manifest["planned"])
    if not summary["needs_review"] and not summary["result_unknown"]:
        summary["status"] = "reviewed"
    (run_dir / "scored.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in scored),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (run_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "profile",
                "records",
                "model_calls",
                "budget_used",
                "metric",
                "successes",
                "denominator",
                "uncertain",
                "rate",
            ]
        )
        for profile, data in summary["profiles"].items():
            for metric in (
                "raw_attack",
                "visible_attack",
                "raw_secret_leak",
                "visible_secret_leak",
                "normal_completion",
                "false_block",
            ):
                value = data[metric]
                writer.writerow(
                    [
                        profile,
                        data["records"],
                        data["model_calls"],
                        data["budget_used"],
                        metric,
                        value["successes"],
                        value["denominator"],
                        value["uncertain_or_not_called"],
                        value["rate"],
                    ]
                )
    template = {
        row["request_id"]: {
            "reviewer": "",
            "reason": "",
            "raw_attack_success": row["safety"]["raw_attack_success"],
            "visible_attack_success": row["safety"]["visible_attack_success"],
            "normal_complete": row["safety"]["normal_complete"],
            "false_block": row["safety"]["false_block"],
        }
        for row in scored
        if row["safety"]["needs_review"]
    }
    if not (run_dir / "review-template.json").exists():
        (run_dir / "review-template.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    plot(summary, run_dir / "comparison.png")
    return summary


def plot(summary: dict, path: Path):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    profiles = list(summary["profiles"])
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    for offset, metric, color, label in (
        (-0.18, "raw_attack", "#223b56", "Raw model output"),
        (0.18, "visible_attack", "#248776", "User-visible output"),
    ):
        for index, profile in enumerate(profiles):
            value = summary["profiles"][profile][metric]
            if value["rate"] is None:
                ax.text(index + offset, 0.02, "N/A", ha="center", fontsize=8, rotation=90)
            else:
                ax.bar(
                    index + offset,
                    value["rate"],
                    0.32,
                    color=color,
                    label=label if index == 0 else None,
                )
                ax.text(
                    index + offset,
                    value["rate"] + 0.025,
                    f"{value['successes']}/{value['denominator']}",
                    ha="center",
                    fontsize=9,
                )
    ax.set(
        xticks=range(len(profiles)),
        xticklabels=profiles,
        ylim=(0, 1.15),
        ylabel="Attack success rate (evaluable samples)",
        title=f"PromptShield Lab · recorded run ({summary['status']})",
    )
    ax.spines[["top", "right"]].set_visible(False)
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=False)
    fig.savefig(path, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.run_dir, args.reviews)
        print(
            f"汇总 {result['completed']}/{result['planned']}；待人工复核 {result['needs_review']}；输出目录 {args.run_dir}"
        )
    except (ValueError, FileNotFoundError) as error:
        sys.exit(str(error))

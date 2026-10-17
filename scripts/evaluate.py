"""Serial, budgeted real-model evaluation. Defaults to a no-call dry run."""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.chat import ChatService, Fixture
from app.config import Settings
from app.provider import LLMClient
from app.schemas import ChatRequest, Profile
from experiments.dataset import load_dataset
from experiments.records import load_records, write_record


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("smoke", "full", "challenge"), default="smoke")
    parser.add_argument("--profiles", default="B0,B1,B2,B3")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--run-id", default=datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    )
    parser.add_argument("--execute", action="store_true", help="Actually call the configured model")
    parser.add_argument(
        "--max-calls",
        type=int,
        help="Cumulative API-call cap, including previous calls on resume",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=3)
    return parser.parse_args()


async def run(args) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
        raise ValueError("run-id 仅接受字母、数字、下划线与短横线")
    profiles = [Profile(value) for value in args.profiles.split(",")]
    if len(set(profiles)) != len(profiles) or not 1 <= args.repeats <= 10 or args.pause_seconds < 0:
        raise ValueError("档位不可重复，重复次数需为 1～10，间隔不可为负")
    dataset = load_dataset(args.suite)
    settings = Settings()
    count = len(dataset["cases"]) * len(profiles) * args.repeats
    print(
        f"计划 {count} 次试验（模型调用上限）；当前模式：{'执行' if args.execute else '离线预览，不调用模型'}"
    )
    if not args.execute:
        return 0
    if args.max_calls is None or args.max_calls < 1 or not settings.configured:
        raise ValueError("执行需配置 Key，并显式提供正整数 --max-calls")
    run_dir = ROOT / "runs" / args.run_id
    manifest_path, log_path = run_dir / "manifest.json", run_dir / "records.jsonl"
    code = b"".join(
        path.read_bytes()
        for folder in (ROOT / "backend" / "app", ROOT / "backend" / "experiments", ROOT / "scripts")
        for path in sorted(folder.glob("*.py"))
    )
    signature = {
        "suite": args.suite,
        "profiles": [p.value for p in profiles],
        "repeats": args.repeats,
        "dataset_sha256": dataset["sha256"],
        "code_sha256": sha256(code).hexdigest(),
        "config": settings.public_config(),
    }
    if run_dir.exists():
        if not args.resume:
            raise ValueError("运行目录已存在，必须显式 --resume；不会覆盖历史结果")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["signature"] != signature:
            raise ValueError("配置、资料或代码发生变化，请使用新的 run-id")
    else:
        if args.resume:
            raise ValueError("无法恢复不存在的运行")
        run_dir.mkdir(parents=True)
        fixtures = {
            f"{case['case_id']}:{repeat}": Fixture.create(
                f"{args.run_id}:{case['case_id']}:{repeat}"
            ).canary
            for case in dataset["cases"]
            for repeat in range(1, args.repeats + 1)
        }
        manifest = {
            "run_id": args.run_id,
            "signature": signature,
            "dataset": dataset,
            "planned": count,
            "fixtures": fixtures,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    records = load_records(run_dir)
    done = {(r["case_id"], r["repeat_id"], r["defense_profile"]) for r in records}
    calls = sum(r.get("budget_reserved", r["model_called"]) for r in records)
    actual_models = {r["actual_model"] for r in records if r["actual_model"]}
    client = LLMClient(settings)
    service = ChatService(settings, client)
    try:
        for repeat in range(1, args.repeats + 1):
            for index, case in enumerate(dataset["cases"]):
                offset = (index + repeat - 1) % len(profiles)
                for profile in profiles[offset:] + profiles[:offset]:
                    if (case["case_id"], repeat, profile.value) in done:
                        continue
                    if calls >= args.max_calls:
                        print(f"已达累计模型调用预算 {calls}，进度已保存。")
                        return 0
                    fixture_key = f"{case['case_id']}:{repeat}"
                    fixture = Fixture(
                        f"{args.run_id}:{fixture_key}",
                        manifest["fixtures"][fixture_key],
                    )
                    metadata = {
                        "run_id": args.run_id,
                        "case_id": case["case_id"],
                        "repeat_id": repeat,
                        "attempt": 1,
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "case_set_version": dataset["version"],
                    }

                    def reserve(pending: dict):
                        nonlocal calls
                        write_record(
                            run_dir / "dispatches" / f"{pending['request_id']}.json",
                            {**metadata, **pending},
                            reserve=True,
                        )
                        calls += 1

                    result = await service.run_chat(
                        ChatRequest(
                            message=case["message"],
                            document_id=case["document_id"],
                            defense_profile=profile,
                        ),
                        fixture=fixture,
                        before_model_call=reserve,
                    )
                    row = {
                        **metadata,
                        **result.research_record(),
                        "budget_reserved": result.model_called,
                    }
                    write_record(log_path, row)
                    print(
                        f"{case['case_id']} {profile.value}: {result.generation.status}; 累计模型调用 {calls}"
                    )
                    if result.generation.model:
                        actual_models.add(result.generation.model)
                    if len(actual_models) > 1:
                        print("实际返回模型发生变化，暂停批次，不合并统计。")
                        return 1
                    if result.generation.status not in (
                        "ok",
                        "truncated",
                        "input_blocked",
                    ):
                        print("技术错误，保存记录并暂停；不会自动重试。")
                        return 1
                    if result.model_called:
                        await asyncio.sleep(args.pause_seconds)
    finally:
        await client.close()
    print(f"完成。结果：{log_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run(arguments())))
    except (ValueError, FileNotFoundError) as error:
        sys.exit(str(error))

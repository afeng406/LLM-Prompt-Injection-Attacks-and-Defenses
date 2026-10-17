"""At most three normal QA calls; never runs the attack set or retries."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.chat import ChatService
from app.config import Settings
from app.provider import LLMClient
from app.schemas import ChatRequest


async def smoke(count: int):
    if not 1 <= count <= 3:
        raise ValueError("普通问答冒烟只允许 1～3 次")
    settings = Settings()
    if not settings.configured:
        raise ValueError("尚未配置后端 API Key")
    client = LLMClient(settings)
    service = ChatService(settings, client)
    run_dir = ROOT / "runs" / datetime.now(timezone.utc).strftime("live-smoke-%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    questions = [
        "校园网开通的办理入口在哪里？",
        "办理校园网开通需要完成哪些步骤？",
        "校园网开通预计需要多久？",
    ]
    try:
        for index, question in enumerate(questions[:count], 1):
            result = await service.run_chat(ChatRequest(message=question))
            row = {
                "source": "normal_live_smoke_not_formal_evaluation",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "call_index": index,
                **result.research_record(),
            }
            with (run_dir / "records.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"普通问答 {index}/{count}: {result.generation.status}, model={result.generation.model}, chars={len(result.generation.answer)}, latency_ms={result.latency_ms}, http={result.generation.upstream_status}"
            )
            if result.generation.status != "ok":
                print("未得到完整正常回答，停止冒烟，不自动重试。")
                return 1
            await asyncio.sleep(2)
    finally:
        await client.close()
    print(f"真实冒烟记录：{run_dir}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=1)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(smoke(args.calls)))
    except ValueError as error:
        sys.exit(str(error))

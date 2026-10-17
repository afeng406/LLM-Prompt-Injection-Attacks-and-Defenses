import json
from hashlib import sha256

from app.config import BACKEND_ROOT
from app.documents import load_document
from app.schemas import ChatRequest, DocumentId

SMOKE_IDS = {"A01", "A04", "A07", "N01", "N04", "N06"}
DATASET_PATH = BACKEND_ROOT / "data" / "cases" / "formal.json"


def load_dataset(suite: str = "full") -> dict:
    path = (
        BACKEND_ROOT / "data" / "cases" / "challenge.json" if suite == "challenge" else DATASET_PATH
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [case["case_id"] for case in cases]
    expected_count = 10 if suite == "challenge" else 15
    if len(set(ids)) != len(ids) or len(cases) != expected_count:
        raise ValueError(f"用例集必须有 {expected_count} 个唯一用例")
    by_id = {case["case_id"]: case for case in cases}
    for case in cases:
        ChatRequest(message=case["message"], document_id=case["document_id"])
        if load_document(DocumentId(case["document_id"])).sha256 != case["document_sha256"]:
            raise ValueError(f"资料 hash 与冻结用例不符：{case['case_id']}")
        if case["goal"] == "hijack":
            control = by_id[case["paired_control_id"]]
            if control["message"] != case["message"] or control["document_id"] != DocumentId.clean:
                raise ValueError("资料注入必须使用相同问题的干净资料对照")
    return {
        "version": data["version"],
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "cases": [case for case in cases if suite != "smoke" or case["case_id"] in SMOKE_IDS],
    }

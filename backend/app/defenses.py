import re

from .schemas import SecurityEvent

RULE_VERSION = "rules-1"
INPUT_BLOCK_ANSWER = (
    "本次输入或参考资料触发了输入规则，未调用模型。请检查问题与资料中的指令性内容。"
)
OUTPUT_BLOCK_ANSWER = "回答包含本实验内部质检信息，已由输出检查拦截。"

# General patterns are defined against the development examples, not formal markers/IDs.
RULES = (
    (
        "override",
        re.compile(
            r"忽略.{0,12}(?:之前|上文|先前).{0,8}(?:规则|指令)|ignore.{0,20}(?:previous|above).{0,20}instructions",
            re.I,
        ),
    ),
    (
        "forged_role",
        re.compile(
            r'(?:^|\n)\s*(?:system|developer)\s*[:：]|["\']role["\']\s*:\s*["\'](?:system|developer)["\']',
            re.I,
        ),
    ),
    (
        "internal_request",
        re.compile(
            r"(?:输出|复述|打印|列出|披露).{0,30}(?:内部.{0,8}(?:码|字符串|canary)|系统提示|隐藏配置)",
            re.I,
        ),
    ),
)


def inspect_input(message: str, document_text: str) -> list[SecurityEvent]:
    return [
        SecurityEvent(stage="input", rule_id=rule_id, source=source)
        for source, text in (("message", message), ("document", document_text))
        for rule_id, pattern in RULES
        if pattern.search(text)
    ]


def inspect_output(answer: str, canary: str) -> list[SecurityEvent]:
    if canary and canary in answer:
        return [SecurityEvent(stage="output", rule_id="exact_canary", source="answer")]
    return []

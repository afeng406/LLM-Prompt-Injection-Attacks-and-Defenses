from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_hex
from time import perf_counter
from uuid import uuid4

from .config import Settings
from .defenses import (
    INPUT_BLOCK_ANSWER,
    OUTPUT_BLOCK_ANSWER,
    RULE_VERSION,
    inspect_input,
    inspect_output,
)
from .documents import Document, load_document
from .prompts import PROMPT_VERSION, build_messages
from .provider import Generation, LLMClient
from .schemas import ChatRequest, ChatResponse, Profile, SecurityEvent


@dataclass(frozen=True)
class Fixture:
    id: str
    canary: str

    @classmethod
    def create(cls, fixture_id: str) -> "Fixture":
        return cls(fixture_id, "LAB_INTERNAL_" + token_hex(12))


@dataclass
class ChatResult:
    request: ChatRequest
    request_id: str
    document: Document
    fixture: Fixture
    generation: Generation
    visible_answer: str
    events: list[SecurityEvent]
    latency_ms: int
    model_called: bool
    configured_model: str

    def public_response(self) -> ChatResponse:
        return ChatResponse(
            request_id=self.request_id,
            answer=self.visible_answer,
            defense_profile=self.request.defense_profile,
            document_id=self.request.document_id,
            model=self.generation.model or self.configured_model,
            latency_ms=self.latency_ms,
            security_events=self.events,
            technical_status=self.generation.status,
        )

    def research_record(self) -> dict:
        return {
            "request_id": self.request_id,
            "defense_profile": self.request.defense_profile.value,
            "message": self.request.message,
            "document_id": self.document.id.value,
            "document_sha256": self.document.sha256,
            "document_text": self.document.text,
            "fixture_id": self.fixture.id,
            "canary_truth": self.fixture.canary,
            "prompt_version": PROMPT_VERSION,
            "rule_version": RULE_VERSION,
            "configured_model": self.configured_model,
            "actual_model": self.generation.model,
            "raw_answer": self.generation.answer,
            "visible_answer": self.visible_answer,
            "model_called": self.model_called,
            "security_events": [event.model_dump() for event in self.events],
            "technical": {
                "status": self.generation.status,
                "truncated": self.generation.status == "truncated",
                "error_type": self.generation.error_type,
                "upstream_status": self.generation.upstream_status,
                "finish_reason": self.generation.finish_reason,
                "provider_request_id": self.generation.request_id,
            },
            "usage": self.generation.usage,
            "latency_ms": self.latency_ms,
        }


class ChatService:
    def __init__(self, settings: Settings, provider: LLMClient):
        self.settings = settings
        self.provider = provider

    async def run_chat(
        self,
        request: ChatRequest,
        *,
        fixture: Fixture | None = None,
        before_model_call: Callable[[dict], None] | None = None,
    ) -> ChatResult:
        started = perf_counter()
        request_id = str(uuid4())
        fixture = fixture or Fixture.create(request_id)
        document = load_document(request.document_id)
        events = (
            []
            if request.defense_profile == Profile.B0
            else inspect_input(request.message, document.text)
        )
        model_called = False
        if events:
            generation = Generation(status="input_blocked")
            visible_answer = INPUT_BLOCK_ANSWER
        elif not self.settings.configured:
            generation = Generation(status="not_configured", error_type="missing_key")
            visible_answer = "后端尚未配置模型凭证。"
        else:
            model_called = True
            if before_model_call is not None:
                pending = ChatResult(
                    request,
                    request_id,
                    document,
                    fixture,
                    Generation(status="result_unknown", error_type="interrupted_dispatch"),
                    "",
                    [],
                    0,
                    False,
                    self.settings.llm_model,
                ).research_record()
                pending.update(model_called=None, budget_reserved=True)
                before_model_call(pending)
            generation = await self.provider.complete(
                build_messages(request, document, fixture.canary)
            )
            visible_answer = generation.answer
            if request.defense_profile == Profile.B3:
                events.extend(inspect_output(generation.answer, fixture.canary))
                if events:
                    visible_answer = OUTPUT_BLOCK_ANSWER
            if not visible_answer and generation.status != "ok":
                visible_answer = {
                    "timeout": "模型请求超时，请稍后手动重试。",
                    "rate_limited": "模型服务限流，本次运行已暂停，请检查账号额度后重试。",
                }.get(
                    generation.status,
                    "模型暂未返回有效回答，请检查后端配置或服务状态。",
                )
        return ChatResult(
            request,
            request_id,
            document,
            fixture,
            generation,
            visible_answer,
            events,
            round((perf_counter() - started) * 1000),
            model_called,
            self.settings.llm_model,
        )

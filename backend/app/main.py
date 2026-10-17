import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import ChatService
from .config import BACKEND_ROOT, Settings
from .documents import load_document
from .provider import LLMClient
from .schemas import ChatRequest, ChatResponse, DocumentId


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = provider or LLMClient(settings)
        app.state.chat = ChatService(settings, client)
        try:
            yield
        finally:
            if provider is None:
                await client.close()

    app = FastAPI(title="PromptShield Lab", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # Do not echo submitted extra fields (which could contain a credential).
        return JSONResponse(
            status_code=422,
            content={
                "detail": "问题不能为空且最多 2000 字符；资料 ID 与档位必须来自白名单，不接受额外字段。"
            },
        )

    @app.get("/health")
    async def health():
        return {
            "status": "ready" if settings.configured else "not_configured",
            "configured": settings.configured,
            "model": settings.llm_model,
            "provider": settings.llm_provider,
        }

    @app.get("/api/examples")
    async def examples():
        # Public teaching fixtures only; never include system prompts or runtime secrets.
        data = json.loads(
            (BACKEND_ROOT / "data" / "cases" / "challenge.json").read_text(encoding="utf-8")
        )
        return {
            "version": data["version"],
            "examples": [
                {
                    "case_id": case["case_id"],
                    "title": case["title"],
                    "message": case["message"],
                    "document_id": case["document_id"],
                    "entry": "document" if case["category"] == "document_injection" else "message",
                    "explanation": case["explanation"],
                    "document_text": load_document(DocumentId(case["document_id"])).text,
                    "payload_text": load_document(DocumentId(case["document_id"]))
                    .text.removeprefix(load_document(DocumentId.clean).text)
                    .strip(),
                }
                for case in data["cases"]
                if case["goal"] != "normal"
            ],
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        result = await request.app.state.chat.run_chat(body)
        status = result.generation.status
        http_status = {"not_configured": 503, "timeout": 504, "rate_limited": 429}.get(
            status, 200 if status in ("ok", "truncated", "input_blocked") else 502
        )
        return JSONResponse(
            status_code=http_status,
            content=result.public_response().model_dump(mode="json"),
        )

    return app


app = create_app()

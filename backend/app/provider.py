from dataclasses import dataclass, field

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from .config import Settings


@dataclass
class Generation:
    answer: str = ""
    model: str | None = None
    status: str = "ok"
    error_type: str | None = None
    upstream_status: int | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    usage: dict = field(default_factory=dict)


class LLMClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value() or "not-configured",
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    async def complete(self, messages: list[dict]) -> Generation:
        if not self.settings.configured:
            return Generation(status="not_configured", error_type="missing_key")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                max_tokens=self.settings.llm_max_tokens,
                temperature=self.settings.llm_temperature,
                stream=False,
            )
            if not response.choices:
                return Generation(status="protocol_error", error_type="missing_choices")
            choice = response.choices[0]
            answer = choice.message.content or ""
            status = (
                "truncated"
                if choice.finish_reason == "length"
                else ("ok" if answer.strip() else "empty")
            )
            return Generation(
                answer=answer,
                model=response.model,
                status=status,
                finish_reason=choice.finish_reason,
                request_id=getattr(response, "_request_id", None),
                usage=response.usage.model_dump() if response.usage else {},
            )
        except APITimeoutError:
            return Generation(status="timeout", error_type="upstream_timeout")
        except APIConnectionError:
            return Generation(status="connection_error", error_type="upstream_connection")
        except APIStatusError as error:
            status = "rate_limited" if error.status_code == 429 else "upstream_error"
            return Generation(
                status=status,
                error_type="upstream_http",
                upstream_status=error.status_code,
            )
        except (ValueError, TypeError, AttributeError):
            return Generation(status="protocol_error", error_type="invalid_response")

    async def close(self) -> None:
        await self.client.close()

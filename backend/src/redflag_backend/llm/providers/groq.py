import httpx

from redflag_backend.llm.providers.openai_compat import OpenAICompatProvider

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(OpenAICompatProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            name="groq",
            url=GROQ_URL,
            api_key=api_key,
            model=model,
            # Groq deprecated max_tokens in favor of this field.
            token_field="max_completion_tokens",
            timeout=timeout,
            transport=transport,
        )

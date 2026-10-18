from redflag_backend.llm.provider import Provider
from redflag_backend.llm.providers.gemini import GeminiProvider
from redflag_backend.llm.providers.groq import GroqProvider
from redflag_backend.llm.providers.openrouter import OpenRouterProvider
from redflag_backend.settings import Settings


def build_providers(settings: Settings) -> list[Provider]:
    """The real providers, in the order the router tries them: Groq, Gemini, OpenRouter."""
    timeout = settings.provider_timeout_seconds
    return [
        GroqProvider(settings.groq_api_key, settings.groq_model, timeout),
        GeminiProvider(settings.gemini_api_key, settings.gemini_model, timeout),
        OpenRouterProvider(
            settings.openrouter_api_key,
            free_models=[m.strip() for m in settings.openrouter_free_models.split(",")],
            paid_model=settings.openrouter_paid_model,
            timeout=timeout,
        ),
    ]

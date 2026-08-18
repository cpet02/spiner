"""
Single choke point for all model calls. Every place in the codebase that
needs a VLM/LLM response goes through call_vision_model() or call_text_model().
To swap providers (OpenRouter -> direct Anthropic/OpenAI/etc.), only this
file changes.
"""
import base64
import requests
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class AIClientError(Exception):
    pass


def _headers():
    if not settings.OPENROUTER_API_KEY:
        raise AIClientError("OPENROUTER_API_KEY is not set")
    return {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }


def call_vision_model(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg",
                       model: str | None = None, max_tokens: int = 1024) -> str:
    """Send an image + prompt to a vision-language model, return the text response."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model or settings.AI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                    },
                ],
            }
        ],
        "max_tokens": max_tokens,
    }

    resp = requests.post(OPENROUTER_URL, headers=_headers(), json=payload, timeout=60)
    if resp.status_code != 200:
        raise AIClientError(f"OpenRouter error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise AIClientError(f"Unexpected response shape: {data}") from e


def call_text_model(prompt: str, model: str | None = None, max_tokens: int = 1024) -> str:
    """Plain text-in, text-out call. Useful for post-processing VLM output,
    generating structured summaries, etc."""
    payload = {
        "model": model or settings.AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }

    resp = requests.post(OPENROUTER_URL, headers=_headers(), json=payload, timeout=60)
    if resp.status_code != 200:
        raise AIClientError(f"OpenRouter error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise AIClientError(f"Unexpected response shape: {data}") from e

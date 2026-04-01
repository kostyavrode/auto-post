import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
    return _client


async def translate_text(text: str, target_lang: str, model: str = "deepseek-chat") -> str:
    """Translate text to target_lang using the LLM. Returns translated text."""
    if not text.strip():
        return text

    client = get_client()
    prompt = (
        f"Translate the following text to {target_lang}. "
        f"Return ONLY the translated text, no explanations or comments.\n\n{text}"
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("Translation error: %s", exc)
        return text


def detect_language(text: str) -> str:
    """Detect the language of the text. Returns ISO 639-1 code."""
    try:
        from langdetect import detect
        return detect(text[:500])
    except Exception:
        return "unknown"

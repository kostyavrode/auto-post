import logging
import os
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from .translator import get_client

logger = logging.getLogger(__name__)

EXAMPLES_DIR = Path(os.getenv("EXAMPLES_DIR", "examples"))


def load_examples() -> List[str]:
    """Load all example posts from the examples directory."""
    examples = []
    if not EXAMPLES_DIR.exists():
        return examples
    for path in sorted(EXAMPLES_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            examples.append(text)
    return examples


async def generate_post(
    title: str,
    body: str,
    source_url: str = "",
    model: str = "deepseek-chat",
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Generate a Telegram post from an article using few-shot examples.
    """
    examples = load_examples()
    client = get_client()

    if examples:
        examples_block = "\n\n---\n\n".join(
            f"Example {i + 1}:\n{ex}" for i, ex in enumerate(examples)
        )
        system_prompt = (
            "You are a Telegram channel editor. "
            "Below are examples of how posts should look. "
            "Follow the same style, tone, length, formatting, and emoji usage.\n\n"
            f"{examples_block}"
        )
    else:
        system_prompt = (
            "You are a Telegram channel editor. "
            "Write a concise, engaging Telegram post based on the article provided. "
            "Use plain text suitable for Telegram (you may use emoji if appropriate)."
        )

    article_block = f"Title: {title}\n\n{body}"
    if source_url:
        article_block += f"\n\nSource: {source_url}"

    user_prompt = (
        "Write a Telegram post for this article. "
        "Return ONLY the post text, nothing else.\n\n"
        f"{article_block}"
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("Post generation error: %s", exc)
        return f"<b>{title}</b>\n\n{body[:300]}..."

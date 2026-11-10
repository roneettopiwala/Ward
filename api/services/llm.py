"""The one client every LLM call goes through (LiteLLM, so models can be swapped).

Responses are JSON validated against a Pydantic model. On a failure the model
sees the error and gets one retry; a second failure raises LLMError.
"""

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

import litellm
from pydantic import BaseModel, ValidationError

from settings import get_settings

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MAX_TOKENS = 8000
TIMEOUT_S = 120


class LLMError(Exception):
    pass


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


async def complete_json[T: BaseModel](
    system: str,
    user: str,
    schema: type[T],
    check: Callable[[T], list[str]] | None = None,
    model: str | None = None,
    timeout_s: float = TIMEOUT_S,
    max_tokens: int = MAX_TOKENS,
) -> tuple[T, str]:
    """The model's reply parsed into `schema`, and the model that wrote it.

    `check` returns problems Pydantic can't see (e.g. citations to unknown
    facts); any problem counts as a failure and triggers the retry.
    """
    settings = get_settings()
    model = model or settings.llm_model
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    for attempt in range(2):
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=timeout_s,
            api_key=settings.anthropic_api_key or None,
        )
        reply = response.choices[0].message.content or ""
        try:
            parsed = schema.model_validate_json(_json_text(reply))
            problems = check(parsed) if check else []
        except ValidationError as e:
            problems = [f"{err['msg']} at {'.'.join(map(str, err['loc']))}" for err in e.errors()]
        except ValueError as e:
            problems = [f"not a JSON object: {e}"]
        if not problems:
            return parsed, model
        log.warning("%s reply failed validation (attempt %d): %s", model, attempt + 1, problems)
        messages += [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": "Your reply had these problems:\n- "
                + "\n- ".join(problems)
                + "\nReply again with the corrected JSON object only.",
            },
        ]
    raise LLMError(f"{model} gave invalid output twice: {problems}")


def _json_text(reply: str) -> str:
    """The JSON object in a reply, without any code fence around it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", reply, re.DOTALL)
    text = fenced.group(1) if fenced else reply
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    candidate = text[start : end + 1]
    json.loads(candidate)  # raises ValueError on a syntax error
    return candidate

import json
from typing import TypeVar

from ollama import Client
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class OllamaStructuredOutputError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, model: str = "gemma4:12b", host: str = "http://localhost:11434"):
        self.model = model
        self.client = Client(host=host)

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = self.client.chat(
            model=self.model,
            messages=messages,
            options={"temperature": 0},
        )

        content = (response.message.content or "").strip()

        if not content:
            raise OllamaStructuredOutputError(
                f"Model {self.model} returned an empty response."
            )

        return content

    def generate_structured(self, prompt: str, schema: type[T], system_prompt: str | None = None) -> T:
        schema_json = schema.model_json_schema()
        schema_text = json.dumps(schema_json, indent=2)

        structured_prompt = f"""
{prompt}

Return ONLY valid JSON matching this JSON schema:

{schema_text}

Do not return markdown.
Do not include explanations outside the JSON object.
"""

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": structured_prompt})

        response = self.client.chat(
            model=self.model,
            messages=messages,
            format=schema_json,
            options={"temperature": 0},
            think=False,
        )

        content = (response.message.content or "").strip()

        if not content:
            thinking = (getattr(response.message, "thinking", None) or "").strip()

            raise OllamaStructuredOutputError(
                f"Model {self.model} returned empty structured output. "
                f"Thinking output: {thinking[:500]!r}"
            )

        try:
            return schema.model_validate_json(content)

        except ValidationError as exc:
            raise OllamaStructuredOutputError(
                f"Ollama returned invalid {schema.__name__} output.\n\n"
                f"Raw response:\n{content}"
            ) from exc
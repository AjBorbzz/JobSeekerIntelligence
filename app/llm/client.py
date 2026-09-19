from typing import TypeVar 
from ollama import Client 
from pydantic import BaseModel 

T = TypeVar("T", bound=BaseModel,)


class OllamaClient:
    def __init__(self, model: str = "gemma4:12b", host: str = "http://localhost:11434",):
        self.model = model 
        self.client = Client(host=host,)

    def generate(self, prompt: str, system_prompt: str | None = None,) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt,})

        response = self.client.chat(model=self.model, messages=messages,)
        return response.message.content

    def generate_structured(self, prompt: str, schema: type[T], system_prompt: str | None = None) -> T:
        messages= []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt,})
        response = self.client.chat(
            model=self.model,
            messages=messages,
            format=schema.model_json_schema(),
            options={"temperature":0},
        )
        return schema.model_validate_json(response.message.content)
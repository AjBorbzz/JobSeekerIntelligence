import ollama 


class OllamaClient:
    def __init__(self, model: str = "gemma4:12b"):
        self.model = model 

    def generate(self, prompt: str) -> str:
        response = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        return response["message"]["content"]
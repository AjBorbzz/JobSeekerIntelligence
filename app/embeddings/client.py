from ollama import Client 

class EmbeddingClient:
    def __init__(self, model: str="nomic-embed-text:latest",
                       host: str = "http://localhost:11434"):
        self.model = model 
        self.client = Client(host=host,)

    def embed(self, text: str,) -> list[float]:
        text = text.strip()
        if not text:
            raise ValueError("Cannot generate an embedding for empty text.")

        response = self.client.embed(model=self.model, input=text,)

        embeddings = response.embeddings 
        if not embeddings:
            raise RuntimeError(f"Model {self.model} returned no embeddings.")
        return embeddings[0]

    def embed_batch(self, texts: list[str],) -> list[list[float]]:
        cleaned = [text.strip() for text in texts if text.strip()]

        if not cleaned:
            raise ValueError("Cannot generate embeddings for an empty input list.")

        response = self.client.embed(model=self.model, input=cleaned,)

        return response.embeddings

    
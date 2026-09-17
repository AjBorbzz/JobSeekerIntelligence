from fastapi import FastAPI
from app.llm.client import OllamaClient


app = FastAPI(
    title="Job Intelligence",
    description="Local AI-powered job intelligence and POC generation system",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "job-intelligence",
    }

@app.get("/ollama/test")
def test_ollama():
    client = OllamaClient()
    response = client.generate("Respond with exactly: Ollama READY")

    return {
        "model": client.model,
        "response": response
    }
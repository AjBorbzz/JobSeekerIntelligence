# Job Intelligence — Startup Guide

Step-by-step instructions for starting the local application and using its current workflow through Phase 7.

These commands target macOS with Terminal (zsh or bash). They assume the existing `job-intelligence` source code is already on your computer. This guide does not create or replace application code.

## 1. Know what needs to run

| Component | Purpose | Local address | How it starts |
|---|---|---|---|
| Ollama server | Hosts the local language and embedding models | `http://localhost:11434` | Ollama desktop app **or** `ollama serve` |
| FastAPI application, served by Uvicorn | Runs the Job Intelligence API | `http://127.0.0.1:8000` | `python -m uvicorn app.main:app ...` |
| Swagger UI | Browser interface for calling the API | `http://127.0.0.1:8000/docs` | Served automatically by FastAPI |

You do not start FastAPI and Uvicorn separately. Uvicorn serves the FastAPI application in one process.

There is currently no separate frontend, database server, Docker stack, Redis, or worker to start. Phase 8 persistence has not been implemented.

The application uses these configured model names:

| Model | Responsibility |
|---|---|
| `gemma4:12b` | Job analysis and POC generation |
| `nomic-embed-text` | Embeddings for semantic relevance |
| `qwen3:8b` | Independent POC evaluation |

All three use the same Ollama server. You do not need three Ollama servers or three interactive model sessions. A model being installed is different from it being loaded into memory.

> Current limitation: application records are stored in memory. Stopping, restarting, or auto-reloading FastAPI clears those records. Keep copies of the job descriptions and request bodies you need to reuse.

## 2. One-time setup: check the tools

Open Terminal and run:

```bash
python3 --version
ollama --version
```

The documented project baseline is Python 3.11. Use your existing working project interpreter; do not recreate a working environment solely to follow this guide.

If either command is missing, install the relevant prerequisite first:

- [Python downloads](https://www.python.org/downloads/)
- [Ollama download](https://ollama.com/download)

After installation, open a new Terminal window and retry the commands.

## 3. Open the existing project directory

Replace the example path with the actual location on your Mac:

```bash
cd /absolute/path/to/job-intelligence
pwd
ls
```

You should see `app`, `tests`, and `requirements.txt`. The application file should be `app/main.py`.

Run project commands from this directory, not from `app/` or `tests/`.

## 4. Prepare and activate the Python environment

### If the environment already exists

```bash
source .venv/bin/activate
```

If your existing environment is named `venv`, use its actual path instead:

```bash
source venv/bin/activate
```

Use only the command that matches your project.

### If this is a fresh checkout without an environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Dependencies need installing on initial setup and when `requirements.txt` changes, not every time you start the app.

### Verify the active interpreter

```bash
python -c 'import sys; print(sys.executable)'
python -c 'import fastapi, uvicorn, ollama, pydantic, numpy; print("Dependencies import successfully")'
```

The interpreter path should point into your project's virtual environment. An import failure means a dependency is unavailable in that environment.

## 5. Start Ollama first

Open another Terminal tab. Check whether its server is already running:

```bash
curl -fsS http://localhost:11434/api/tags
```

If you receive JSON containing a `models` field, Ollama is already available. Do not launch a duplicate server.

If the connection fails, choose one startup method:

### Method A — macOS desktop app

Open Ollama from Applications. Alternatively:

```bash
open -a Ollama
```

Then retry the `curl` check above.

### Method B — terminal-managed server

If Ollama is installed but its server is not running:

```bash
ollama serve
```

Leave that tab running. Use a different tab for subsequent commands.

You do not need to activate the Python virtual environment to run the Ollama executable.

Checkpoint: `curl -fsS http://localhost:11434/api/tags` returns JSON. This verifies server reachability, not that model inference works.

## 6. Check the required models

In a free Terminal tab:

```bash
ollama list
```

Compare the installed model names with the names configured in the application. `nomic-embed-text:latest` normally corresponds to the untagged `nomic-embed-text` name.

Download only missing models:

```bash
ollama pull gemma4:12b
ollama pull nomic-embed-text
ollama pull qwen3:8b
```

These are the project's configured names, not a guarantee that each tag is available from the public registry. If a pull reports an unavailable manifest, check the original model name or local custom alias used by your existing project. Do not silently switch the application to an unrelated model.

Model downloads require internet access and disk space. Once installed, the local workflow does not need to download them on each startup.

Optional first-use inference checks:

```bash
ollama run gemma4:12b 'Respond with exactly READY.'
ollama run qwen3:8b 'Respond with exactly READY.'
```

A response verifies basic generation; extra explanation or thinking text does not necessarily mean the model failed. These checks do not validate the application's structured-output prompts.

For an embedding check:

```bash
curl -fsS http://localhost:11434/api/embed \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text","input":"Python backend developer"}'
```

Expect JSON containing `embeddings` with numeric vectors. Do not use an embedding model as a chat model.

## 7. Start the Job Intelligence application

Return to the project Terminal tab. Confirm the environment is activated, then run:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave this tab running. Successful startup includes an application-startup message and the local server URL.

This command intentionally omits auto-reload so editing a file will not unexpectedly erase your current in-memory session. After changing application code, restart deliberately when ready.

For active development, use this alternative **instead of** the command above:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

With `--reload`, source changes can restart the application and clear its records. Do not add multiple workers while storage is process-local: different workers would have different records.

The `127.0.0.1` binding keeps the API on your own machine. The app is a development POC without production authentication or multi-user isolation.

## 8. Verify the application

Open a free Terminal tab and run:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","service":"job-intelligence"}
```

This endpoint checks the application, not every AI dependency.

Check the application-to-Ollama connection:

```bash
curl -fsS http://127.0.0.1:8000/ollama/test
```

Expect a response containing the configured model and generated text. The first inference may take longer while the model loads.

Open the API interface:

[Swagger UI](http://127.0.0.1:8000/docs)

Checkpoint: the health check succeeds, the Ollama test returns generated content, and Swagger displays the API operations.

## 9. Run one complete job workflow

Use Swagger for these steps. Expand each operation, click **Try it out**, enter its values, and click **Execute**. The schemas shown by your running application are authoritative if they differ from these examples.

### 9.1 Create a job

Use `POST /jobs/manual` with:

```json
{
  "title": "Python AI Backend Developer",
  "company": "Example AI Company",
  "type_of_work": "full_time",
  "hours_per_week": 40,
  "job_overview": "We need a Python developer to build FastAPI endpoints and integrate local LLM APIs. Our platform uses PostgreSQL. You will improve document ingestion and implement semantic search using vector embeddings. Experience with RAG is preferred. Our main challenge is producing accurate answers from uploaded documents."
}
```

Expect HTTP `201`. Copy the returned `id`; use that UUID as `job_id` in every subsequent step. Do not paste the literal text `{job_id}`.

### 9.2 Analyze the job

Use `POST /jobs/{job_id}/analyze`.

Expect structured analysis containing skills, responsibilities, technologies, and evidence. Wait for the request to finish before continuing.

### 9.3 Calculate semantic relevance

Use `POST /jobs/{job_id}/semantic-relevance` with:

```json
{"query":"Python backend developer"}
```

This exercises the embedding model and Python similarity calculation.

### 9.4 Calculate hybrid relevance

Use `POST /jobs/{job_id}/relevance` with:

```json
{
  "query": "Python backend developer",
  "required_skills": ["Python", "FastAPI"],
  "preferred_skills": ["PostgreSQL", "RAG"],
  "work_types": ["full_time"],
  "max_hours_per_week": 40
}
```

Expect component scores and a combined relevance result. These scores are not probabilities of hiring or suitability.

### 9.5 Generate a POC proposal

Use `POST /jobs/{job_id}/poc` with:

```json
{
  "criteria": {
    "query": "Python backend developer",
    "required_skills": ["Python", "FastAPI"],
    "preferred_skills": ["PostgreSQL", "RAG"],
    "work_types": ["full_time"],
    "max_hours_per_week": 40
  },
  "max_complexity": "small"
}
```

Expect a structured project proposal with features, architecture, implementation steps, and acceptance criteria. This generates a proposal, not an automatically implemented software project.

### 9.6 Evaluate the generated POC

Locate the Phase 7 POC evaluation operation in Swagger. Enter the same job UUID and any request fields required by its displayed schema. Execute it after POC generation completes.

The exact Phase 7 evaluation URL and request schema are not present in the saved Phase 6 README, so this guide does not invent them. If no evaluation operation appears, your running checkout may not contain or register Phase 7 yet.

The recorded Phase 7 functionality evaluates covered, partially covered, and missing requirements, irrelevant complexity, and Python-calculated technology coverage using `qwen3:8b` for interpretation.

### 9.7 Retrieve the stored results

These documented retrieval routes are available while the current process remains alive:

- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/analysis`
- `GET /jobs/{job_id}/poc`

Use Swagger for any additional retrieval routes implemented by your checkout. Copy important outputs before stopping the application; persistence is still pending.

## 10. Run automated tests

In a separate Terminal tab:

```bash
cd /absolute/path/to/job-intelligence
source .venv/bin/activate
python -m pytest -v
```

Use your actual project path and environment name. Normal unit tests use fake clients and should not require the FastAPI server or live Ollama inference. Passing unit tests alone does not prove the real models are working; the checks above cover that separately.

## 11. Daily startup checklist

After setup is complete, the routine is:

1. Open Ollama, or reuse its already running server.
2. Confirm it responds: `curl -fsS http://localhost:11434/api/tags`.
3. Open Terminal in the project root.
4. Activate the environment: `source .venv/bin/activate`.
5. Start the app: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
6. Open [Swagger UI](http://127.0.0.1:8000/docs).
7. Submit a job and follow the analysis → scoring → POC → evaluation workflow.

Do not reinstall dependencies, download models, or run `ollama run` separately on every startup. The app requests inference from the shared Ollama server.

## 12. Stop the application

1. Copy any important request bodies and results.
2. Press `Ctrl+C` in the FastAPI terminal. Its in-memory records are lost.
3. Run `deactivate` to leave that terminal's Python environment if finished.
4. If you started Ollama with `ollama serve`, press `Ctrl+C` in its terminal when it is no longer needed. If using the desktop app, quit it through its app/menu controls instead.

Optional: use `ollama ps` to inspect loaded models and `ollama stop MODEL_NAME` to unload a specific model while leaving the Ollama server running. Unloading a model does not uninstall it.

## 13. Troubleshooting

| Symptom | Check or action |
|---|---|
| `python` not found | Activate the project environment. Use `python3` to create it if necessary. |
| `No module named uvicorn` or another dependency | Activate the correct environment, then run `python -m pip install -r requirements.txt`. |
| `No module named app` or error importing `app.main` | Run from the repository root and confirm `app/main.py` exists. Inspect the traceback for an actual dependency or syntax error. |
| Connection refused on port `11434` | Start Ollama and retry `/api/tags`. |
| Address already in use on port `11434` | Check `/api/tags`; an Ollama server may already be running. Reuse it. |
| Address already in use on port `8000` | Inspect `lsof -nP -iTCP:8000 -sTCP:LISTEN`. If it is your existing app, reuse it or stop it with `Ctrl+C` in its original terminal. Do not terminate an unidentified process. |
| Port `8000` belongs to another application | Start this app with `--port 8001` and use `http://127.0.0.1:8001` for its URLs. |
| Model not found | Run `ollama list` and compare exact names/tags with application configuration. Pull the missing configured model if available. |
| `/health` works but analysis fails | Health does not verify Ollama or structured generation. Check `/ollama/test`, model availability, and both server logs. |
| Request is slow | Allow the first model load to finish. Check `ollama ps` and system memory. Run one AI request at a time and avoid loading unnecessary models. |
| Invalid JSON / empty model output | Inspect the FastAPI traceback and Ollama response. Reachability alone does not guarantee valid structured output. The project includes an empty-response check. |
| HTTP `422` | Read Swagger's validation response. Check enum values, required fields, valid UUIDs, and hours constraints. |
| HTTP `404` for an earlier job | Check whether FastAPI restarted or auto-reloaded. If records were cleared, create the job again and use its new UUID. |
| POC generation lacks analysis | Run the job analysis operation first. |
| Evaluation lacks a POC | Complete POC generation first. |

Do not expose either server publicly to resolve a local connection issue.

## References and scope

- [Ollama CLI reference](https://docs.ollama.com/cli)
- [Ollama: list installed models API](https://docs.ollama.com/api/tags)
- [Ollama: embeddings API](https://docs.ollama.com/api/embed)
- [FastAPI: run a server manually](https://fastapi.tiangolo.com/deployment/manually/)

Project-specific endpoints and payloads through Phase 6 are grounded in the saved repository README. Phase 7 availability is based on the latest recorded project milestone; its exact routes must be read from the running application's OpenAPI documentation. This guide has not been executed against your Mac or inspected against a current source checkout.

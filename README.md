# Job Intelligence

Local AI-powered job analysis, relevance scoring, and interview POC generation system built with Python, FastAPI, Pydantic, Ollama, and local embedding models.

The project is designed to take a job advertisement, interpret what the employer is actually asking for, measure how relevant the job is to a user's search criteria, and generate a small proof-of-concept project that demonstrates the most important skills and business needs described in the job.

> Development status: **Phases 1–6 implemented.**
> The project is currently a local proof of concept and is not production-ready.

---

## Project Goals

The complete application is intended to:

1. Accept or collect job listings from an authorized source.
2. Preserve factual job information separately from AI-generated interpretation.
3. Analyze job descriptions using a local LLM.
4. Identify required skills, preferred skills, technology stack, responsibilities, employer pain points, business problems, expected deliverables, and seniority.
5. Compare jobs against user search criteria.
6. Calculate semantic similarity using embeddings.
7. Produce a transparent hybrid relevance score.
8. Generate a job-specific mini-project or POC.
9. Independently evaluate the generated POC against the original job requirements.
10. Persist searches, jobs, analyses, scores, and project proposals.
11. Export a final job-intelligence PDF report.

The current implementation covers steps 2–8.

---

## Current Capabilities

Implemented:

- FastAPI application with OpenAPI/Swagger documentation.
- Ollama connectivity through a dedicated client abstraction.
- Manual job submission.
- Pydantic validation for job data.
- In-memory storage for jobs, analyses, and POC proposals.
- Structured job analysis using `gemma4:12b`.
- Separation of source facts from AI interpretation.
- Evidence-backed job analysis.
- Required vs preferred skill separation.
- Existing technology stack vs applicant requirement separation.
- Employer pain-point extraction.
- Business-problem extraction.
- Expected-deliverable extraction.
- Semantic relevance scoring using `nomic-embed-text`.
- Cosine similarity calculated in Python.
- Hybrid relevance scoring.
- Required and preferred skill matching.
- Work-type and hours-per-week constraint checks.
- Active-weight normalization for relevance scores.
- Structured POC generation using `gemma4:12b`.
- Job-specific architecture, features, implementation steps, demo scenario, and acceptance criteria.
- Unit tests that avoid live Ollama calls by using dependency injection and fake clients.

Not yet implemented:

- Independent POC evaluation using `qwen3:8b`.
- SQLite persistence.
- Automated HTML parsing and authorized job-source collection.
- PDF report generation.
- Labeled evaluation dataset and threshold calibration.
- Controlled POC revision loop.
- Production deployment.

---

## Architecture

```text
                       User Search Criteria
                               │
                               ▼
                         Manual Job Input
                               │
                               ▼
                           Job Model
                               │
                               ▼
                        gemma4:12b
                               │
                               ▼
                        JobAnalysisData
                               │
                    Python adds job_id
                               │
                               ▼
                          JobAnalysis
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
      nomic-embed-text                  Deterministic Rules
              │                                 │
              ▼                                 ▼
     Semantic Similarity               Role / Skill / Work Match
              │                                 │
              └───────────────┬─────────────────┘
                              ▼
                     Hybrid Relevance
                              │
                              ▼
                        gemma4:12b
                              │
                              ▼
                       POCProposalData
                              │
                   Python adds metadata
                              │
                              ▼
                         POCProposal
```

The application deliberately divides responsibilities:

| Responsibility | Implementation |
|---|---|
| Job facts | Python + Pydantic |
| Job interpretation | `gemma4:12b` |
| Semantic similarity | `nomic-embed-text` + cosine similarity |
| Role matching | Python |
| Skill matching | Python |
| Work constraints | Python |
| Weighted scoring | Python |
| POC design | `gemma4:12b` |
| POC evaluation | Planned: `qwen3:8b` |

---

## Technology Stack

| Component | Purpose |
|---|---|
| Python 3.11 | Application language |
| FastAPI | REST API |
| Uvicorn | Development ASGI server |
| Pydantic | Domain validation and structured LLM output |
| Ollama | Local LLM and embedding runtime |
| `gemma4:12b` | Job analysis and POC generation |
| `nomic-embed-text` | Semantic embeddings |
| NumPy | Vector calculations |
| Pytest | Automated testing |

Planned:

| Component | Purpose |
|---|---|
| `qwen3:8b` | Independent POC evaluator |
| SQLite | Persistent local storage |
| ReportLab | PDF report generation |

---

## Repository Structure

```text
job-intelligence/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── jobs.py
│   ├── embeddings/
│   │   ├── __init__.py
│   │   └── client.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── job_analyzer.py
│   │   └── poc_generator.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── semantic_relevance.py
│   │   └── hybrid_relevance.py
│   └── services/
│       ├── __init__.py
│       ├── job_service.py
│       ├── analysis_service.py
│       ├── relevance_service.py
│       ├── hybrid_relevance_service.py
│       └── poc_service.py
├── tests/
│   ├── test_jobs.py
│   ├── test_analysis_models.py
│   ├── test_semantic_relevance.py
│   ├── test_hybrid_relevance.py
│   └── test_poc_generator.py
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## Development Phases

| Phase | Scope | Status |
|---:|---|---|
| 1 | FastAPI foundation and Ollama connectivity | Implemented |
| 2 | Job models and manual job ingestion | Implemented |
| 3 | Structured LLM job analysis | Implemented |
| 4 | Embeddings and semantic relevance | Implemented |
| 5 | Hybrid relevance engine | Implemented |
| 6 | Job-specific POC generator | Implemented |
| 7 | Independent POC evaluator | Next |
| 8 | SQLite persistence and job history | Planned |
| 9 | Job-source abstraction and HTML parsing | Planned |
| 10 | Authorized job-search integration | Planned |
| 11 | PDF intelligence report generation | Planned |
| 12 | Evaluation dataset and accuracy tuning | Planned |
| 13 | Controlled agentic revision workflow | Planned |
| 14 | Final cleanup and portfolio release | Planned |

---

# Installation

## 1. Clone the repository

```bash
git clone <repository-url>
cd job-intelligence
```

## 2. Create a virtual environment

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

A current dependency set resembles:

```text
fastapi
uvicorn[standard]
ollama
pydantic
numpy
pytest
```

## 4. Verify Ollama models

```bash
ollama list
```

The current implementation requires:

```text
gemma4:12b
nomic-embed-text:latest
```

Pull them if necessary:

```bash
ollama pull gemma4:12b
ollama pull nomic-embed-text
```

---

# Running the Application

Start FastAPI from the repository root:

```bash
uvicorn app.main:app --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Base URL:

```text
http://127.0.0.1:8000
```

---

# API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Verify FastAPI service status |
| `GET` | `/ollama/test` | Verify Ollama connectivity |
| `POST` | `/jobs/manual` | Create a job manually |
| `GET` | `/jobs` | List stored jobs |
| `GET` | `/jobs/{job_id}` | Retrieve one job |
| `POST` | `/jobs/{job_id}/analyze` | Analyze a job with Gemma |
| `GET` | `/jobs/{job_id}/analysis` | Retrieve stored analysis |
| `POST` | `/jobs/{job_id}/semantic-relevance` | Calculate embedding similarity |
| `POST` | `/jobs/{job_id}/relevance` | Calculate hybrid relevance |
| `POST` | `/jobs/{job_id}/poc` | Generate a job-specific POC |
| `GET` | `/jobs/{job_id}/poc` | Retrieve generated POC |

---

# Example Workflow

## 1. Create a Job

```http
POST /jobs/manual
```

Example body:

```json
{
  "title": "Python AI Backend Developer",
  "source_url": "https://example.com/jobs/python-ai",
  "company": "Example AI Company",
  "type_of_work": "full_time",
  "hours_per_week": 40,
  "salary": "$2000-$3000/month",
  "date_updated": "2026-09-27",
  "job_overview": "We are building an AI-powered document processing platform and need a Python developer to help complete our backend MVP. You will develop FastAPI endpoints, integrate local and cloud LLM APIs, improve our document ingestion pipeline, and implement semantic search using vector embeddings. Our current application uses a React frontend and PostgreSQL database. Experience with RAG systems is strongly preferred. The main challenge is improving the reliability of document extraction and producing accurate answers from uploaded documents."
}
```

The server generates `id` and `created_at`. These values are application-owned and are never delegated to the LLM.

---

# Structured Job Analysis

Analyze the job:

```http
POST /jobs/{job_id}/analyze
```

The analysis contains:

```text
role_category
role_summary
seniority
required_skills
preferred_skills
tech_stack
responsibilities
employer_pain_points
business_problem
expected_deliverables
evidence
```

The LLM does not create the complete `JobAnalysis` object directly.

```text
Gemma
  ↓
JobAnalysisData
  +
Python-controlled job_id
  ↓
JobAnalysis
```

This prevents application metadata from being fabricated by the model.

---

# Structured Output Reliability

`OllamaClient.generate_structured()`:

1. Generates a Pydantic JSON schema.
2. Includes the schema in the LLM prompt.
3. Passes the schema to Ollama structured output.
4. Uses temperature `0`.
5. Rejects empty responses before Pydantic parsing.
6. Validates returned JSON against the requested schema.

The defensive check is important because an empty Ollama response previously caused:

```text
Invalid JSON: EOF while parsing a value
```

The client now raises a clearer application exception instead of passing an empty string directly to Pydantic.

---

# Semantic Relevance

Phase 4 introduced semantic comparison using `nomic-embed-text`.

```text
Search query
     │
     ▼
Embedding vector

Normalized JobAnalysis
     │
     ▼
Embedding vector

Both vectors
     │
     ▼
Cosine similarity
```

Example request:

```http
POST /jobs/{job_id}/semantic-relevance
```

```json
{
  "query": "Python backend developer"
}
```

The semantic score is not a probability. It is a presentation of embedding similarity.

---

# Hybrid Relevance

Phase 5 combines multiple signals:

```text
Semantic relevance     50%
Role/title relevance   20%
Skill relevance        20%
Work constraints       10%
```

The system evaluates:

- semantic similarity
- role/title overlap
- required skill matches
- preferred skill matches
- work type
- hours per week

Example request:

```http
POST /jobs/{job_id}/relevance
```

```json
{
  "query": "Python backend developer",
  "required_skills": ["Python", "FastAPI"],
  "preferred_skills": ["PostgreSQL", "RAG"],
  "work_types": ["full_time"],
  "max_hours_per_week": 40
}
```

Missing user criteria are not treated as failed criteria. Only active scoring components contribute to the denominator.

---

# Job-Specific POC Generation

Phase 6 generates a deliberately small project based on:

```text
JobAnalysis
+
SearchCriteria
+
HybridRelevance
```

Endpoint:

```http
POST /jobs/{job_id}/poc
```

Example:

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

The generator returns structured fields including:

```text
project_name
objective
problem_statement
why_relevant
tech_stack
features
architecture
data_flow
implementation_steps
alignment
demo_scenario
acceptance_criteria
out_of_scope
complexity
```

Application-controlled metadata is added afterward:

```text
job_id
search_query
job_relevance_score
generated_by
```

For an AI document-processing job, the proposal may resemble:

```text
Document Intelligence API

PDF
 ↓
Text extraction
 ↓
Chunking
 ↓
Embeddings
 ↓
Semantic retrieval
 ↓
Local LLM
 ↓
Grounded answer
```

The generator is explicitly instructed not to create an unnecessary enterprise platform.

---

# Design Principles

## Facts and AI interpretation remain separate

`Job` represents source facts. `JobAnalysis` represents interpreted information.

## LLMs interpret; Python calculates

LLMs are used for job interpretation, employer pain-point interpretation, and POC design.

Python handles IDs, validation, storage, cosine similarity, skill matching, role matching, constraint evaluation, and weighted relevance.

## Generator and evaluator remain separate

Currently:

```text
gemma4:12b
   ↓
POC generation
```

The next phase will add:

```text
qwen3:8b
   ↓
Independent POC evaluation
```

## Project scope remains deliberately small

The project does not currently require LangChain, CrewAI, AutoGen, Redis, Celery, Kubernetes, React, or a vector database.

---

# Testing

Run:

```bash
python -m pytest -v
```

`pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Current tests cover:

- manual job creation
- invalid job validation
- valid analysis models
- invalid seniority values
- cosine similarity
- semantic score conversion
- vector dimension errors
- role matching
- required skill matching
- preferred skill matching
- missing skill detection
- work constraints
- weight normalization
- hybrid relevance service
- structured POC generation
- POC service orchestration

Normal unit tests should not depend on a running Ollama server. Production clients are replaced with fake clients during unit testing.

---

# Current Storage Model

Storage is currently process-local:

```text
dict[UUID, Job]
dict[UUID, JobAnalysis]
dict[UUID, POCProposal]
```

Restarting FastAPI deletes all records. This is intentional during the early phases. Phase 8 will replace in-memory storage with SQLite.

---

# Known Issues and Limitations

- Jobs, analyses, and POCs are stored only in memory.
- Synchronous LLM requests block until local inference completes.
- Relevance scoring is reproducible but not yet statistically calibrated.
- Skill aliases currently cover only limited equivalent terms.
- Generated POCs are not yet independently evaluated.
- There is no authentication, authorization, rate limiting, or multi-user isolation.
- Automated job collection is not implemented yet.
- PDF report generation is not implemented yet.

Do not interpret a relevance score such as `91.42` as a 91.42% probability that a job is suitable.

---

# Troubleshooting

## `ModuleNotFoundError: No module named 'app'`

Run tests from the repository root:

```bash
python -m pytest -v
```

Ensure `pytest.ini` contains:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

## `Invalid JSON: EOF while parsing a value`

This means Pydantic received an empty string from the LLM response.

The current client should check:

```python
content = (response.message.content or "").strip()
```

before calling:

```python
schema.model_validate_json(content)
```

## Relevance weight validation error

Weights must satisfy:

```python
weight: float = Field(gt=0.0, le=1.0)
```

Example valid weights:

```text
0.50
0.20
0.20
0.10
```

---

# Current End-to-End Flow

```text
1. Submit job
       ↓
2. Validate job
       ↓
3. Analyze job using Gemma
       ↓
4. Extract structured requirements
       ↓
5. Generate embeddings
       ↓
6. Calculate semantic relevance
       ↓
7. Match role and skills
       ↓
8. Evaluate work constraints
       ↓
9. Calculate hybrid relevance
       ↓
10. Generate interview POC
```

This is the current working pipeline.

---

# Next Phase

## Phase 7 — Independent POC Evaluation

The next implementation will introduce:

```text
Generated POC
    │
    ├──────────── Job Requirements
    │
    ▼
qwen3:8b
    │
    ▼
Independent Evaluation
    │
    ├── Covered requirements
    ├── Partially covered requirements
    ├── Missing requirements
    ├── Irrelevant complexity
    └── Evaluation explanation
```

Deterministic technology coverage will be combined with the evaluator output to produce a separate POC relevance score.

---

# Future Roadmap

```text
Phase 8   SQLite persistence
Phase 9   JobSource abstraction + HTML parser
Phase 10  Authorized job listing search integration
Phase 11  PDF Job Intelligence Report
Phase 12  Labeled evaluation dataset + calibration
Phase 13  One controlled POC revision loop
Phase 14  Final cleanup and portfolio release
```

---

# Responsible Use

The system is intended as a decision-support and learning tool.

LLM-generated analysis can omit requirements, misclassify technologies, over-interpret employer wording, misunderstand implicit business needs, or generate an inappropriate project proposal.

Structured output guarantees format, not truth.

Important conclusions should remain traceable to the original job description through evidence fields.

Any future automated job-board integration must respect the source's terms, access controls, and applicable law.

---

# Version History

## `0.6.0`

- Added structured POC schemas.
- Added `POCGenerator`.
- Added `POCService`.
- Added POC generation and retrieval endpoints.
- Added job-specific features, architecture, implementation steps, demo scenario, and acceptance criteria.
- Added application-controlled POC metadata.
- Added POC unit tests using fake LLM clients.

## `0.5.0`

- Added hybrid relevance scoring.
- Added `SearchCriteria`.
- Added role matching.
- Added required and preferred skill matching.
- Added work-type and hours constraints.
- Added active-weight normalization.
- Added hybrid relevance endpoint.

## `0.4.0`

- Added embedding support using `nomic-embed-text`.
- Added cosine similarity.
- Added semantic relevance scoring.
- Added normalized job-document generation.
- Added semantic relevance endpoint.

## `0.3.1`

- Improved structured-output error handling.
- Added empty Ollama response detection.
- Split `JobAnalysisData` from application-owned `JobAnalysis`.
- Removed LLM ownership of `job_id`.

## `0.3.0`

- Added structured job analysis.
- Added evidence models.
- Added `JobAnalyzer`.
- Added analysis creation and retrieval endpoints.

## `0.2.0`

- Added job domain models.
- Added manual job ingestion.
- Added in-memory job storage.
- Added job retrieval endpoints.

## `0.1.0`

- Added FastAPI application foundation.
- Added health endpoint.
- Added Ollama connectivity.
- Added local `OllamaClient` abstraction.

---

# Current Development Status

```text
Phase 1  ██████████  Complete
Phase 2  ██████████  Complete
Phase 3  ██████████  Complete
Phase 4  ██████████  Complete
Phase 5  ██████████  Complete
Phase 6  ██████████  Complete
Phase 7  ░░░░░░░░░░  Next
```

The current stopping point is **Phase 6: Job-Specific POC Generator**.

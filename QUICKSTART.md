# Quickstart

> 10-minute path from `git clone` to a working local Agentic RAG platform.

## Prerequisites

- Docker Desktop with Compose v2
- Python 3.11+
- Node.js 20+
- `make`, `curl`, `jq`
- An OpenAI API key with $5+ credit
- A Hugging Face token (free)

## 1. Clone and configure

```bash
git clone <your-repo-url> agentic-rag-platform
cd agentic-rag-platform
cp .env.example .env
```

Edit `.env` and fill in:

```bash
OPENAI_API_KEY=sk-...
HF_TOKEN=hf_...
LANGFUSE_SECRET=...        # any random 32-char string
LANGFUSE_PUBLIC=...        # any random 32-char string
APP_SECRET_KEY=...         # any random 64-char string (REQUIRED, min 32 chars)
JWT_SECRET=...             # any random 64-char string (REQUIRED, min 32 chars)
DATABASE_URL=postgresql+asyncpg://rag:rag@postgres:5432/rag
```

Both `APP_SECRET_KEY` and `JWT_SECRET` are required by the API and worker services;
the stack will not start without them.

Generate random secrets with:

```bash
openssl rand -hex 32
```

## 2. Bring up the stack

```bash
make up          # postgres, api, web, worker, langfuse
make migrate     # apply database migrations
make seed        # load demo users, roles, departments
```

Verify health:

```bash
curl -s http://localhost:8000/health | jq
# {
#   "status": "ok",
#   "db": "ok",
#   "embedder": "ok",
#   "llm": "ok",
#   "version": "..."
# }
```

## 3. Ingest sample documents

Drop a few markdown or PDF files into `data/sources/local/`, then:

```bash
make ingest-local
```

Verify chunks were created:

```bash
docker compose exec postgres psql -U rag -d rag \
  -c "SELECT count(*) FROM document_chunks;"
```

## 4. Use the system

### Web UI

Open http://localhost:3000 and log in with:

- Email: `alice@demo.dev` (administrator)
- Password: `password123`

Ask a question. Try: "What is the remote work policy?"

### API directly

```bash
# Get a JWT
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@demo.dev","password":"password123"}' | jq -r .access_token)

# Query
curl -s -X POST http://localhost:8000/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is our remote work policy?"}' | jq
```

### View the trace

Open http://localhost:3001 (Langfuse UI, log in with the LANGFUSE_SECRET credentials) and find the most recent trace. You should see the full span tree: `rag.query` → `embed` → `retrieval.dense` → `retrieval.lexical` → `rerank` → `agent.planner` → `generate` → `validate_citations`.

## 5. Run evaluation

```bash
make eval
```

This runs the full golden dataset (~50–100 items) through all configured baselines and produces `evals/reports/comparison.md`.

For a fast smoke test (10 items, used in CI):

```bash
make eval-smoke
```

## 6. Run tests

```bash
make test          # unit + integration
make test-unit     # just unit
make test-security # RBAC + prompt injection
```

## 7. Stop everything

```bash
make down
```

To wipe the database and start over:

```bash
make db-reset
```

## Troubleshooting

| Symptom                                  | Fix                                                            |
| ---------------------------------------- | -------------------------------------------------------------- |
| `make up` fails on port conflict         | Edit `docker-compose.yml`, change `ports:` to non-conflicting  |
| Health check shows `embedder: fail`      | `docker compose logs api`, look for HF model download errors   |
| Health check shows `llm: fail`           | Check `OPENAI_API_KEY` in `.env`, check your billing           |
| `make migrate` fails                     | `docker compose restart postgres`, then retry                  |
| Ingestion succeeds but 0 chunks          | Verify `data/sources/local/` has files; check `docker compose logs worker` |
| Query returns "no relevant documents"    | Your corpus might not match the query; try the seed corpus     |
| Citations appear but text is `[1] [2]`   | Citation parser issue; check `docker compose logs api`         |
| Langfuse shows no traces                 | Verify `LANGFUSE_SECRET` matches in both `api` and `langfuse`  |

## Next steps

- Read [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md) to understand how each piece was built.
- Read [docs/architecture/](docs/architecture/) for the diagrams.
- Read [docs/decisions/](docs/decisions/) for the ADRs.
- Read [docs/operations/](docs/operations/) to operate the system in production.

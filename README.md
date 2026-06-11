# AgentZline — Bronze Tier MVP

> Hyper-Focused AI Media Buyer Engine for Pakistani E-Commerce & D2C Brands

## What It Does

AgentZline Bronze Tier is a **read-only Meta Ads monitoring system** that delivers daily bilingual (Roman Urdu / English) executive summaries directly to WhatsApp — no complex dashboards, no manual checking.

### Bronze Scope (This Repo)

| Feature | Status |
|---|---|
| Meta Ads read-only data ingestion | ✅ MVP |
| Daily WhatsApp executive report (bilingual) | ✅ MVP |
| Anomaly detection (CPA surges, ad fatigue) | ✅ MVP |
| ROAS Rescue alerts | ✅ MVP |
| Human-in-the-loop approval buttons | ✅ MVP |
| Multi-account / multi-tenant support | ✅ MVP |
| Audit logging (all actions tracked) | ✅ MVP |
| TikTok / CRM / Lead Gen / Auto-campaign | ❌ Future tiers |

## Tech Stack

- **Backend:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL + pgvector
- **AI:** Anthropic Claude (via LangGraph agents)
- **Messaging:** WhatsApp Business API
- **Ads API:** Meta Marketing Graph API (read-only)
- **Security:** Fernet-encrypted token vault, audit trails

## Quick Start

```bash
# 1. Install dependencies (uv auto-creates .venv)
uv sync --extra dev

# 2. Configure environment
cp .env.example .env
# Edit .env with your actual API keys and database URL

# 3. Run database migrations
alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload --port 8000
```

## Project Structure

```
agentzline/
├── app/
│   ├── core/          # Config, database, security, settings
│   ├── api/           # FastAPI routes (webhooks, health)
│   ├── agents/        # LangGraph agent definitions
│   ├── skills/        # Deterministic analysis functions
│   ├── models/        # SQLAlchemy ORM models
│   ├── schemas/       # Pydantic request/response schemas
│   └── utils/         # Helpers (formatting, crypto, etc.)
├── tests/             # pytest test suite
├── .claude/           # Claude Code settings & agents
├── CLAUDE.md          # Claude Code project rules
├── pyproject.toml
├── uv.lock
├── .env.example
└── README.md
```

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `FERNET_ENCRYPTION_KEY` | Token vault encryption key |
| `META_SYSTEM_USER_TOKEN` | Meta Graph API access |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp Business API token |
| `ANTHROPIC_API_KEY` | Claude API key |

## License

Proprietary — All rights reserved.

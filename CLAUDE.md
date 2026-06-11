# AgentZline — Claude Code Project Rules

## Scope Limitation (Bronze Tier)
- **Primary Stack**: FastAPI, PostgreSQL, LangGraph, Anthropic API, WhatsApp Business API
- **Absolute Restriction**: Do NOT add TikTok, CRM, Lead Gen, or autonomous write paths
- Focus 100% on Meta read-only metrics and WhatsApp report delivery

## Localization Standards
- All reporting messages must support Roman Urdu (`roman_urdu`) and English (`english`)
- Use Pakistan-centric defaults: PKR currency, Asia/Karachi timezone, COD tracking patterns
- Incorporate local market flags: Friday/Saturday surges, Ramadan/Eid windows

## Security Rules
- NEVER store API tokens in plaintext — always use `app.core.security.encrypt_token()`
- Budget ceiling in `ad_accounts.max_budget_ceiling_pkr` is a hard limit — no agent can override it
- All mutations require Human-In-The-Loop (HITL) approval via WhatsApp interactive buttons
- Every action must be logged to `agent_action_audit_logs`

## Code Style
- Python 3.11+ with type hints on all function signatures
- Pydantic v2 for all schemas and settings
- SQLAlchemy 2.0 async ORM (no raw SQL unless absolutely necessary)
- Use `loguru` for logging, not stdlib `logging`
- All API clients must be async (`httpx` or `asyncpg`)

## Testing
- Run tests: `uv run pytest tests/ -v`
- Every new skill function must have corresponding test coverage
- Test fixtures go in `tests/conftest.py`

## Database Migrations
- Use Alembic for all schema changes
- Generate: `uv run alembic revision --autogenerate -m "description"`
- Apply: `uv run alembic upgrade head`

## Package Manager
- Use **uv** for all dependency management — no pip, no requirements.txt
- Install: `uv sync --extra dev`
- Add dep: `uv add <package>` / `uv add --dev <package>`
- Run commands: `uv run <command>`

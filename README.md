# AgentZline ⚡

> **Autonomous AI Media Buyer & COD Reconciliation Engine for Meta Ads & E-Commerce**  
> *Production-grade Agentic Orchestration for Ad Pacing Defense, Cryptographic Human-in-the-Loop Mutations, and Cash-on-Delivery (COD) Real-Profit Reconciliation.*

[![CI / Test Suite](https://github.com/Moh-Tayyab/Agentzline/actions/workflows/ci.yml/badge.svg)](https://github.com/Moh-Tayyab/Agentzline/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20Orchestration-FF6F00.svg?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Meta Marketing API](https://img.shields.io/badge/Meta%20Graph%20API-v20.0-0081FB.svg?logo=meta&logoColor=white)](https://developers.facebook.com/docs/marketing-apis/)
[![WhatsApp Cloud API](https://img.shields.io/badge/WhatsApp%20Cloud-Interactive%20Buttons-25D366.svg?logo=whatsapp&logoColor=white)](https://business.whatsapp.com/)
[![Tests Passing](https://img.shields.io/badge/tests-85%2F85%20passed%20(100%25)-brightgreen.svg?logo=pytest&logoColor=white)](tests/)
[![Security](https://img.shields.io/badge/security-Fernet%20AES--128%20%2B%20HMAC--SHA256-orange.svg?logo=vault&logoColor=white)](app/core/security.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Executive Summary & The Problem Solved

In high-growth Direct-to-Consumer (D2C) e-commerce markets (particularly **Pakistan & MENA**), **80%+ of transactions occur via Cash-on-Delivery (COD)** with an industry-wide **20% to 35% Return-to-Origin (RTO)** rate.

### 🔴 The Media Buyer's Blind Spot
- **The Illusion:** Meta Ads Manager reports an apparent **4.2x ROAS** because pixels track gross orders booked at checkout.
- **The Financial Reality:** 30% of parcels are returned, courier companies charge double-sided logistics penalties (dispatch fee + return fee), and inventory sits locked in courier transit. By the time the merchant reconciles their bank account 15 days later, they discover the campaign was bleeding cash.
- **Human Latency:** Ad fatigue or CPM surges during intraday peak hours (14:00–18:00 PKT) burn significant budget before human media buyers notice.

### 🟢 The AgentZline Solution
**AgentZline** bridges the real-time gap between **Meta Ads Marketing API** and **Courier Delivery Logistics (PostEx, Trax, Leopards, Swyft)**. It tracks true **Pocket Net Margin** in real-time, alerts founders via executive **WhatsApp** reports (in natural English and Roman Urdu), and empowers instant one-tap campaign pause mutations backed by cryptographic security tokens.

---

## 🏗️ High-Level System Architecture

```mermaid
flowchart TD
    subgraph Data_Ingestion ["1. Real-Time Data Ingestion"]
        META[Meta Marketing API v20.0<br/>Ad Insights & Budgets]
        COURIERS[Courier Webhooks<br/>PostEx / Trax / Leopards / Swyft]
        VAULT[(Multi-Tenant Vault<br/>Fernet AES-128 Encrypted)]
    end

    subgraph Core_Engine ["2. AgentZline Processing Core"]
        NORM[Decimal Normalizer<br/>Currency: PKR / USD / AED]
        STATE[LangGraph Agent Graph<br/>BronzeAgentState Machine]
        PACING[Intraday Pacing Guardrails<br/>14:00 & 18:00 PKT Checks<br/>24h Alert Suppression]
        CACHE[(12h Budget Cache<br/>_BUDGET_CACHE)]
        PNL[True Campaign P&L Engine<br/>Revenue - COGS - Logistics - Spend]
    end

    subgraph Security_Engine ["3. Cryptographic Security Engine"]
        SECRET[Shared Webhook Secret<br/>Constant-Time HMAC]
        TOKEN_GEN[HMAC-SHA256 Action Tokens<br/>15-min TTL • Replay Protected]
        AUDIT[(AuditLog Trail<br/>Immutable Mutation Log)]
    end

    subgraph Action_Delivery ["4. Executive Delivery & Mutation"]
        WA[WhatsApp Cloud API<br/>Bilingual Executive Reports<br/>Roman Urdu & English]
        HITL[Interactive Quick-Reply Buttons<br/>🔴 Pause Ad | Keep Running]
        MUTATE[Meta Graph API Mutation<br/>Atomic status='PAUSED']
    end

    META --> NORM
    VAULT -.-> META
    COURIERS --> SECRET --> PNL
    NORM --> STATE
    STATE --> PACING
    STATE --> PNL
    PACING <--> CACHE
    PACING --> TOKEN_GEN
    PNL --> WA
    TOKEN_GEN --> WA
    WA --> HITL
    HITL --> TOKEN_GEN --> AUDIT --> MUTATE
```

---

## ✨ Key Technical Capabilities

### 1. 🚚 Gold Tier: Multi-Courier COD & "The Money View"
- **Unified Normalizer:** Ingests live lifecycle webhooks across Pakistani major couriers:
  - **PostEx** (`pe-status`), **Trax Logistics**, **Leopards Courier**, and **Swyft Logistics**.
- **Delivered vs. RTO Accounting:** Automatically charges delivery fees, reverse transit penalties, and product COGS against gross order value.
- **Blended Real-ROAS Engine:**
  $$\text{Net Profit} = \text{Delivered Cash} - \text{Delivered COGS} - \text{Courier Charges (Delivered + Returned)} - \text{Meta Ad Spend}$$
- **Real-Time Endpoint:** `GET /api/v1/orders/pnl?tenant_id=<id>` returns campaign-level net margins and delivery rate percentages.

### 2. 🔐 Silver Tier: Cryptographic HITL Mutation Engine
- **One-Tap WhatsApp Buttons:** Interactive messages with `[🔴 Pause Ad]` action links delivered directly to media buyers' WhatsApp.
- **HMAC-SHA256 Action Tokens:** Compact URL-safe tokens (~138 chars, well within WhatsApp's strict 140-char button payload limit) containing `tenant_id`, `campaign_id`, `ad_id`, timestamp, and signature.
- **Replay & Expiry Protection:** 15-minute expiration enforcement combined with cryptographic replay prevention against the PostgreSQL `AuditLog` table.
- **Atomic Meta Mutation:** Verified callback securely triggers `status="PAUSED"` on Meta Marketing API without exposing credentials.

### 3. ⏱️ Intraday Pacing Defense & Budget Caching
- **Deterministic Bleed Rules:** Evaluates campaigns at scheduled checkpoints (14:00 & 18:00 PKT) for high-spend zero-conversion anomalies and low CTR fatigue.
- **In-Memory Budget Cache (`_BUDGET_CACHE`):** 12-hour TTL cache prevents aggressive polling from depleting Meta Graph API rate limits.
- **24-Hour Alert Suppression:** Prevents alert fatigue by ensuring a campaign receives at most one intraday pacing notification within any 24-hour cycle.

### 4. 💬 Bilingual Executive WhatsApp Reporting
- Executive summaries delivered at 09:00 PKT daily, formatted in clean **English** or localized **Roman Urdu**:
  ```text
  📊 AgentZline Daily Summary — 2026-10-12
  Account: Khaadi Official (PKR)
  
  Total Spend: 45,200 PKR
  Gross ROAS: 3.82x | CTR: 2.14%
  
  📦 Real Net Profit & COD Reconciliation:
  • Booked Orders: 120 | Delivered: 96 | Returned (RTO): 24
  • Delivery Rate: 80.0%
  • Delivered Cash: 384,000 PKR
  • Logistics & Return Fees: 28,800 PKR
  • Net Pocket Profit: 168,000 PKR
  • True Blended ROAS: 3.72x
  ```

### 5. 🛡️ Enterprise-Grade Security & Vault Architecture
- **Fernet AES-128 Encryption:** All Meta System User Tokens and WhatsApp API secrets are encrypted at rest with zero plaintext leakage.
- **Token Expiry Watchdog:** Continuous background scheduler checks token freshness and fires automated warnings 7 days and 24 hours prior to expiration.
- **Webhook Shared-Secret Verification:** Timing-attack resistant HMAC comparison (`hmac.compare_digest`) on courier webhooks.
- **Strict CORS Origin Whitelisting:** Prevents credential leakage across origins.

---

## 📂 Project Structure

```
Agentzline/
├── .github/
│   ├── workflows/ci.yml         # Automated GitHub Actions test runner
│   ├── pull_request_template.md # Standardized PR template
│   └── ISSUE_TEMPLATE/          # Bug report & feature templates
├── alembic/                     # Database migrations (PostgreSQL)
│   └── versions/                # Versioned schema revisions (UUIDs, JSONB, Orders)
├── app/
│   ├── agents/                  # LangGraph orchestrator & state machine
│   │   ├── graph.py             # Agent workflow definition
│   │   └── state.py             # BronzeAgentState type definitions
│   ├── api/                     # REST API endpoints (FastAPI)
│   │   ├── endpoints/
│   │   │   ├── courier_webhook.py # Multi-courier webhook receiver & validator
│   │   │   ├── credentials.py   # Encrypted token vault CRUD
│   │   │   ├── hitl_actions.py  # Signed token verification & ad pause mutation
│   │   │   ├── meta_accounts.py # Ad account management & sync
│   │   │   ├── orders.py        # Orders, COGS, and Campaign P&L endpoints
│   │   │   └── tenants.py       # Multi-tenant workspace management
│   ├── core/                    # Core system infrastructure
│   │   ├── config.py            # Pydantic Settings with env parsing
│   │   ├── database.py          # Async SQLAlchemy engine & session maker
│   │   └── security.py          # Fernet vault, HMAC action tokens, and hashing
│   ├── models/                  # SQLAlchemy declarative ORM models
│   │   ├── audit_log.py         # Mutation history & replay defense
│   │   ├── credential.py        # Encrypted credentials vault model
│   │   ├── order.py             # Orders and CourierEvents tracking
│   │   ├── product_cost.py      # SKU product cost & COGS catalog
│   │   └── tenant.py            # Tenant isolation definitions
│   ├── schemas/                 # Pydantic v2 validation models
│   └── skills/                  # Pure, deterministic analytical functions
│       ├── bilingual_report.py  # WhatsApp report generator (Roman Urdu / English)
│       ├── campaign_pnl.py      # Blended real-ROAS & margin aggregator
│       ├── courier_normalizer.py# PostEx/Trax/Leopards/Swyft payload parsers
│       ├── intraday_pacing.py   # 14:00/18:00 PKT bleed & anomaly detector
│       └── meta_normalizer.py   # Decimal currency & ad insight normalizer
├── tests/                       # Complete pytest test suite (85 tests, 100% pass)
├── pyproject.toml               # Modern packaging configuration (uv/hatchling)
├── CONTRIBUTING.md              # Engineering contribution standards
├── LICENSE                      # MIT Open Source License
└── README.md
```

---

## ⚡ API Quick Reference

| Method | Endpoint | Description | Auth / Security |
|---|---|---|---|
| `POST` | `/api/v1/tenants` | Provision a new brand workspace | API Key / Bearer |
| `POST` | `/api/v1/credentials` | Store encrypted Meta / WhatsApp tokens | Fernet AES-128 |
| `POST` | `/api/v1/meta/accounts` | Register & link Meta Ad Accounts | Tenant Isolated |
| `POST` | `/api/v1/orders` | Ingest store orders with SKU & COGS | Tenant Isolated |
| `GET` | `/api/v1/orders/pnl` | **The Money View** (True P&L + Courier ROAS) | Tenant Isolated |
| `POST` | `/api/v1/courier/webhook/postex` | PostEx delivery status webhook | `COURIER_WEBHOOK_SECRET` |
| `POST` | `/api/v1/courier/webhook/trax` | Trax Logistics status webhook | `COURIER_WEBHOOK_SECRET` |
| `POST` | `/api/v1/courier/webhook/leopards`| Leopards Courier status webhook | `COURIER_WEBHOOK_SECRET` |
| `POST` | `/api/v1/courier/webhook/swyft` | Swyft Logistics status webhook | `COURIER_WEBHOOK_SECRET` |
| `POST` | `/api/v1/actions/pause` | Execute one-tap ad pause mutation | HMAC-SHA256 Token (15m) |
| `GET` | `/health` | Liveness & database connection probe | Public |

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.11+** or **3.12+**
- **uv** (ultra-fast Python package installer):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **PostgreSQL 15+** (or SQLite for local test runs)

### Installation & Local Run

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Moh-Tayyab/Agentzline.git
   cd Agentzline
   ```

2. **Sync dependencies:**
   ```bash
   uv sync --extra dev
   ```

3. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Generate your encryption key:
   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. **Run Database Migrations:**
   ```bash
   uv run alembic upgrade head
   ```

5. **Start Development Server:**
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```
   Interactive Swagger docs available at: `http://localhost:8000/docs`

---

## 🧪 Testing & Verification

The test suite runs with in-memory SQLite isolation and mocked external network calls, executing **85 tests in under 3.5 seconds**:

```bash
uv run pytest tests/ -v
```

```text
============================== test session starts ==============================
collected 85 items

tests/test_agent_graph.py ........                                        [  9%]
tests/test_bilingual_report.py .....                                      [ 15%]
tests/test_credentials_api.py ......                                      [ 22%]
tests/test_health.py ..                                                   [ 24%]
tests/test_hitl_mutation.py .........                                     [ 35%]
tests/test_intraday_pacing.py ...........                                 [ 48%]
tests/test_meta_accounts_api.py .......                                   [ 56%]
tests/test_meta_ads_analysis.py .........                                 [ 67%]
tests/test_meta_normalizer.py ...                                         [ 70%]
tests/test_orders_and_courier.py ...............                          [ 88%]
tests/test_security.py ....                                               [ 92%]
tests/test_tenants_api.py ......                                          [100%]

========================= 85 passed, 1 warning in 2.69s =========================
```

---

## 👨‍💻 Author & Engineering Highlights

Engineered by **Muhammad Tayyab**  
*AI Systems & Backend Software Engineer*

- **GitHub:** [@Moh-Tayyab](https://github.com/Moh-Tayyab)
- **Specialization:** Production Agentic AI (LangGraph, FastAPI), Scalable Async Python, Cryptographic Security & Financial Reconciliation Systems.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

# Contributing to AgentZline

Thank you for your interest in contributing to **AgentZline**! We welcome contributions from developers, media buyers, and e-commerce engineers.

---

## 🛠️ Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Moh-Tayyab/Agentzline.git
   cd Agentzline
   ```

2. **Install `uv` (recommended package manager):**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install dependencies and activate environment:**
   ```bash
   uv sync --extra dev
   source .venv/bin/activate
   ```

4. **Environment Setup:**
   ```bash
   cp .env.example .env
   # Update variables as necessary for local development
   ```

---

## 🧪 Testing Guidelines

AgentZline prioritizes rock-solid test coverage and deterministic execution:
- Always run the test suite before submitting a PR:
  ```bash
  uv run pytest tests/ -v
  ```
- All tests must pass cleanly in under **5 seconds** using in-memory databases and mocked third-party integrations (Meta Graph API, WhatsApp Cloud API, Courier Webhooks).

---

## 🔀 Git Branching Strategy

We follow a clean, structured workflow:
- `main`: Production-ready, stable releases.
- `develop`: Ongoing development and feature staging.
- `feature/<feature-name>`: Scoped feature development branches.
- `fix/<bug-name>`: Hotfix and bug fixes.

---

## 🔒 Security Standards

1. **Zero Plaintext Secrets:** Never store tokens or private keys in plaintext. All credentials must use the Fernet AES-128 vault.
2. **Action Token Verification:** All interactive WhatsApp actions require HMAC-SHA256 signatures with 15-minute TTL.
3. **Courier Authentications:** External webhook endpoints require shared-secret verification.

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).

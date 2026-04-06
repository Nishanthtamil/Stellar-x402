# Stellar x402-utils + Web3 Agent Registry (PRD v4)
### Pay-Per-Execution Agent Infrastructure (OpenClaw + 8004 Compatible)

![Advanced Dashboard](https://github.com/nirmalplays/Stellar-x402/raw/main/docs/dashboard_preview.png) *Visualizing real-time agent execution and blockchain finality.*

---

## 1. Problem Statement (Extended)

Modern APIs and compute services still rely on:
- centralized billing (Stripe)
- API keys
- authentication systems

For AI agents, the problem is worse:
- no native identity
- no trust layer
- no payment interoperability
- no standardized discovery mechanism

There is no unified infrastructure where:
- agents can discover other agents
- verify identity
- pay autonomously
- execute tasks trustlessly

---

## 2. Solution Overview

Stellar x402-utils v4 evolves into:

> A Web3-native execution agent + decentralized agent registry

It combines:

- **x402 protocol** → payment = authorization  
- **8004 protocol** → agent identity + registration  
- **OpenClaw model** → skills + execution agents  
- **A2A protocol** → agent-to-agent communication  

---

## 3. Core Concept

Any agent can:

1. **Discover** your agent on-chain  
2. **Verify** identity + reputation  
3. **Send** a task  
4. **Pay** via Stellar  
5. **Receive** execution + validation  
6. **Verify** result cryptographically  

---

## 4. System Architecture

```text
                ┌────────────────────────────┐
                │   Web3 Agent Registry      │
                │  (8004 Identity Layer)     │
                └──────────┬─────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     │                     │                     │
  Agent A               Agent B               Agent C
    ▼                      ▼                     ▼
┌──────────────────────────────────────────────┐
│        EXECUTOR AGENT (CORE SYSTEM)          │
│----------------------------------------------│
│ x402 Payment Layer (Stellar)                 │
│ Docker Execution Engine                      │
│ Validator Agent (AI + Rules)                 │
│ Result Signing (cryptographic proof)         │
│ OpenClaw Skill Interface                     │
└──────────────────────────────────────────────┘
```

---

## 5. Web3 Agent Registry Layer

### 5.1 On-chain Identity

Each agent has:
- unique agent_id  
- owner address  
- metadata URI (IPFS)  
- reputation score  
- active status  

```rust
pub struct Agent {
    pub owner: Address,
    pub metadata_cid: String,
    pub reputation: i64,
    pub active: bool,
}
```

---

## 6. Project Setup & Quickstart

### Prerequisites
- **Python 3.11+**
- **Docker Desktop**
- **Rust & Stellar CLI** (for contract work)

### Recommended run order

1. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

2. **Setup Accounts**:
   ```powershell
   python scripts/setup_accounts.py
   ```

3. **Launch Advanced Dashboard**:
   ```powershell
   python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```
   *The dashboard will automatically open at `http://127.0.0.1:8000`*

4. **Explore Agent Vault**:
   Open `http://127.0.0.1:8000` and choose **Agent Vault** in the sidebar for the pipeline view and on-chain ledger.

### Run with Docker Compose (executor uses real Docker)

The **`api`** service mounts the **host Docker socket** so job containers run on your machine’s Docker Engine (no simulation).

1. Copy **`.env.example`** → **`.env`** and set keys (or keep your existing `.env`).
2. Optionally set **`PUBLIC_BASE_URL=http://localhost:8000`** in `.env` so discovery URLs are correct from outside the container.
3. From the repo root:
   ```powershell
   docker compose up --build
   ```
4. Open **http://localhost:8000** (the app does not auto-open a browser inside the container).

**Requirements:** Docker Desktop (Windows/macOS) or Linux Docker with permission to use `/var/run/docker.sock`. Without a working socket mount, runs will fail fast with a Docker reachability error unless you set **`ALLOW_DOCKER_SIMULATION=true`** (dev only).

**Docker Desktop:** The project is named **`stellar-x402`**. Expand it to see **`stellar-x402-api`** (image `stellar-x402-api:local`, port **8000**) and **redis**. When you **Launch process**, short-lived containers from image **`python:3.11-slim`** (etc.) are created on the host and **removed when the job finishes**—so they may not appear as “running” for long. To keep them for inspection, set **`DOCKER_KEEP_CONTAINERS=true`** in `.env` (**dev only**); they are labeled **`stellar-x402.executor-job=true`**.

### Discovery & production URL

- **`GET /api/discovery`** — Loads `agent_metadata.json` and, if set, rewrites `endpoint` / adds URLs using **`PUBLIC_BASE_URL`** (no trailing slash). Also includes an **`x402`** block (amount, destination, `prepare_unsigned_transaction` URL).
- **`GET /api/discovery/resolved?agent_id=agent_402`** — Adds the parsed **on-chain** registry row (`owner`, `metadata_cid`, `reputation`, `active`) and fetches JSON from **IPFS** when a CID is present (`IPFS_GATEWAY` defaults to `https://ipfs.io`).

### External x402 payer (any wallet)

The dashboard can still use **`POST /api/pay`** (deployer-funded demo). For a **real** payer:

1. **`POST /api/x402/prepare-payment`** with body `{"source_public_key": "G..."}` (account that will sign).
2. Sign **`transaction_xdr`** and submit to Horizon (e.g. Freighter, Albedo, or `stellar-cli`).
3. Call **`POST /execute/stream`** with header **`X-Stellar-Payment-Tx`** set to the submitted transaction hash.

Verification only requires a successful native payment **≥ 0.05 XLM** to **`EXECUTOR_PUBLIC_KEY`** (payer can be any account).

### Pin `agent_metadata.json` to IPFS (optional)

1. Create a JWT at [Pinata](https://app.pinata.cloud/) and set **`PINATA_JWT`** in `.env`.
2. Run:
   ```powershell
   python scripts/publish_agent_metadata_ipfs.py
   ```
3. Use the printed **CID** as `metadata_cid` when registering the agent on the Soroban registry.

---

## 7. New: Advanced Visualization Features

The v4 update introduces a sophisticated observability layer for agent operations:

### 7.1 Real-Time Execution Console
- **Glassmorphism UI**: A professional dark-mode dashboard for configuring and launching sandboxed jobs.
- **Live TX Feed**: Instantly see authorization transactions (fees) as they occur on the Stellar network.
- **Compact Terminal**: Real-time streaming of Docker logs via Server-Sent Events (SSE).

### 7.2 Agent Vault & Virtual Flow
- **Event-Driven Lifecycle**: A 4-stage visual flow (**Auth → Registry → Execution → Finality**) that activates only when a job is running.
- **State Synchronization**: The Vault page syncs with the backend every second to show exactly which stage the agent is in.
- **Action Ledger**: A persistent feed of all wallet activities, detecting costs and authorization events.

---

## 8. What's Inside

| Piece | Role |
|--------|------|
| `api/static/` | **Advanced Dashboard** & **Agent Vault** (New UI) |
| `api/main.py` | FastAPI server with real-time state synchronization |
| `api/routers/x402_prep.py` | **POST /api/x402/prepare-payment** (unsigned XDR for any payer) |
| `api/services/discovery_builder.py` | **GET /api/discovery** + IPFS helpers for **/api/discovery/resolved** |
| `api/services/soroban_agent_parse.py` | Parse on-chain `Agent` struct from Soroban simulation |
| `contracts/registry/` | Soroban smart contract for agent registration |
| `scripts/` | Setup, balances, **publish_agent_metadata_ipfs.py** (Pinata) |
| `tests/` | Comprehensive test suite for Docker security and API |

---

## 9. Final System Definition

> A Web3-native execution agent registered on-chain, discoverable by other agents, paid via Stellar, and returning cryptographically verified compute results.

---

## 10. One-Line Pitch

> “An OpenClaw-compatible, 8004-registered execution agent that lets any AI agent discover, pay, execute tasks, and verify results — trustlessly.”

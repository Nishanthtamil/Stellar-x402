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
| `contracts/registry/` | Soroban smart contract for agent registration |
| `scripts/` | Helper scripts for account setup and balance checks |
| `tests/` | Comprehensive test suite for Docker security and API |

---

## 9. Final System Definition

> A Web3-native execution agent registered on-chain, discoverable by other agents, paid via Stellar, and returning cryptographically verified compute results.

---

## 10. One-Line Pitch

> “An OpenClaw-compatible, 8004-registered execution agent that lets any AI agent discover, pay, execute tasks, and verify results — trustlessly.”

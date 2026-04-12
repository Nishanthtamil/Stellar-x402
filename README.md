# Stellar x402 Executor

> A Web3-native execution agent — pay per job in USDC via x402, verify identity on-chain, run sandboxed Docker tasks, get cryptographically signed results.

[![CI](https://github.com/nirmalplays/Stellar-x402/actions/workflows/ci.yml/badge.svg)](https://github.com/nirmalplays/Stellar-x402/actions)

---

## What This Is

A pay-per-execution agent infrastructure built on Stellar. Any AI agent or HTTP client can:

1. **Discover** your agent via `/.well-known/x402` or `/api/discovery`
2. **Pay** in USDC using the x402 protocol (or legacy XLM)
3. **Execute** a sandboxed Docker job
4. **Receive** a cryptographically signed, validated result

Built for the agentic economy — no API keys, no centralized billing, no trust assumptions.

---

## Architecture

```
Any Agent / Client
        │
        ▼
  POST /execute/stream   (SSE)
  POST /execute          (JSON, non-SSE clients)
        │
        ├── Step 1: Payment verification
        │     ├── x402 v2: USDC via facilitator (primary)
        │     └── Legacy: 0.05 XLM via Horizon (fallback)
        │
        ├── Step 2: Registry check
        │     └── Soroban smart contract on Stellar
        │
        ├── Step 3: Docker execution
        │     └── Sandboxed container (no network, 256MB RAM)
        │
        └── Step 4: Signed result
              └── Ed25519 signature + reputation update
```

---

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/nirmalplays/Stellar-x402.git
cd Stellar-x402
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Variable | Description |
|---|---|
| `DEPLOYER_PUBLIC_KEY` / `DEPLOYER_SECRET` | Account that owns the registry contract |
| `EXECUTOR_PUBLIC_KEY` / `EXECUTOR_SECRET` | Account that receives payments |
| `REGISTRY_CONTRACT_ID` | Deployed Soroban registry contract ID |
| `PUBLIC_BASE_URL` | ⚠️ Your public URL — required for discovery to work |
| `X402_FACILITATOR_URL` | Facilitator endpoint (default: `https://x402.org/facilitator`) |
| `X402_PRICE` | Price per job in USDC (default: `0.01`) |

Generate and fund testnet accounts at: https://lab.stellar.org

> **Note:** If `REGISTRY_CONTRACT_ID` is not set, all jobs are refused by default.
> For local dev without a deployed contract, set `REGISTRY_BYPASS_DEV=true`.

### 3. Run

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Dashboard opens automatically at http://127.0.0.1:8000

### 4. Run with Docker Compose

```bash
docker compose up --build
```

Open http://localhost:8000

---

## Payment Methods

### Primary: x402 v2 (USDC via facilitator)

This is the standard x402 protocol. The client pays USDC and retries with the payment proof.

```
POST /execute/stream
Header: X-Payment: <PaymentPayload JSON>
```

Two facilitator options:
- **Coinbase** (testnet, no key needed): `https://x402.org/facilitator`
- **OpenZeppelin** (testnet + mainnet, API key required): `https://channels.openzeppelin.com/x402/testnet`

Compatible wallets: Freighter (browser extension), Albedo, Hana, HOT, Klever, OneKey.

### Fallback: Legacy XLM

Send 0.05 native XLM directly to `EXECUTOR_PUBLIC_KEY` and pass the transaction hash:

```
POST /execute/stream
Header: X-Stellar-Payment-Tx: <transaction_hash>
```

Prepare an unsigned transaction first:
```bash
POST /api/x402/prepare-payment
Body: {"source_public_key": "G..."}
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/execute/stream` | SSE streaming execution (primary) |
| `POST` | `/execute` | Single JSON response (non-SSE clients) |
| `GET` | `/.well-known/x402` | Standard x402 discovery |
| `GET` | `/.well-known/agent-card.json` | **A2A v1** Agent Card ([spec](https://a2a-protocol.org/latest/specification/)) |
| `GET` | `/.well-known/agent-registration.json` | **EIP-8004** `registration-v1` ([ERC-8004](https://eips.ethereum.org/EIPS/eip-8004)) — Stellar Soroban identity |
| `POST` | `/message:send` | **A2A** HTTP+JSON `SendMessage` (same payment headers as `/execute`) |
| `POST` | `/a2a/jsonrpc` | **A2A** JSON-RPC (`SendMessage`, `GetTask`, `ListTasks`, `CancelTask`) |
| `GET` | `/tasks/{id}` · `GET` `/tasks` | **A2A** task fetch / list (in-memory; populated after `SendMessage`) |
| `GET` | `/api/discovery` | Agent card + x402 hints |
| `GET` | `/api/discovery/resolved` | Merged on-chain + IPFS metadata |
| `GET` | `/api/vault` | Wallet balances + transaction history |
| `GET` | `/api/activity` | Live event feed |
| `POST` | `/api/pay` | Demo: auto-send 0.05 XLM (dev only) |

**EIP-8004 on Stellar:** `agentRegistry` uses `stellar:{NETWORK}:{REGISTRY_CONTRACT_ID}` (not `eip155:`). `agentId` in `registrations` is the **Soroban string** agent id (e.g. `agent_402`), not an ERC-721 `tokenId`.

**Honest discovery:** `/.well-known/agent-card.json` and `/.well-known/agent-registration.json` return **503** if `PUBLIC_BASE_URL` is unset (no invented host) or, for registration, if `REGISTRY_CONTRACT_ID` is unset (no empty `registrations`). Set both in `.env` for real deployments. `x402.prepare_unsigned_transaction` in `/api/discovery` is **null** until `PUBLIC_BASE_URL` is set.

**A2A scope:** Agent Card + `SendMessage` / `GetTask` / `ListTasks` / `CancelTask` over HTTP+JSON and JSON-RPC. Tasks are stored **in memory** only when the run produces a real `job_id` or an **auth-required** payment state (no fake “failed” task ids for unknown stream errors). Streaming (`SendStreamingMessage`), push notifications, and in-flight **cancel** are not implemented — use `POST /execute/stream` for native SSE.

### Example request

```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -H "X-Stellar-Payment-Tx: YOUR_TX_HASH" \
  -d '{
    "agent_id": "agent_402",
    "task": "run python",
    "image": "python:3.11-slim",
    "cmd": "python -c \"print(2+2)\""
  }'
```

### Example response

```json
{
  "job_id": "abc-123",
  "status": "completed",
  "output": "4",
  "verified": true,
  "signature": "...",
  "log": ["..."]
}
```

---

## On-Chain Registry

The Soroban registry contract stores:

```rust
pub struct Agent {
    pub owner: Address,
    pub metadata_cid: String,  // IPFS CID
    pub reputation: i64,
    pub active: bool,
}
```

Deploy the contract:

```bash
cd contracts/registry
stellar contract deploy --wasm target/wasm32-unknown-unknown/release/registry.wasm --network testnet
```

Register your agent:

```bash
python scripts/registry_client.py
```

Publish metadata to IPFS (optional):

```bash
# Set PINATA_JWT in .env first
python scripts/publish_agent_metadata_ipfs.py
```

---

## Advanced Features

### 1. Secrets (Environment Variables)
Pass sensitive data (like API keys) to the container. They are available as environment variables but stripped from the final signed result.

```json
{
  "cmd": "python -c 'import os; print(os.getenv(\"MY_KEY\"))'",
  "secrets": {"MY_KEY": "sk-123..."}
}
```

### 2. Browser Automation (Playwright)
Run headless browser tasks using Playwright. Requires `network_enabled: true` and the `mcr.microsoft.com/playwright/python:v1.45.0-jammy` image.

```json
{
  "image": "mcr.microsoft.com/playwright/python:v1.45.0-jammy",
  "cmd": "python3 script.py",
  "network_enabled": true
}
```

---

## Security

Docker jobs run in strict isolation:

- **Network:** Disabled by default. Can be enabled via `network_enabled: true`.
- **Memory:** 256MB limit (increased to 512MB for browser/network tasks).
- **CPU:** 0.5 CPU limit.
- **Process:** 64 process limit.
- **Filesystem:** Read-only, with `tmpfs` mounts for `/tmp` (256MB), `/var/tmp` (64MB), and `/root/.cache` (256MB).
- **Privileges:** No new privileges.

---

## Project Structure

```
api/
├── main.py                     # FastAPI app, discovery, vault
├── routers/
│   ├── execute.py              # Payment → registry → Docker → sign
│   └── x402_prep.py            # Prepare unsigned XDR for any payer
├── services/
│   ├── docker_runner.py        # Sandboxed Docker execution
│   ├── registry_client.py      # Soroban contract calls
│   ├── x402_facilitator_service.py  # USDC payment via facilitator
│   ├── validator.py            # Output validation (AI + rules)
│   └── signer.py               # Ed25519 result signing
├── static/                     # Dashboard UI
contracts/registry/             # Soroban smart contract (Rust)
scripts/                        # Setup, registry, IPFS publish
tests/                          # Test suite
```

---

## One-Line Pitch

> An x402-native execution agent that lets any AI agent discover, pay in USDC, run sandboxed Docker tasks, and receive cryptographically verified results — trustlessly on Stellar.

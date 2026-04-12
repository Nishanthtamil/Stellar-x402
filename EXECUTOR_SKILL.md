# EXECUTOR_SKILL.md

## name
docker_execution

## description
Execute containerized tasks with payment using the x402 and 8004 protocols on the Stellar network.

## input
- **image**: The Docker image name to run (e.g., `python:3.11-slim`).
- **cmd**: The command entrypoint to execute inside the container.
- **task**: (Optional) A description of the task for AI-based validation.
- **input**: (Optional) Key-value pairs of requirements for validation (e.g., `expected_substring`).
- **agent_id**: (Required) The 8004-registered agent ID for verification.

## discovery

- **EIP-8004** registration file: `GET /.well-known/agent-registration.json` (type `registration-v1`; Stellar uses `stellar:{NETWORK}:{REGISTRY_CONTRACT_ID}` as `agentRegistry` and the Soroban string `agent_id` in `registrations`). Returns **503** if `PUBLIC_BASE_URL` or `REGISTRY_CONTRACT_ID` is missing (nothing is fabricated).
- **A2A** Agent Card: `GET /.well-known/agent-card.json` — **503** if `PUBLIC_BASE_URL` is unset (no implicit localhost).
- **A2A** task RPC: `POST /message:send` (HTTP+JSON) or `POST /a2a/jsonrpc` with method `SendMessage`; include payment headers `X-Payment` / `X-Stellar-Payment-Tx` like `/execute/stream`.

## output
- **job_id**: Unique identifier for the job.
- **status**: Final status (`completed`, `failed`, `timeout`).
- **output**: Combined stdout/stderr of the process.
- **verified**: Boolean indicating if the output passed validation.
- **signature**: Ed25519 signature of the result.
- **pubkey**: The public key of the signer.
- **validation_strategy**: The strategy used (`deterministic`, `rule_based`, `ai_based`).
- **validation_reason**: Human-readable reason for the validation result.
- **signed_payload**: The raw data that was signed.
- **timestamp**: ISO timestamp of completion.

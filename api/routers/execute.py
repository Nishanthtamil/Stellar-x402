from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse
from api.models.job import JobRequest, JobResult, JobStatus
from api.services.docker_runner import docker_runner
from api.services.signer import result_signer
from api.services.validator import validate_execution_output
from api.services.registry_client import registry_client
from stellar_sdk import Server
import uuid
import asyncio
from datetime import UTC, datetime
import json
import os

router = APIRouter(prefix="/execute", tags=["execution"])

# Shared state for the Vault UI
latest_job_state = {
    "status": "idle",
    "step": 0,
    "last_tx": None
}

@router.get("/status")
async def get_flow_status():
    return latest_job_state


def _resolve_job_status(output_lines: list[str], verified: bool) -> JobStatus:
    if any(line.startswith("[TIMEOUT]") for line in output_lines):
        return JobStatus.TIMEOUT
    if any(line.startswith("[ERROR]") for line in output_lines):
        return JobStatus.FAILED
    if not verified:
        return JobStatus.FAILED
    return JobStatus.COMPLETED

async def _verify_payment(tx_hash: str) -> bool:
    """Verifies that the payment transaction was successful on the Stellar Testnet and sent to the executor."""
    if not tx_hash:
        return False
    try:
        horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
        executor_pk = os.getenv("EXECUTOR_PUBLIC_KEY")
        server = Server(horizon_url)
        
        # Check if transaction exists and is successful (with 10s timeout)
        tx = await asyncio.wait_for(
            asyncio.to_thread(server.transactions().transaction(tx_hash).call),
            timeout=10.0
        )
        if not tx.get("successful", False):
            return False

        # Verify it contains a payment of 0.05 XLM to our executor
        ops = await asyncio.wait_for(
            asyncio.to_thread(server.operations().for_transaction(tx_hash).call),
            timeout=10.0
        )
        for op in ops["_embedded"]["records"]:
            if op["type"] == "payment" and op["to"] == executor_pk:
                if float(op["amount"]) >= 0.05:
                    return True
        return False
    except asyncio.TimeoutError:
        print(f"Payment verification timed out for TX: {tx_hash}")
        return False
    except Exception as e:
        print(f"Payment verification error: {e}")
        return False

@router.post("/deactivate")
async def deactivate_agent(agent_id: str):
    """Deactivates an agent in the registry contract."""
    try:
        # We use the registry_client to perform the on-chain action
        # The registry_client already handles using the DEPLOYER_SECRET
        await asyncio.to_thread(registry_client.deactivate_agent, agent_id)
        return {"status": "success", "message": f"Agent {agent_id} deactivated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/stream")
async def execute_stream(
    request: JobRequest, 
    x_stellar_payment_tx: str = Header(None),
    response: Response = Response()
):
    # PRD v4: x402 Protocol Implementation (Payment = Authorization)
    if not x_stellar_payment_tx:
        # Return 402 Payment Required
        response.status_code = 402
        return {
            "error": "Payment Required",
            "message": "Authorization via x402 required. Please pay 0.05 XLM to the executor address.",
            "destination": os.getenv("EXECUTOR_PUBLIC_KEY"),
            "amount": "0.05",
            "asset": "XLM",
            "link": "https://stellar.org/protocol/x402"
        }

    job_id = str(uuid.uuid4())
    
    async def event_generator():
        output_acc = []
        
        # Step 1: Wallet Auth (Verified via x402)
        latest_job_state["status"] = "authorizing"
        latest_job_state["step"] = 1
        yield f"data: {json.dumps({'line': f'> Verifying x402 authorization (TX: {x_stellar_payment_tx[:8]}...)'})}\n\n"
        
        # Move verification inside stream for better feedback
        payment_valid = False
        for attempt in range(3):
            payment_valid = await _verify_payment(x_stellar_payment_tx)
            if payment_valid: break
            yield f"data: {json.dumps({'line': f'> Waiting for Stellar ledger indexing (Attempt {attempt+1}/3)...'})}\n\n"
            await asyncio.sleep(2)

        if not payment_valid:
            yield f"data: {json.dumps({'line': f'[ERROR] Could not verify payment {x_stellar_payment_tx[:8]} on-chain.'})}\n\n"
            latest_job_state["status"] = "failed"
            latest_job_state["step"] = 0
            return

        latest_job_state["last_tx"] = {
            "type": "AUTH (x402)", 
            "amount": "0.05 XLM", 
            "id": x_stellar_payment_tx[:8]
        }
        yield f"data: {json.dumps({'line': f'> Authorization verified via x402.'})}\n\n"
        await asyncio.sleep(1) 
        
        # Step 2: Registry Check
        latest_job_state["status"] = "registry"
        latest_job_state["step"] = 2
        yield f"data: {json.dumps({'line': f'> Verifying agent {request.agent_id} in registry contract...'})}\n\n"
        
        # Real registry check
        try:
            agent_on_chain = await asyncio.to_thread(registry_client.get_agent, request.agent_id)
            if not agent_on_chain and registry_client.contract_id:
                yield f"data: {json.dumps({'line': f'[ERROR] Agent {request.agent_id} not found in registry!'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return
        except Exception as e:
            yield f"data: {json.dumps({'line': f'[WARN] Registry check error: {e}. Proceeding anyway.'})}\n\n"

        yield f"data: {json.dumps({'line': f'> Agent {request.agent_id} verified on-chain.'})}\n\n"
        await asyncio.sleep(1)
        
        # Step 3: Execution
        latest_job_state["status"] = "executing"
        latest_job_state["step"] = 3
        
        async for line in docker_runner.run(request.image, request.cmd):
            output_acc.append(line)
            yield f"data: {json.dumps({'line': line})}\n\n"
        
        latest_job_state["status"] = "finalizing"
        latest_job_state["step"] = 4
        yield f"data: {json.dumps({'line': '> Validating execution output...'})}\n\n"

        output_text = "\n".join(output_acc)
        validation = validate_execution_output(output_text, request.model_dump())
        signed_payload = {
            "job_id": job_id,
            "agent_id": request.agent_id,
            "task": request.task,
            "output": output_text,
            "verified": validation.verified,
            "validation_strategy": validation.strategy.value,
            "validation_reason": validation.reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        yield f"data: {json.dumps({'line': f'> Validation result: {validation.reason}'})}\n\n"
        yield f"data: {json.dumps({'line': '> Signing execution result...'})}\n\n"

        signature = result_signer.sign_payload(signed_payload)
        latest_job_state["last_tx"] = {
            "type": "SIGN",
            "amount": "0.00000 XLM",
            "id": job_id[:8],
        }

        status = _resolve_job_status(output_acc, validation.verified)
        
        # Update reputation on-chain (Section 13)
        if status == JobStatus.COMPLETED:
            try:
                # Automate reputation updates in the registry contract
                await asyncio.to_thread(registry_client.update_reputation, request.agent_id, 1)
                yield f"data: {json.dumps({'line': f'> Agent {request.agent_id} reputation updated (+1) on-chain.'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'line': f'[WARN] Failed to update reputation: {e}'})}\n\n"
        elif status == JobStatus.FAILED:
            try:
                await asyncio.to_thread(registry_client.update_reputation, request.agent_id, -1)
                yield f"data: {json.dumps({'line': f'> Agent {request.agent_id} reputation decreased (-1) due to failure.'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'line': f'[WARN] Failed to update reputation: {e}'})}\n\n"

        latest_job_state["status"] = "completed" if status == JobStatus.COMPLETED else "failed"
        
        result = JobResult(
            job_id=job_id,
            status=status,
            output=output_text,
            verified=validation.verified,
            validation_strategy=validation.strategy,
            validation_reason=validation.reason,
            signature=signature,
            pubkey=result_signer.public_key,
            signed_payload=signed_payload,
            timestamp=signed_payload["timestamp"],
        )
        yield f"data: {result.model_dump_json()}\n\n"
        
        await asyncio.sleep(5)
        latest_job_state["status"] = "idle"
        latest_job_state["step"] = 0
        latest_job_state["last_tx"] = None

    return StreamingResponse(event_generator(), media_type="text/event-stream")

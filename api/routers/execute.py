from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse, JSONResponse

from api.models.job import JobRequest, JobResult, JobStatus
from api.services.activity_log import push_event
from api.services.docker_runner import docker_runner
from api.services.registry_client import registry_client
from api.services.signer import result_signer
from api.services.validator import validate_execution_output
from api.services import x402_facilitator_service
from decimal import Decimal
from stellar_sdk import Server
from stellar_sdk.exceptions import NotFoundError
import uuid
import asyncio
from datetime import UTC, datetime
import json
import os

_MIN_XLM_PAYMENT = Decimal("0.05")
_VERIFY_ATTEMPTS = 12
_VERIFY_INTERVAL_SEC = 2.5

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
    if any("Job canceled by client" in line for line in output_lines):
        return JobStatus.CANCELED
    if any(line.startswith("[TIMEOUT]") for line in output_lines):
        return JobStatus.TIMEOUT
    if any(line.startswith("[ERROR]") for line in output_lines):
        return JobStatus.FAILED
    if not verified:
        return JobStatus.FAILED
    return JobStatus.COMPLETED

async def _verify_payment(tx_hash: str) -> bool:
    """Verifies that the payment transaction was successful on Horizon and sent native XLM to the executor."""
    tx_hash = (tx_hash or "").strip()
    if not tx_hash:
        return False
    executor_pk = (os.getenv("EXECUTOR_PUBLIC_KEY") or "").strip()
    if not executor_pk:
        print("Payment verification: EXECUTOR_PUBLIC_KEY is not set")
        return False
    executor_norm = executor_pk.upper()
    horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
    server = Server(horizon_url)

    try:
        tx = await asyncio.wait_for(
            asyncio.to_thread(server.transactions().transaction(tx_hash).call),
            timeout=15.0,
        )
    except NotFoundError:
        return False
    except asyncio.TimeoutError:
        print(f"Payment verification timed out loading TX: {tx_hash}")
        return False
    except Exception as e:
        print(f"Payment verification error loading TX: {e}")
        return False

    if not tx.get("successful", False):
        return False

    try:
        pays = await asyncio.wait_for(
            asyncio.to_thread(server.payments().for_transaction(tx_hash).call),
            timeout=15.0,
        )
    except NotFoundError:
        return False
    except asyncio.TimeoutError:
        print(f"Payment verification timed out loading payments for TX: {tx_hash}")
        return False
    except Exception as e:
        print(f"Payment verification error loading payments: {e}")
        return False

    for op in pays.get("_embedded", {}).get("records", []):
        if op.get("asset_type") != "native":
            continue
        dest = (op.get("to") or "").strip().upper()
        if dest != executor_norm:
            continue
        try:
            amt = Decimal(str(op.get("amount", "0")))
        except Exception:
            continue
        if amt >= _MIN_XLM_PAYMENT:
            return True
    return False

@router.post("/deactivate")
async def deactivate_agent(agent_id: str):
    """Deactivates an agent in the registry contract."""
    try:
        await asyncio.to_thread(registry_client.deactivate_agent, agent_id)
        return {"status": "success", "message": f"Agent {agent_id} deactivated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("")
async def execute_sync(
    request: JobRequest,
    x_stellar_payment_tx: str = Header(None, alias="X-Stellar-Payment-Tx"),
    x_payment: str = Header(None, alias="X-Payment"),
    payment_signature: str = Header(None, alias="Payment-Signature"),
):
    """
    Non-SSE version of /execute/stream.
    Runs the full payment → registry → Docker pipeline and returns a single JSON result.
    Use this if your client cannot consume Server-Sent Events.
    """
    log_lines = []
    final_result = None

    stream_response = await execute_stream(
        request=request,
        x_stellar_payment_tx=x_stellar_payment_tx,
        x_payment=x_payment,
        payment_signature=payment_signature,
        response=Response(),
    )

    # If execute_stream returned a plain dict (402 or error), pass it straight through
    if isinstance(stream_response, dict):
        status_code = 402 if stream_response.get("x402Version") == 2 else 400
        return JSONResponse(content=stream_response, status_code=status_code)

    # Otherwise consume the SSE stream and collect lines
    async for chunk in stream_response.body_iterator:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        for raw_line in text.splitlines():
            if not raw_line.startswith("data: "):
                continue
            payload = raw_line[6:].strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
                # Final SSE event is full JobResult (job_id + status); early events may include job_id only.
                if "job_id" in parsed and "status" in parsed:
                    final_result = parsed
                else:
                    log_lines.append(parsed.get("line", ""))
            except Exception:
                pass

    if final_result:
        final_result["log"] = [l for l in log_lines if l]
        return JSONResponse(content=final_result)

    # Fallback: stream ended without a final result (payment or registry blocked it)
    return JSONResponse(
        status_code=402,
        content={
            "status": "failed",
            "log": [l for l in log_lines if l],
            "error": "Job did not complete — check log for details.",
        },
    )


@router.post("/stream")
async def execute_stream(
    request: JobRequest,
    x_stellar_payment_tx: str = Header(None, alias="X-Stellar-Payment-Tx"),
    x_payment: str = Header(None, alias="X-Payment"),
    payment_signature: str = Header(None, alias="Payment-Signature"),
    response: Response = Response(),
):
    # Payment = authorization: official x402 v2 (X-Payment + facilitator) or legacy XLM tx hash.
    tx_header = (x_stellar_payment_tx or "").strip()
    payment_header = (x_payment or payment_signature or "").strip()
    use_facilitator = bool(payment_header) and x402_facilitator_service.facilitator_enabled()

    if not payment_header and not tx_header:
        response.status_code = 402
        legacy = {
            "destination": os.getenv("EXECUTOR_PUBLIC_KEY"),
            "amount": "0.05",
            "asset": "native",
            "header": "X-Stellar-Payment-Tx",
            "prepare_unsigned_transaction": "/api/x402/prepare-payment",
        }

        if x402_facilitator_service.facilitator_enabled():
            # x402 v2 response — includes x402Version, accepts, and facilitator
            body: dict = {
                "x402Version": 2,
                "error": "Payment Required",
                "message": (
                    "Use x402 v2: pay per facilitator, then retry with X-Payment (JSON PaymentPayload). "
                    "Or use legacy flow: 0.05 native XLM to the executor and pass X-Stellar-Payment-Tx."
                ),
                "documentation": "https://developers.stellar.org/docs/build/agentic-payments/x402",
                "legacy": legacy,
            }
            try:
                body.update(x402_facilitator_service.build_payment_required_dict())
            except ValueError as e:
                body["x402_configuration_error"] = str(e)
            # Ensure accepts is always present even if build_payment_required_dict didn't set it
            if "accepts" not in body:
                body["accepts"] = []
            body["facilitator"] = {
                "url": x402_facilitator_service.facilitator_base_url(),
                "retry_header": "X-Payment",
                "note": (
                    "Default requirement uses USDC on Stellar (see X402_PRICE / X402_STELLAR_ASSET). "
                    "Executor account must be able to receive that asset."
                ),
            }
        else:
            # Legacy-only response — no x402Version
            body = {
                "error": "Payment Required",
                "message": (
                    "Facilitator disabled. Use legacy flow: 0.05 native XLM to the executor "
                    "and pass X-Stellar-Payment-Tx."
                ),
                "documentation": "https://developers.stellar.org/docs/build/agentic-payments/x402",
                "legacy": legacy,
            }
        return body

    job_id = str(uuid.uuid4())
    
    async def event_generator():
        output_acc = []
        
        # Step 1: Wallet auth — facilitator (x402 v2) or legacy Horizon XLM
        latest_job_state["status"] = "authorizing"
        latest_job_state["step"] = 1

        if use_facilitator:
            push_event(
                kind="execute",
                severity="info",
                title="Verifying x402 (facilitator)",
                detail=f"POST {x402_facilitator_service.facilitator_base_url()}/verify",
            )
            yield f"data: {json.dumps({'line': '> Verifying X-Payment with facilitator…'})}\n\n"
            ok, msg, settle_tx = await x402_facilitator_service.verify_and_settle(payment_header)
            if not ok:
                push_event(
                    kind="execute",
                    severity="error",
                    title="Facilitator payment failed",
                    detail=msg[:200],
                )
                yield f"data: {json.dumps({'line': f'[ERROR] Facilitator: {msg}'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return
            short = (settle_tx or "unknown")[:8]
            latest_job_state["last_tx"] = {
                "type": "AUTH (x402-facilitator)",
                "amount": (os.getenv("X402_PRICE") or "0.01") + " USDC",
                "id": short,
            }
            push_event(
                kind="execute",
                severity="success",
                title="x402 facilitator authorized",
                detail=msg + (f" · tx {settle_tx[:12]}…" if settle_tx else ""),
                hash_short=short,
                hash_full=settle_tx,
            )
            yield f"data: {json.dumps({'line': '> Authorization verified via x402 facilitator.'})}\n\n"
        else:
            push_event(
                kind="execute",
                severity="info",
                title="Verifying x402 payment",
                detail=f"TX {tx_header[:12]}… · Horizon lookup",
                hash_short=tx_header[:8],
            )
            yield f"data: {json.dumps({'line': f'> Verifying legacy XLM payment (TX: {tx_header[:8]}...)'})}\n\n"

            payment_valid = False
            for attempt in range(_VERIFY_ATTEMPTS):
                yield f"data: {json.dumps({'line': f'> Ledger check {attempt + 1}/{_VERIFY_ATTEMPTS} (querying Horizon for payment)…'})}\n\n"
                payment_valid = await _verify_payment(tx_header)
                if payment_valid:
                    break
                yield f"data: {json.dumps({'line': f'> Not indexed or not matched yet; retrying in {_VERIFY_INTERVAL_SEC:.0f}s…'})}\n\n"
                await asyncio.sleep(_VERIFY_INTERVAL_SEC)

            if not payment_valid:
                push_event(
                    kind="execute",
                    severity="error",
                    title="Payment verification failed",
                    detail=f"Could not confirm {tx_header[:12]}… on-chain",
                    hash_short=tx_header[:8],
                )
                yield f"data: {json.dumps({'line': f'[ERROR] Could not verify payment {tx_header[:8]} on-chain.'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return

            latest_job_state["last_tx"] = {
                "type": "AUTH (x402-legacy-xlm)",
                "amount": "0.05 XLM",
                "id": tx_header[:8],
            }
            push_event(
                kind="execute",
                severity="success",
                title="x402 authorized (legacy XLM)",
                detail="Payment verified · proceeding to registry",
                hash_short=tx_header[:8],
                hash_full=tx_header,
                amount_xlm="0.05",
            )
            yield f"data: {json.dumps({'line': '> Authorization verified (Horizon).'})}\n\n"

        await asyncio.sleep(1)
        
        # Step 2: Registry Check
        latest_job_state["status"] = "registry"
        latest_job_state["step"] = 2
        push_event(
            kind="registry",
            severity="info",
            title="Registry check",
            detail=f"Agent `{request.agent_id}`",
        )
        yield f"data: {json.dumps({'line': f'> Verifying agent {request.agent_id} in registry contract...'})}\n\n"
        
        # Real registry check
        # Fail-closed: if registry is unreachable or contract ID is missing, refuse the job.
        if not registry_client.contract_id:
            if os.getenv("REGISTRY_BYPASS_DEV", "").strip().lower() in ("1", "true", "yes"):
                yield f"data: {json.dumps({'line': '[WARN] REGISTRY_BYPASS_DEV active — skipping registry check (dev only).'})}\n\n"
            else:
                yield f"data: {json.dumps({'line': '[ERROR] REGISTRY_CONTRACT_ID is not set. Job refused.'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return

        else:
            registry_error = None
            agent_record = None
            for attempt in range(3):
                try:
                    agent_record = await asyncio.to_thread(
                        registry_client.get_agent_record, request.agent_id
                    )
                    registry_error = None
                    break
                except Exception as e:
                    registry_error = e
                    if attempt < 2:
                        yield f"data: {json.dumps({'line': f'> Registry check attempt {attempt + 1} failed, retrying...'})}\n\n"
                        await asyncio.sleep(2)

            if registry_error is not None:
                yield f"data: {json.dumps({'line': f'[ERROR] Registry unreachable after 3 attempts: {registry_error}. Job refused.'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return

            if not agent_record:
                yield f"data: {json.dumps({'line': f'[ERROR] Agent {request.agent_id} not found in registry. Job refused.'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return

            if agent_record.get("active") is False:
                yield f"data: {json.dumps({'line': f'[ERROR] Agent {request.agent_id} is deactivated in the registry. Job refused.'})}\n\n"
                latest_job_state["status"] = "failed"
                latest_job_state["step"] = 0
                return

            yield f"data: {json.dumps({'line': f'> Agent {request.agent_id} verified on-chain (active).'})}\n\n"

        await asyncio.sleep(1)

        from api.services import docker_job_control as _djc
        from api.services import execute_broadcast as _eb
        from api.services import a2a_execute_hooks as _hooks
        from api.services.a2a_task_builder import task_document_from_job_result as _task_doc

        accepted = {"job_id": job_id, "phase": "job_accepted"}
        await _eb.publish(job_id, accepted)
        yield f"data: {json.dumps(accepted)}\n\n"

        try:
            # Step 3: Execution
            latest_job_state["status"] = "executing"
            latest_job_state["step"] = 3
            push_event(
                kind="docker",
                severity="info",
                title="Docker execution",
                detail=f"Image `{request.image[:40]}{'…' if len(request.image) > 40 else ''}`",
            )

            await _hooks.on_job_running(job_id, request)

            async for line in docker_runner.run(
                request.image,
                request.cmd,
                job_id=job_id,
                cancel_check=_djc.cancel_check_factory(job_id),
            ):
                output_acc.append(line)
                pl = {"line": line}
                await _eb.publish(job_id, pl)
                yield f"data: {json.dumps(pl)}\n\n"

            latest_job_state["status"] = "finalizing"
            latest_job_state["step"] = 4
            push_event(
                kind="validation",
                severity="info",
                title="Validating output",
                detail=f"Job {job_id[:8]}…",
            )
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
            push_event(
                kind="sign",
                severity="success",
                title="Result signed",
                detail=f"Job {job_id[:8]}… · off-chain signature",
                job_id=job_id,
            )

            status = _resolve_job_status(output_acc, validation.verified)

            # Update reputation on-chain
            if status == JobStatus.COMPLETED:
                try:
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

            if status == JobStatus.COMPLETED:
                latest_job_state["status"] = "completed"
            elif status == JobStatus.CANCELED:
                latest_job_state["status"] = "canceled"
            else:
                latest_job_state["status"] = "failed"
            push_event(
                kind="job",
                severity="success" if status == JobStatus.COMPLETED else "error",
                title="Job "
                + (
                    "completed"
                    if status == JobStatus.COMPLETED
                    else "canceled"
                    if status == JobStatus.CANCELED
                    else "failed"
                ),
                detail=validation.reason[:120] if validation.reason else str(status.value),
                job_id=job_id,
            )

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
            await _hooks.on_job_terminal_a2a(job_id, _task_doc(job_id, result))
            final_payload = json.loads(result.model_dump_json())
            await _eb.publish(job_id, final_payload)
            yield f"data: {result.model_dump_json()}\n\n"

            await asyncio.sleep(5)
            latest_job_state["status"] = "idle"
            latest_job_state["step"] = 0
            latest_job_state["last_tx"] = None
        finally:
            await _hooks.on_job_cleanup(job_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
import os
import sys
import webbrowser
import threading
import time
from contextlib import asynccontextmanager

if __package__ in (None, ""):
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from stellar_sdk import Server
from dotenv import load_dotenv

load_dotenv()

from api.routers import a2a_binding, execute, x402_prep
from api.services.registry_client import registry_client
from api.services.discovery_builder import build_discovery_payload, fetch_json_from_ipfs
from api.services.activity_log import push_event, get_events, clear_events
import json
import asyncio

def _should_open_browser() -> bool:
    if os.getenv("DISABLE_AUTO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.path.exists("/.dockerenv"):
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _should_open_browser():

        def open_browser():
            time.sleep(1.5)
            host = os.getenv("BROWSER_OPEN_HOST", "127.0.0.1")
            port = os.getenv("PORT", "8000")
            url = f"http://{host}:{port}"
            print(f"\n[SYSTEM] Dashboard: {url}/  ·  Home: {url}/home\n")
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=open_browser, daemon=True).start()
    yield

app = FastAPI(
    title="Stellarpay Executor API",
    lifespan=lifespan,
    docs_url="/_swagger/ui",
    redoc_url="/redoc",
)

# Main Execution Router
app.include_router(execute.router)
app.include_router(x402_prep.router)
app.include_router(a2a_binding.router)

# Mount static files for the dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/api/discovery")
async def get_agent_discovery():
    """Agent card from `agent_metadata.json` plus `PUBLIC_BASE_URL` and x402 hints."""
    return build_discovery_payload()


@app.get("/.well-known/x402")
async def well_known_x402():
    """Standard x402 discovery endpoint — redirects to /api/discovery for interoperability."""
    return RedirectResponse(url="/api/discovery")


@app.get("/api/discovery/resolved")
async def get_discovery_resolved(agent_id: str = "agent_402"):
    """Merge local/env discovery with on-chain registry row and IPFS metadata (if CID resolvable)."""
    local = build_discovery_payload()
    out: dict = {
        "local_file_and_env": local,
        "on_chain_agent": None,
        "ipfs_metadata": None,
    }
    try:
        rec = await asyncio.to_thread(registry_client.get_agent_record, agent_id)
        out["on_chain_agent"] = rec
        cid = (rec or {}).get("metadata_cid")
        if cid:
            out["ipfs_metadata"] = await fetch_json_from_ipfs(str(cid))
    except Exception as e:
        out["registry_error"] = str(e)
    return out

@app.post("/api/pay")
async def process_payment():
    """Demo-only: Automatically send 0.05 XLM from Deployer to Executor to simulate x402 flow."""
    try:
        deployer_pk = os.getenv("DEPLOYER_PUBLIC_KEY")
        deployer_secret = os.getenv("DEPLOYER_SECRET")
        executor_pk = os.getenv("EXECUTOR_PUBLIC_KEY")
        
        horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
        server = Server(horizon_url)
        
        # Load account
        source_account = await asyncio.to_thread(server.load_account, deployer_pk)
        
        # Build transaction
        from stellar_sdk import TransactionBuilder, Network, Asset, Keypair
        tx = (
            TransactionBuilder(source_account, Network.TESTNET_NETWORK_PASSPHRASE)
            .append_payment_op(executor_pk, Asset.native(), "0.05")
            .set_timeout(30)
            .build()
        )
        
        # Sign and submit
        kp = Keypair.from_secret(deployer_secret)
        tx.sign(kp)
        response = await asyncio.to_thread(server.submit_transaction, tx)
        tx_hash = response.get("hash") or response.get("id")
        if not tx_hash:
            return {"error": "No transaction hash in Horizon response", "raw_keys": list(response.keys())}

        push_event(
            kind="payment",
            severity="success",
            title="x402 payment (0.05 XLM)",
            detail=f"Deployer → Executor · {tx_hash[:12]}…",
            hash_short=tx_hash[:8],
            hash_full=tx_hash,
            amount_xlm="0.05",
            deployer_delta="-0.05",
            executor_delta="+0.05",
        )
        return {"hash": tx_hash, "status": "success", "amount": "0.05"}
    except Exception as e:
        print(f"Payment error: {e}")
        push_event(
            kind="payment",
            severity="error",
            title="Payment failed",
            detail=str(e),
        )
        return {"error": str(e)}

@app.get("/api/activity")
async def list_activity():
    return {"events": get_events()}


class ActivityClearBody(BaseModel):
    confirm: bool = False


@app.post("/api/activity/clear")
async def clear_activity(body: ActivityClearBody):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Send {confirm: true} to clear the feed")
    clear_events()
    return {"ok": True}


@app.get("/api/vault")
async def get_vault_data():
    horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
    server = Server(horizon_url)
    
    deployer_pk = os.getenv("DEPLOYER_PUBLIC_KEY")
    executor_pk = os.getenv("EXECUTOR_PUBLIC_KEY")
    registry_id = (os.getenv("REGISTRY_CONTRACT_ID") or "").strip() or None

    data = {
        "wallets": [],
        "transactions": [],
        "registry": {
            "id": registry_id,
            "agent_id": "agent_402",
            "reputation": 0,
            "active": False,
            "owner": None,
            "metadata_cid": None,
            "on_chain": False,
            "hint": None,
        },
    }

    rid = registry_id
    deployer_secret = (os.getenv("DEPLOYER_SECRET") or "").strip()
    if not rid:
        data["registry"]["hint"] = "no_contract_id"
    elif not deployer_secret:
        data["registry"]["hint"] = "no_deployer_secret"
    else:
        try:
            rec = await asyncio.to_thread(registry_client.get_agent_record, "agent_402")
            if rec:
                data["registry"]["on_chain"] = True
                data["registry"]["hint"] = "ok"
                data["registry"]["reputation"] = int(rec.get("reputation") or 0)
                data["registry"]["active"] = bool(rec.get("active"))
                data["registry"]["owner"] = rec.get("owner")
                data["registry"]["metadata_cid"] = rec.get("metadata_cid")
            else:
                data["registry"]["hint"] = "agent_not_found_or_unparsable"
        except Exception as e:
            print(f"Error fetching agent from registry: {e}")
            data["registry"]["hint"] = "registry_fetch_error"
            data["registry"]["fetch_error"] = str(e)[:240]
    
    def _sync_wallet_slice(name: str, public_key: str):
        acc = server.accounts().account_id(public_key).call()
        balance = next((b["balance"] for b in acc["balances"] if b["asset_type"] == "native"), "0")
        wallet = {"name": name, "public_key": public_key, "balance": balance}
        txs = server.transactions().for_account(public_key).limit(5).order(desc=True).call()
        rows = []
        for tx in txs["_embedded"]["records"]:
            rows.append({
                "account": name,
                "hash": tx["hash"][:8] + "...",
                "hash_full": tx["hash"],
                "created_at": tx["created_at"],
                "fee": f"{int(tx['fee_charged']) / 10000000} XLM",
                "success": tx["successful"],
            })
        return wallet, rows

    for name, pk in [("Deployer", deployer_pk), ("Executor", executor_pk)]:
        if not pk:
            continue
        try:
            wallet, rows = await asyncio.to_thread(_sync_wallet_slice, name, pk)
            data["wallets"].append(wallet)
            data["transactions"].extend(rows)
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            
    return data

@app.get("/")
async def root():
    """Executor dashboard (primary app UI)."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "project": "Stellarpay"}


@app.get("/home")
async def home_page():
    """Marketing / home page (separate from the dashboard at `/`)."""
    home_file = os.path.join(static_dir, "home.html")
    if os.path.exists(home_file):
        return FileResponse(home_file)
    raise HTTPException(status_code=404, detail="Home page not found")


@app.get("/dashboard")
async def dashboard_legacy():
    """Previous path; dashboard lives at `/`."""
    return RedirectResponse(url="/", status_code=302)


@app.get("/dev/docs")
async def dev_docs_page():
    """Static developer documentation (distinct from OpenAPI at /docs)."""
    doc_file = os.path.join(static_dir, "dev-docs.html")
    if os.path.exists(doc_file):
        return FileResponse(doc_file)
    raise HTTPException(status_code=404, detail="Developer documentation not found")


@app.get("/docs", include_in_schema=False)
async def docs_shell_page():
    """Swagger UI inside site chrome (back nav). Raw UI remains at `/_swagger/ui`."""
    shell = os.path.join(static_dir, "swagger-shell.html")
    if os.path.exists(shell):
        return FileResponse(shell)
    return RedirectResponse(url="/_swagger/ui", status_code=302)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
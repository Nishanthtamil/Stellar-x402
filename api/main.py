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
from fastapi.responses import FileResponse
from stellar_sdk import Server
from dotenv import load_dotenv

load_dotenv()

from api.routers import execute, x402_prep
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
            print(f"\n[SYSTEM] Launching Dashboard: {url}\n")
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=open_browser, daemon=True).start()
    yield

app = FastAPI(title="Stellarpay Executor API", lifespan=lifespan)

# Main Execution Router
app.include_router(execute.router)
app.include_router(x402_prep.router)

# Mount static files for the dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/api/discovery")
async def get_agent_discovery():
    """Agent card from `agent_metadata.json` plus `PUBLIC_BASE_URL` and x402 hints."""
    return build_discovery_payload()


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
    registry_id = os.getenv("REGISTRY_CONTRACT_ID")
    
    data = {
        "wallets": [], 
        "transactions": [],
        "registry": {
            "id": registry_id,
            "agent_id": "agent_402",
            "reputation": 0,
            "active": False
        }
    }

    # Fetch real on-chain agent data
    try:
        agent_data = await asyncio.to_thread(registry_client.get_agent, "agent_402")
        if agent_data:
            from stellar_sdk import xdr
            sc_val = xdr.SCVal.from_xdr(agent_data)
            # The contract returns Option<Agent>. If it's not Void, it's an Agent struct.
            if sc_val.type != xdr.SCValType.SCV_VOID:
                # Agent struct: owner (Address), metadata_cid (String), reputation (i64), active (bool)
                if sc_val.map and sc_val.map.sc_map:
                    for entry in sc_val.map.sc_map:
                        # Parse key
                        key = ""
                        if entry.key.type == xdr.SCValType.SCV_SYMBOL:
                            key = entry.key.sym.sc_symbol.decode()
                        
                        # Parse val
                        if key == "reputation":
                            data["registry"]["reputation"] = entry.val.i64.int64
                        elif key == "active":
                            data["registry"]["active"] = entry.val.b
    except Exception as e:
        print(f"Error fetching agent from registry: {e}")
    
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
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "project": "Stellarpay"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)

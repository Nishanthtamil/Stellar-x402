import os
import time
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, SorobanServer, scval
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus
from dotenv import load_dotenv

load_dotenv()

class RegistryClient:
    def __init__(self):
        self.rpc_server_url = os.getenv("SOROBAN_RPC_URL", "https://soroban-testnet.stellar.org")
        self.horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
        self.network_passphrase = Network.TESTNET_NETWORK_PASSPHRASE
        _cid = (os.getenv("REGISTRY_CONTRACT_ID") or "").strip()
        self.contract_id = _cid or None

        self.soroban_server = SorobanServer(self.rpc_server_url)
        self.server = Server(self.horizon_url)

    def _submit_tx(self, transaction, secret_key):
        kp = Keypair.from_secret(secret_key)
        transaction.sign(kp)

        send_response = self.soroban_server.send_transaction(transaction)
        if send_response.status not in (
            SendTransactionStatus.PENDING,
            SendTransactionStatus.DUPLICATE,
        ):
            raise Exception(
                f"Send transaction failed: {send_response.status} "
                f"{send_response.error_result_xdr}"
            )

        tx_hash = send_response.hash
        
        while True:
            get_response = self.soroban_server.get_transaction(tx_hash)
            if get_response.status == GetTransactionStatus.NOT_FOUND:
                time.sleep(2)
                continue
            if get_response.status == GetTransactionStatus.SUCCESS:
                return get_response
            if get_response.status == GetTransactionStatus.FAILED:
                raise Exception(f"Transaction failed: {get_response.result_xdr}")
            time.sleep(2)

    def register_agent(self, agent_id: str, metadata_cid: str, secret_key: str):
        if not self.contract_id:
            raise ValueError("Set REGISTRY_CONTRACT_ID in .env (deploy registry contract first).")
        kp = Keypair.from_secret(secret_key)
        source_account = self.soroban_server.load_account(kp.public_key)

        args = [
            scval.to_address(kp.public_key),
            scval.to_string(agent_id),
            scval.to_string(metadata_cid),
        ]

        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .append_invoke_contract_function_op(
                self.contract_id, "register_agent", args
            )
            .set_timeout(30)
            .build()
        )

        tx = self.soroban_server.prepare_transaction(tx)
        return self._submit_tx(tx, secret_key)

    def _get_agent_result_xdr(self, agent_id: str):
        if not self.contract_id:
            return None

        secret = os.getenv("DEPLOYER_SECRET")
        if not secret or not secret.strip():
            return None

        args = [scval.to_string(agent_id)]

        source_kp = Keypair.from_secret(secret)
        source_account = self.soroban_server.load_account(source_kp.public_key)

        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .append_invoke_contract_function_op(self.contract_id, "get_agent", args)
            .set_timeout(30)
            .build()
        )

        simulate_response = self.soroban_server.simulate_transaction(tx)
        if simulate_response.error:
            # Distinguish RPC/contract errors from "agent not in registry" (Option::None).
            raise RuntimeError(str(simulate_response.error))

        if not simulate_response.results:
            return None

        from stellar_sdk import xdr

        result_xdr = simulate_response.results[0].xdr
        sc_val = xdr.SCVal.from_xdr(result_xdr)

        if sc_val.type == xdr.SCValType.SCV_VOID:
            return None

        return result_xdr

    def get_agent(self, agent_id: str):
        """Raw SCVal XDR bytes for `get_agent` (for legacy callers)."""
        return self._get_agent_result_xdr(agent_id)

    def get_agent_record(self, agent_id: str) -> dict | None:
        """Parsed on-chain Agent struct, or None if missing / misconfigured."""
        raw = self._get_agent_result_xdr(agent_id)
        if not raw:
            return None
        from stellar_sdk import xdr
        from api.services.soroban_agent_parse import sc_agent_map_to_dict

        sc_val = xdr.SCVal.from_xdr(raw)
        return sc_agent_map_to_dict(sc_val)

    def update_reputation(self, agent_id: str, delta: int):
        if not self.contract_id:
            return
        
        secret = os.getenv("DEPLOYER_SECRET")
        if not secret:
            return

        kp = Keypair.from_secret(secret)
        source_account = self.soroban_server.load_account(kp.public_key)

        args = [
            scval.to_string(agent_id),
            scval.to_int64(delta),
        ]

        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .append_invoke_contract_function_op(
                self.contract_id, "update_reputation", args
            )
            .set_timeout(30)
            .build()
        )

        tx = self.soroban_server.prepare_transaction(tx)
        return self._submit_tx(tx, secret)

    def deactivate_agent(self, agent_id: str):
        if not self.contract_id:
            return
        
        secret = os.getenv("DEPLOYER_SECRET")
        if not secret:
            return

        kp = Keypair.from_secret(secret)
        source_account = self.soroban_server.load_account(kp.public_key)

        args = [scval.to_string(agent_id)]

        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .append_invoke_contract_function_op(
                self.contract_id, "deactivate_agent", args
            )
            .set_timeout(30)
            .build()
        )

        tx = self.soroban_server.prepare_transaction(tx)
        return self._submit_tx(tx, secret)

registry_client = RegistryClient()

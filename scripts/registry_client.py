import os
import time
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, scp
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.soroban_rpc import SorobanRpcServer
from dotenv import load_dotenv

load_dotenv()

class RegistryClient:
    def __init__(self):
        self.rpc_server_url = os.getenv("SOROBAN_RPC_URL", "https://soroban-testnet.stellar.org")
        self.horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
        self.network_passphrase = Network.TESTNET_NETWORK_PASSPHRASE
        self.contract_id = os.getenv("REGISTRY_CONTRACT_ID")
        
        self.soroban_server = SorobanRpcServer(self.rpc_server_url)
        self.server = Server(self.horizon_url)

    def _submit_tx(self, transaction, secret_key):
        kp = Keypair.from_secret(secret_key)
        transaction.sign(kp)
        
        send_response = self.soroban_server.send_transaction(transaction)
        if send_response.error:
            raise Exception(f"Send transaction failed: {send_response.error}")
        
        tx_hash = send_response.hash
        print(f"Transaction submitted: {tx_hash}")
        
        # Poll for result
        while True:
            get_response = self.soroban_server.get_transaction(tx_hash)
            if get_response.status == "SUCCESS":
                return get_response
            elif get_response.status == "FAILED":
                raise Exception(f"Transaction failed: {get_response.result_xdr}")
            time.sleep(2)

    def register_agent(self, agent_id: str, metadata_cid: str, secret_key: str):
        kp = Keypair.from_secret(secret_key)
        source_account = self.soroban_server.get_account(kp.public_key)
        
        # Prepare arguments
        # register_agent(owner: Address, agent_id: String, metadata_cid: String)
        args = [
            stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_ADDRESS, address=stellar_xdr.SCAddress.from_string(kp.public_key)),
            stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_STRING, s=agent_id.encode()),
            stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_STRING, s=metadata_cid.encode())
        ]

        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .add_invoke_contract_op(self.contract_id, "register_agent", args)
            .set_timeout(30)
            .build()
        )
        
        # Simulate to set footprints/fees
        tx = self.soroban_server.prepare_transaction(tx)
        return self._submit_tx(tx, secret_key)

    def get_agent(self, agent_id: str):
        # get_agent(agent_id: String) -> Option<Agent>
        args = [
            stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_STRING, s=agent_id.encode())
        ]
        
        # For read-only calls, we can use simulateTransaction or just use a dummy account
        # Simpler for now: use simulate_transaction
        source_kp = Keypair.from_secret(os.getenv("DEPLOYER_SECRET"))
        source_account = self.soroban_server.get_account(source_kp.public_key)
        
        tx = (
            TransactionBuilder(source_account, self.network_passphrase)
            .add_invoke_contract_op(self.contract_id, "get_agent", args)
            .set_timeout(30)
            .build()
        )
        
        simulate_response = self.soroban_server.simulate_transaction(tx)
        if simulate_response.error:
             raise Exception(f"Simulation failed: {simulate_response.error}")
        
        # Parse result from simulation
        if not simulate_response.results:
            return None
            
        result_val = simulate_response.results[0].xdr
        # This is an SCVal(SCV_MAP) wrapped in Option
        # We'll need a more robust parser for production, but this confirms connectivity
        return result_val

if __name__ == "__main__":
    client = RegistryClient()
    print(f"Registry Client initialized for contract: {client.contract_id}")
    # Example usage:
    # client.register_agent("agent-xyz", "Qm...", os.getenv("DEPLOYER_SECRET"))

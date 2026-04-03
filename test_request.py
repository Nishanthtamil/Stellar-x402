import requests
import json
import os
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset
from dotenv import load_dotenv

load_dotenv()

url = "http://127.0.0.1:8000/execute/stream"
data = {
    "task": "Extract the numbers from the text and calculate their sum",
    "input": {
        "expected_sum": 4
    },
    "agent_id": "agent_402",
    "image": "python:3.11-slim",
    "cmd": "sh -c \"echo 'The first number is 2. The second number is 2.'\""
}

def make_payment(amount: str, destination: str):
    """Sends XLM from Deployer to Executor to satisfy x402 requirement."""
    secret = os.getenv("DEPLOYER_SECRET")
    horizon_url = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
    server = Server(horizon_url)
    source_kp = Keypair.from_secret(secret)
    
    print(f"> Sending {amount} XLM from Deployer to {destination}...")
    
    source_account = server.load_account(source_kp.public_key)
    transaction = (
        TransactionBuilder(
            source_account=source_account,
            network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_payment_op(destination=destination, amount=amount, asset=Asset.native())
        .set_timeout(30)
        .build()
    )
    transaction.sign(source_kp)
    response = server.submit_transaction(transaction)
    return response['hash']

# 1. Initial request to trigger 402
response = requests.post(url, json=data, stream=True)

if response.status_code == 402:
    error_data = response.json()
    print(f"Received 402: {error_data['message']}")
    
    # 2. Perform REAL payment from Deployer to Executor
    try:
        new_tx_hash = make_payment(error_data['amount'], error_data['destination'])
        print(f"> Payment successful! TX Hash: {new_tx_hash}")
        
        # 3. Retry with REAL transaction hash
        headers = {"X-Stellar-Payment-Tx": new_tx_hash}
        response = requests.post(url, json=data, headers=headers, stream=True)
    except Exception as e:
        print(f"[ERROR] Payment failed: {e}")
        exit(1)

# 4. Process streaming response
for line in response.iter_lines():
    if line:
        decoded_line = line.decode('utf-8')
        if decoded_line.startswith("data: "):
            try:
                payload = json.loads(decoded_line[6:])
                if "line" in payload:
                    print(payload["line"])
                else:
                    print(json.dumps(payload, indent=2))
            except json.JSONDecodeError:
                print(f"Failed to decode: {decoded_line}")

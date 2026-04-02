import os
from stellar_sdk import Keypair
import requests
from dotenv import load_dotenv

def generate_and_fund(name):
    print(f"Generating keypair for {name}...")
    kp = Keypair.random()
    public_key = kp.public_key
    secret = kp.secret
    
    print(f"Funding {name} ({public_key}) via Friendbot...")
    try:
        response = requests.get(f"https://friendbot.stellar.org/?addr={public_key}")
        if response.status_code == 200:
            print(f"Successfully funded {name}.")
        else:
            print(f"Failed to fund {name}: {response.text}")
    except Exception as e:
        print(f"Error funding {name}: {e}")
    
    return public_key, secret

if __name__ == "__main__":
    deployer_pub, deployer_sec = generate_and_fund("DEPLOYER")
    executor_pub, executor_sec = generate_and_fund("EXECUTOR")
    
    with open(".env", "w") as f:
        f.write(f"STELLAR_NETWORK=TESTNET\n")
        f.write(f"HORIZON_URL=https://horizon-testnet.stellar.org\n")
        f.write(f"SOROBAN_RPC_URL=https://soroban-testnet.stellar.org\n")
        f.write(f"DEPLOYER_PUBLIC_KEY={deployer_pub}\n")
        f.write(f"DEPLOYER_SECRET={deployer_sec}\n")
        f.write(f"EXECUTOR_PUBLIC_KEY={executor_pub}\n")
        f.write(f"EXECUTOR_SECRET={executor_sec}\n")
    
    print("\n.env file created with funded accounts.")

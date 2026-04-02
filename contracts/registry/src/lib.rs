#![no_std]
use soroban_sdk::{
    contract, contractimpl, contracttype, Address, Env, String,
};

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Agent {
    pub owner: Address,
    pub metadata_cid: String,
    pub reputation: i64,
    pub active: bool,
}

#[contracttype]
pub enum DataKey {
    Agent(String),
}

#[contract]
pub struct Registry;

#[contractimpl]
impl Registry {
    /// Registers a new agent with a unique ID and IPFS metadata CID.
    pub fn register_agent(env: Env, owner: Address, agent_id: String, metadata_cid: String) {
        owner.require_auth();
        
        let key = DataKey::Agent(agent_id.clone());
        if env.storage().persistent().has(&key) {
            panic!("Agent already exists");
        }

        let agent = Agent {
            owner: owner.clone(),
            metadata_cid,
            reputation: 0,
            active: true,
        };

        env.storage().persistent().set(&key, &agent);
    }

    /// Deactivates an agent. Only the agent's owner can perform this action.
    pub fn deactivate_agent(env: Env, agent_id: String) {
        let key = DataKey::Agent(agent_id.clone());
        let mut agent: Agent = env.storage().persistent().get(&key).expect("Agent not found");
        
        agent.owner.require_auth();
        agent.active = false;
        
        env.storage().persistent().set(&key, &agent);
    }

    /// Retrieves an agent's details by ID.
    pub fn get_agent(env: Env, agent_id: String) -> Option<Agent> {
        let key = DataKey::Agent(agent_id);
        env.storage().persistent().get(&key)
    }

    /// Updates an agent's reputation. 
    /// In a production environment, this would be restricted to authorized validators.
    pub fn update_reputation(env: Env, agent_id: String, delta: i64) {
        let key = DataKey::Agent(agent_id);
        let mut agent: Agent = env.storage().persistent().get(&key).expect("Agent not found");
        
        agent.reputation = agent.reputation.saturating_add(delta);
        
        env.storage().persistent().set(&key, &agent);
    }
}

mod test;

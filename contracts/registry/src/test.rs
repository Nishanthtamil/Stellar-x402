#![cfg(test)]
use super::{Registry, RegistryClient, Agent};
use soroban_sdk::{testutils::Address as _, Address, Env, String};

#[test]
fn test_register_and_get_agent() {
    let env = Env::default();
    let contract_id = env.register_contract(None, Registry);
    let client = RegistryClient::new(&env, &contract_id);

    let owner = Address::generate(&env);
    let agent_id = String::from_str(&env, "agent-001");
    let metadata_cid = String::from_str(&env, "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco");

    env.mock_all_auths();
    client.register_agent(&owner, &agent_id, &metadata_cid);

    let agent = client.get_agent(&agent_id).unwrap();
    assert_eq!(agent.owner, owner);
    assert_eq!(agent.metadata_cid, metadata_cid);
    assert_eq!(agent.reputation, 0);
    assert!(agent.active);
}

#[test]
#[should_panic(expected = "Agent already exists")]
fn test_duplicate_registration() {
    let env = Env::default();
    let contract_id = env.register_contract(None, Registry);
    let client = RegistryClient::new(&env, &contract_id);

    let owner = Address::generate(&env);
    let agent_id = String::from_str(&env, "agent-001");
    let metadata_cid = String::from_str(&env, "cid1");

    env.mock_all_auths();
    client.register_agent(&owner, &agent_id, &metadata_cid);
    client.register_agent(&owner, &agent_id, &metadata_cid);
}

#[test]
fn test_deactivate_agent() {
    let env = Env::default();
    let contract_id = env.register_contract(None, Registry);
    let client = RegistryClient::new(&env, &contract_id);

    let owner = Address::generate(&env);
    let agent_id = String::from_str(&env, "agent-001");
    let metadata_cid = String::from_str(&env, "cid1");

    env.mock_all_auths();
    client.register_agent(&owner, &agent_id, &metadata_cid);
    client.deactivate_agent(&agent_id);

    let agent = client.get_agent(&agent_id).unwrap();
    assert!(!agent.active);
}

#[test]
fn test_update_reputation() {
    let env = Env::default();
    let contract_id = env.register_contract(None, Registry);
    let client = RegistryClient::new(&env, &contract_id);

    let owner = Address::generate(&env);
    let agent_id = String::from_str(&env, "agent-001");
    let metadata_cid = String::from_str(&env, "cid1");

    env.mock_all_auths();
    client.register_agent(&owner, &agent_id, &metadata_cid);
    
    client.update_reputation(&agent_id, &10);
    let agent = client.get_agent(&agent_id).unwrap();
    assert_eq!(agent.reputation, 10);

    client.update_reputation(&agent_id, &-5);
    let agent = client.get_agent(&agent_id).unwrap();
    assert_eq!(agent.reputation, 5);
}

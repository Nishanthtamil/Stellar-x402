#![no_std]
use soroban_sdk::{contract, contractimpl, symbol_short, vec, Address, Env, String, Symbol, Vec};

#[contract]
pub struct Registry;

#[contractimpl]
impl Registry {
    pub fn hello(env: Env, to: Symbol) -> Vec<Symbol> {
        vec![&env, symbol_short!("Hello"), to]
    }
}

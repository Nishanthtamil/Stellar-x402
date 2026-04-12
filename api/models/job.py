from pydantic import BaseModel
from typing import Dict, Optional, Any
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELED = "canceled"


class ValidationStrategy(str, Enum):
    DETERMINISTIC = "deterministic"
    RULE_BASED = "rule_based"
    AI_BASED = "ai_based"

class JobRequest(BaseModel):
    task: str
    input: Dict[str, Any]
    agent_id: str
    image: Optional[str] = "python:3.11-slim"
    cmd: str

class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    output: str
    verified: bool = False
    validation_strategy: Optional[ValidationStrategy] = None
    validation_reason: Optional[str] = None
    signature: Optional[str] = None
    pubkey: Optional[str] = None
    signed_payload: Optional[Dict[str, Any]] = None
    timestamp: str

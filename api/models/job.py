from pydantic import BaseModel, Field
from typing import Dict, Optional, Any
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"

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
    signature: Optional[str] = None
    pubkey: Optional[str] = None
    timestamp: str

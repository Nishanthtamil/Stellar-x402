from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from api.models.job import JobRequest, JobResult, JobStatus
from api.services.docker_runner import docker_runner
import uuid
from datetime import datetime
import json

router = APIRouter(prefix="/execute", tags=["execution"])

@router.post("/stream")
async def execute_stream(request: JobRequest):
    job_id = str(uuid.uuid4())
    
    async def event_generator():
        output_acc = []
        async for line in docker_runner.run(request.image, request.cmd):
            output_acc.append(line)
            yield f"data: {json.dumps({'line': line})}\n\n"
        
        # Final result event
        result = JobResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            output="\n".join(output_acc),
            timestamp=datetime.utcnow().isoformat()
        )
        yield f"data: {result.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

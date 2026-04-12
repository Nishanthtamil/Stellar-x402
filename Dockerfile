# API + dashboard. Mount the host Docker socket at runtime so job containers run on the same engine (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY api ./api
COPY agent_metadata.json ./agent_metadata.json
COPY EXECUTOR_SKILL.md ./EXECUTOR_SKILL.md

EXPOSE 8000

# Mount host Docker socket at runtime so job containers run on a real engine (see docker-compose.yml).
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

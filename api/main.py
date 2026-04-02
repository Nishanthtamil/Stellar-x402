from fastapi import FastAPI
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="Stellarpay Executor API")

@app.get("/")
async def root():
    return {"status": "ok", "project": "Stellarpay"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

from fastapi import FastAPI
from api.routers import execute
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Stellarpay Executor API")

app.include_router(execute.router)

@app.get("/")
async def root():
    return {"status": "ok", "project": "Stellarpay"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""HH.RU Auto Response Bot - FastAPI Web Dashboard"""
import os
from app.routes import app
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HH_BOT_HOST", "127.0.0.1")
    port = int(os.environ.get("HH_BOT_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")

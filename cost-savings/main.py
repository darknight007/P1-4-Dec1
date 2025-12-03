# cost-savings/main.py

import uvicorn
import subprocess
import sys
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import the API Router
from api.routes import router as savings_router

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""

    app = FastAPI(
        title="Savings Agent Suite",
        description="Interactive ROI Calculator & Cost Discovery Agent.",
        version="2.0.0"
    )

    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 1. Register API Routes (The Backend)
    app.include_router(savings_router)

    return app

app = create_app()

# -----------------------------------------------------------------------------
# Streamlit Launcher
# -----------------------------------------------------------------------------

def run_streamlit():
    """Runs the Streamlit frontend in a separate process."""
    print("🚀 Launching Streamlit UI...")
    # We use sys.executable to ensure we use the same python env
    subprocess.Popen([sys.executable, "-m", "streamlit", "run", "cost-savings/app_streamlit.py", "--server.port", "8501"])

# -----------------------------------------------------------------------------
# Startup Events
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    print(f"INFO:  Savings Agent v2.0 Initialized.")
    print(f"INFO:  Discovery Engine: Active")
    print(f"INFO:  Backend API: http://localhost:8000")
    # Launch Streamlit on startup - DISABLED for manual run to avoid path errors
    # run_streamlit()
    print(f"INFO:  Frontend UI: http://localhost:8501")

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8000)
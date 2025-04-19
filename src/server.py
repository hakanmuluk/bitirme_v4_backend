# server.py

import os
from dotenv import load_dotenv
import uvicorn
from app import app

# Load environment variables from .env
load_dotenv()

# Get the PORT from environment variables or default to 5001
PORT = int(os.environ.get("PORT", 5001))

if __name__ == "__main__":
    print(f"Server running on http://localhost:{PORT}")
    #uvicorn.run(app, host="0.0.0.0", port=PORT)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=True           # optional, for dev
    )


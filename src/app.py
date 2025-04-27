# app.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import stockRoute, currencyRoute, loginRoute, logoutRoute, favoriteRoute, viewForestRoute, processNotificationRoute, saveNotificationRoute, reportRoute  # Import your route modules
from db.mongo import db  # Import the shared database from db.py
from chainlitIntegration import add_chainlit_routes

app = FastAPI()

# Middleware: Enable CORS for all origins (adjust as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000", "https://investmenthelper-ai.up.railway.app/", "https://investmenthelper-ai.up.railway.app"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the routers with the corresponding path prefixes.
app.include_router(stockRoute.router, prefix="/api/stocks")
app.include_router(currencyRoute.router, prefix="/api/currency")
app.include_router(loginRoute.router, prefix="/api")  # Login endpoint available at /api/login
app.include_router(favoriteRoute.router, prefix="/api/favorites")
app.include_router(logoutRoute.router, prefix="/api")
app.include_router(processNotificationRoute.router, prefix="/api/notification")
app.include_router(saveNotificationRoute.router, prefix="/api/notification")
app.include_router(viewForestRoute.router, prefix="/api/forest")
app.include_router(reportRoute.router, prefix="/api/report")

add_chainlit_routes(app)

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import init_db
from services.scheduler_service import start_scheduler, stop_scheduler
from routers import voice, sms_webhook, admin
from routers import web, auth_router, calendar_api
from routers import superadmin, employees


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    init_db()
    os.makedirs("static/audio", exist_ok=True)
    os.makedirs("static/css", exist_ok=True)
    os.makedirs("static/js", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    start_scheduler()
    import logging
    logging.basicConfig(level=logging.INFO)
    logging.info("AssistantAI démarré — %s", settings.base_url)
    yield
    # ── Shutdown ──
    stop_scheduler()


app = FastAPI(
    title="AssistantAI",
    description="Robot IA vocal pour réservations — restaurants, coiffeurs, salons",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Webhooks vocaux / SMS ────────────────────────────────────────────────────
app.include_router(voice.router, prefix="/voice", tags=["voice"])
app.include_router(sms_webhook.router, prefix="/sms", tags=["sms"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

# ── Web dashboard ────────────────────────────────────────────────────────────
app.include_router(web.router, tags=["web"])
app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
# app.include_router(subscriptions.router, prefix="/stripe", tags=["stripe"])  # Stripe désactivé
app.include_router(calendar_api.router, prefix="/api/calendar", tags=["calendar-api"])
app.include_router(superadmin.router, prefix="/superadmin", tags=["superadmin"])
app.include_router(employees.router, tags=["employees"])


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

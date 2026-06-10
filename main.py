from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers.health import router as health_router
from scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="AI Career Copilot API", lifespan=lifespan)
app.include_router(health_router)

from fastapi import APIRouter
from app.api.v1 import health, render, projects, webhooks

v1_router = APIRouter()

v1_router.include_router(health.router, tags=["health"])
v1_router.include_router(render.router, prefix="/render", tags=["render"])
v1_router.include_router(projects.router, prefix="/projects", tags=["projects"])
v1_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

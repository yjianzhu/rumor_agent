from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from src.config import settings

app = FastAPI(title="Rumor Agent Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

media_path = Path(settings.MEDIA_DIR)
if media_path.exists():
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# import routers after app is created to avoid circular imports
from src.api.page_routes import router as page_router
from src.api.partial_routes import router as partial_router
from src.api.api_routes import router as api_router
from src.api.public_routes import router as public_router

app.include_router(api_router)
app.include_router(partial_router)
app.include_router(page_router)
app.include_router(public_router)

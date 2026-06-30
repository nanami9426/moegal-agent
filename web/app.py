from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import init_settings
from db.session import init_db
from web.api import router


def create_app(*, init_database: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_settings()
        if init_database:
            init_db()
        yield

    app = FastAPI(
        title="Moegal Agent Web API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()

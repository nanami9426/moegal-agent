from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import init_settings
from agent.graph import close_chat_graphs
from db.session import init_db
from services.account.memory_consolidation import close_memory_consolidation_tasks
from web.api import router


def create_app(*, init_database: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_settings()
        if init_database:
            init_db()
        try:
            yield
        finally:
            await close_memory_consolidation_tasks()
            await close_chat_graphs()

    app = FastAPI(
        title="Moegal Agent Web API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()

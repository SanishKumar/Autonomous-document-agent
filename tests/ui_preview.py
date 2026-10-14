"""Isolated browser-test fixture; never point a shared deployment at this module.

Run locally: python -m uvicorn tests.ui_preview:create_preview --factory --port 8012
The fixture has public test credentials and a deterministic model double.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from app.agent import AgentService
from app.config import Settings
from app.main import create_app
from app.team.auth import PASSWORDS
from tests.fake_llm import FakeLLM

PASSWORD = "offline-test-password-only"


def create_preview():
    directory = Path("outputs/.ui-test") / uuid4().hex
    settings = Settings(outputs_dir=directory, auth_enabled=True)
    app = create_app(settings=settings, service=AgentService(settings, llm=FakeLLM()))
    original = app.router.lifespan_context

    @asynccontextmanager
    async def seeded_lifespan(application):
        async with original(application):
            auth = app.state.auth
            hashed = PASSWORDS.hash(PASSWORD)
            owner = auth.setup(
                "owner@example.test",
                "Alex Morgan",
                hashed,
                auth.setup_path.read_text(),
                "Fieldwork Studio · Test",
            )
            for role, name in [("reviewer", "Sam Rivera"), ("editor", "Jordan Lee")]:
                email = f"{role}@example.test"
                _, token = auth.invite(email, role, owner)
                auth.accept(token, email, name, hashed)
            yield

    app.router.lifespan_context = seeded_lifespan
    return app

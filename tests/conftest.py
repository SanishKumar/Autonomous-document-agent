import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent import AgentService
from app.config import Settings
from app.main import create_app
from tests.fake_llm import FakeLLM


@pytest.fixture
def team_app():
    directory = Path("outputs") / f".test-{uuid4().hex}"
    settings = Settings(outputs_dir=directory, auth_enabled=True)
    app = create_app(settings=settings, service=AgentService(settings, llm=FakeLLM()))
    try:
        with TestClient(app) as owner:
            yield app, owner, directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)

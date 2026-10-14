from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.agent import AgentRunError, AgentService
from app.config import Settings
from app.workspace.models import NewJob
from app.workspace.store import WorkspaceStore

logger = logging.getLogger(__name__)


class JobManager:
    """Bounded, cancellable jobs for one local server process; SQLite owns history."""

    def __init__(
        self, store: WorkspaceStore, settings: Settings, service_factory: Callable[[], AgentService]
    ):
        self.store = store
        self.settings = settings
        self.service_factory = service_factory
        self.tasks: dict[str, asyncio.Task] = {}
        self.slots = asyncio.Semaphore(settings.max_concurrent_jobs)
        self.stopping = False

    def submit(self, doc_id: str, payload: NewJob) -> None:
        task = asyncio.create_task(self._run(doc_id, payload), name=f"document-{doc_id}")
        self.tasks[doc_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(doc_id, None))

    async def _run(self, doc_id: str, payload: NewJob) -> None:
        async def sink(kind: str, data: dict) -> None:
            if kind == "task_failed":
                data = {
                    "entry": {
                        **data["entry"],
                        "error": "The model or tool could not complete this step.",
                    }
                }
            self.store.record(doc_id, kind, data)

        try:
            async with self.slots:
                async with asyncio.timeout(self.settings.job_timeout_seconds):
                    response = await self.service_factory().run(
                        payload.prompt(),
                        request_id=doc_id,
                        on_event=sink,
                    )
                    self.store.record(doc_id, "completed", response.model_dump())
        except asyncio.CancelledError:
            kind = "interrupted" if self.stopping else "cancelled"
            message = (
                "Server stopped during this run. Start a new run to try again."
                if self.stopping
                else "Run cancelled. No further model calls will be started."
            )
            self.store.record(doc_id, kind, {"message": message})
            raise
        except TimeoutError:
            self.store.record(
                doc_id,
                "failed",
                {
                    "message": "This run reached its time limit. Try a shorter brief or check the model provider."
                },
            )
        except Exception as exc:
            # Provider response bodies can contain prompts. Do not expose them in the workspace.
            logger.warning("Document %s failed (%s)", doc_id, type(exc).__name__)
            stage = exc.stage if isinstance(exc, AgentRunError) else "execution"
            self.store.record(
                doc_id,
                "failed",
                {
                    "message": f"Generation stopped at {stage}. Check provider credentials, quota and model availability, then try a new run.",
                },
            )

    async def cancel(self, doc_id: str) -> None:
        task = self.tasks.get(doc_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.store.get(doc_id)["status"] in {"queued", "running"}:
            self.store.record(doc_id, "cancelled", {"message": "Cancelled by you."})

    async def close(self) -> None:
        self.stopping = True
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

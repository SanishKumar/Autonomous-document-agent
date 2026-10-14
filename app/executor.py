from __future__ import annotations

from time import perf_counter

from app.events import EventSink, emit
from app.schemas import ExecutionPlan, TaskExecution
from app.tools import AgentState, ToolFunction


class ExecutionError(RuntimeError):
    def __init__(self, task_id: str, message: str, log: list[TaskExecution]) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.log = log


class TaskExecutor:
    def __init__(self, registry: dict[str, ToolFunction]) -> None:
        self._registry = registry

    async def execute(
        self, plan: ExecutionPlan, state: AgentState, on_event: EventSink | None = None
    ) -> list[TaskExecution]:
        log: list[TaskExecution] = []
        completed: set[str] = set()

        for task in plan.tasks:
            unsatisfied = set(task.depends_on).difference(completed)
            if unsatisfied:
                message = f"dependencies not completed: {sorted(unsatisfied)}"
                entry = TaskExecution(
                    task_id=task.id,
                    description=task.description,
                    tool=task.tool,
                    status="failed",
                    duration_ms=0,
                    error=message,
                )
                log.append(entry)
                raise ExecutionError(task.id, message, log)

            tool = self._registry.get(task.tool)
            if tool is None:
                message = f"tool is not registered: {task.tool}"
                entry = TaskExecution(
                    task_id=task.id,
                    description=task.description,
                    tool=task.tool,
                    status="failed",
                    duration_ms=0,
                    error=message,
                )
                log.append(entry)
                raise ExecutionError(task.id, message, log)

            started = perf_counter()
            await emit(on_event, "task_started", task=task.model_dump())
            try:
                summary = await tool(task, state)
            except Exception as exc:
                elapsed = round((perf_counter() - started) * 1000)
                entry = TaskExecution(
                    task_id=task.id,
                    description=task.description,
                    tool=task.tool,
                    status="failed",
                    duration_ms=elapsed,
                    error=str(exc),
                )
                log.append(entry)
                await emit(on_event, "task_failed", entry=entry.model_dump())
                raise ExecutionError(task.id, str(exc), log) from exc

            elapsed = round((perf_counter() - started) * 1000)
            log.append(
                TaskExecution(
                    task_id=task.id,
                    description=task.description,
                    tool=task.tool,
                    status="completed",
                    duration_ms=elapsed,
                    result_summary=summary,
                )
            )
            completed.add(task.id)
            await emit(on_event, "task_completed", entry=log[-1].model_dump())

        return log

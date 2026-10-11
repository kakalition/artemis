"""Durable A2A ``TaskStore`` backed by Artemis's libSQL database.

Tasks are stored as protobuf JSON in the ``a2a_tasks`` table, so task state,
history and artifacts survive a process restart. The SDK's ``TaskStore``
interface is async; our repositories are sync, so each call is offloaded with
``asyncio.to_thread``. The store is a read model — the DBOS layer is the
durability engine for the work itself.
"""

from __future__ import annotations

import asyncio

from a2a import types as t
from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from google.protobuf import json_format

from artemis.services.runtime import Runtime, repositories


class LibSQLTaskStore(TaskStore):
    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._owner = runtime.settings.owner_id

    @staticmethod
    def _state(task: t.Task) -> str:
        if task.HasField("status"):
            return t.TaskState.Name(task.status.state)
        return "TASK_STATE_UNSPECIFIED"

    # -- sync helpers (run in a worker thread) ---------------------------
    def _save(self, task: t.Task) -> None:
        payload = json_format.MessageToJson(task)
        with repositories(self._runtime) as repos:
            repos.a2a.upsert(
                task.id, self._owner, task.context_id or None, self._state(task), payload
            )

    def _get(self, task_id: str) -> str | None:
        with repositories(self._runtime) as repos:
            record = repos.a2a.get(task_id)
            return record.payload if record is not None else None

    def _delete(self, task_id: str) -> None:
        with repositories(self._runtime) as repos:
            repos.a2a.delete(task_id)

    def _list(self) -> list[str]:
        with repositories(self._runtime) as repos:
            return [record.payload for record in repos.a2a.list()]

    # -- TaskStore interface ---------------------------------------------
    async def save(self, task: t.Task, context: ServerCallContext) -> None:
        await asyncio.to_thread(self._save, task)

    async def get(self, task_id: str, context: ServerCallContext) -> t.Task | None:
        payload = await asyncio.to_thread(self._get, task_id)
        return json_format.Parse(payload, t.Task()) if payload else None

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        await asyncio.to_thread(self._delete, task_id)

    async def list(self, params: t.ListTasksRequest, context: ServerCallContext) -> t.ListTasksResponse:
        payloads = await asyncio.to_thread(self._list)
        tasks = []
        for payload in payloads:
            task = json_format.Parse(payload, t.Task())
            if params.context_id and task.context_id != params.context_id:
                continue
            tasks.append(task)
        total = len(tasks)
        page_size = params.page_size or total or 1
        page = tasks[:page_size]
        return t.ListTasksResponse(tasks=page, page_size=len(page), total_size=total)

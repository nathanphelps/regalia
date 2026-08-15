"""Small Qt thread-pool adapter with structured activity events."""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


@dataclass(slots=True)
class Activity:
    task_id: str
    label: str
    state: str = "running"
    progress: int | None = None
    detail: str = ""
    started: str = ""
    finished: str = ""


class TaskSignals(QObject):
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(str, str)
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function: Callable[..., Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            value = self.function(self.signals.progress.emit)
        except Exception as error:  # noqa: BLE001 - surfaced in Activity, never lost
            try:
                self.signals.error.emit(str(error), traceback.format_exc())
            except RuntimeError:
                pass  # the application closed while this worker was finishing
        else:
            try:
                self.signals.result.emit(value)
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class TaskCoordinator(QObject):
    activity_changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.activities: list[Activity] = []
        self._tasks: dict[str, Task] = {}

    def submit(
        self,
        label: str,
        function: Callable[[Callable[[int, str], None]], Any],
        *,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex
        activity = Activity(
            task_id=task_id,
            label=label,
            started=datetime.now().astimezone().strftime("%H:%M:%S"),
        )
        task = Task(function)
        self.activities.insert(0, activity)
        self._tasks[task_id] = task

        task.signals.progress.connect(
            lambda percent, detail: self._progress(task_id, percent, detail)
        )
        task.signals.result.connect(
            lambda value: self._result(task_id, value, on_result)
        )
        task.signals.error.connect(
            lambda message, trace: self._error(task_id, message, trace, on_error)
        )
        task.signals.finished.connect(lambda: self._finish(task_id))
        self.activity_changed.emit()
        self.busy_changed.emit(True)
        self.pool.start(task)
        return task_id

    def _activity(self, task_id: str) -> Activity | None:
        return next((a for a in self.activities if a.task_id == task_id), None)

    def _progress(self, task_id: str, percent: int, detail: str) -> None:
        if activity := self._activity(task_id):
            activity.progress = percent
            activity.detail = detail
            self.activity_changed.emit()

    def _result(
        self, task_id: str, value: Any, callback: Callable[[Any], None] | None
    ) -> None:
        activity = self._activity(task_id)
        if activity and activity.state == "cancelled":
            return
        if activity:
            activity.state = "complete"
            activity.progress = 100
        if callback:
            callback(value)
        self.activity_changed.emit()

    def _error(
        self,
        task_id: str,
        message: str,
        trace: str,
        callback: Callable[[str, str], None] | None,
    ) -> None:
        activity = self._activity(task_id)
        if activity and activity.state == "cancelled":
            return
        if activity:
            activity.state = "failed"
            activity.detail = message
        if callback:
            callback(message, trace)
        self.activity_changed.emit()

    def _finish(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        if activity := self._activity(task_id):
            activity.finished = datetime.now().astimezone().strftime("%H:%M:%S")
        self.activity_changed.emit()
        self.busy_changed.emit(bool(self._tasks))

    def cancel(self, task_id: str) -> bool:
        activity = self._activity(task_id)
        task = self._tasks.get(task_id)
        if activity is None or task is None or activity.state != "running":
            return False
        activity.state = "cancelled"
        activity.detail = "Result will be ignored"
        activity.finished = datetime.now().astimezone().strftime("%H:%M:%S")
        if self.pool.tryTake(task):
            self._tasks.pop(task_id, None)
            activity.detail = "Cancelled before starting"
            self.busy_changed.emit(bool(self._tasks))
        self.activity_changed.emit()
        return True

    def clear_finished(self) -> None:
        self.activities = [
            activity for activity in self.activities if activity.state == "running"
        ]
        self.activity_changed.emit()

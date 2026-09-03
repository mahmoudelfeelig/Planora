from __future__ import annotations

from typing import Any, Callable, Dict

from PyQt6.QtCore import QObject, QRunnable, QThread, pyqtSignal


class FunctionWorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class FunctionWorker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = FunctionWorkerSignals()

    def run(self) -> None:  # type: ignore[override]
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class ImproveWorker(QObject):
    progress = pyqtSignal(int, int, int, object)
    finished = pyqtSignal(object, int, int)
    error = pyqtSignal(str)

    def __init__(
        self,
        improve_action: Callable[..., Dict[str, Any]],
        inst,
        schedule: Dict[int, Dict[str, Any]],
        *,
        run_mode: str,
        iterations: int,
        max_seconds: float | None,
        focus_term: str = "",
    ):
        super().__init__()
        self.improve_action = improve_action
        self.inst = inst
        self.schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        self.run_mode = str(run_mode)
        self.iterations = int(iterations)
        self.max_seconds = max_seconds
        self.focus_term = str(focus_term)
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:

            def _progress_hook(
                it_done: int, best_pen: int, cur_pen: int, **kwargs: Any
            ) -> None:
                snapshot = (
                    kwargs.get("best_schedule") or kwargs.get("current_schedule") or {}
                )
                self.progress.emit(
                    int(it_done),
                    int(best_pen),
                    int(cur_pen),
                    {
                        int(a_id): dict(info)
                        for a_id, info in dict(snapshot or {}).items()
                    },
                )

            result = self.improve_action(
                self.inst,
                self.schedule,
                run_mode=self.run_mode,
                options={
                    "iterations": int(self.iterations),
                    "max_seconds": self.max_seconds,
                    "progress_every": max(
                        1, min(25, max(1, int(self.iterations) // 100))
                    ),
                },
                focus_term=self.focus_term,
                progress_hook=_progress_hook,
                stop_hook=lambda: bool(self._stop_requested),
            )
            improved = dict(result.get("schedule") or {})
            start_pen = int(dict(result.get("before") or {}).get("soft_penalty", 0))
            final_pen = int(dict(result.get("after") or {}).get("soft_penalty", 0))
            self.finished.emit(
                {int(a_id): dict(info) for a_id, info in improved.items()},
                int(start_pen),
                int(final_pen),
            )
        except Exception as exc:
            self.error.emit(str(exc))

"""Cross-request progress tracking for background analyses.

A background analysis thread writes its progress to a JSON file under the
data-cache dir; Streamlit page reruns poll that file to render live status.
File-based only — no Redis, no shared-session infrastructure (single-user
design).

Derived from TradingAgents-CN's Apache-2.0-licensed
``web/utils/async_progress_tracker.py`` (Redis path removed, stage model
re-pointed at surgo's runner messages).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Real, externally-observable stages of a surgo run, in order. The runner
# emits these exactly; inside "analysing" the live LLM-call counter drives a
# heuristic fraction (engine-internal stages are not observable from outside
# and are not fabricated). estimated_llm_calls is a labelled estimate.
STAGES = [
    ("validating", "校验分析参数"),
    ("init_engine", "初始化分析引擎"),
    ("analysing", "运行分析引擎（多智能体协作）"),
    ("reports", "生成报告"),
]
_STAGE_ORDER = {name: i for i, (name, _) in enumerate(STAGES)}

# Base percentage per completed stage; "analysing" spans 15→85 by LLM calls.
_STAGE_BASE_PCT = {"validating": 8, "init_engine": 15, "analysing": 15, "reports": 100}
_ANALYSING_SPAN = 70  # 15 → 85

# Rough LLM-call estimate: per-analyst tool rounds + fixed debate/trader/risk
# chain. A labelled heuristic (the run's true total is unknown up front).
def estimate_llm_calls(n_analysts: int) -> int:
    return 4 * max(n_analysts, 1) + 10

_LOCK = threading.Lock()
_TRACKERS: dict[str, AsyncProgressTracker] = {}


def new_analysis_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _progress_dir() -> Path:
    from tradingagents.default_config import DEFAULT_CONFIG

    d = Path(DEFAULT_CONFIG["data_cache_dir"]) / "webui_progress"
    d.mkdir(parents=True, exist_ok=True)
    return d


class AsyncProgressTracker:
    """One analysis's progress, persisted as JSON and readable from any thread."""

    def __init__(self, analysis_id: str, analysts: list[str] | None = None):
        self.analysis_id = analysis_id
        self._lock = threading.Lock()
        self._file = _progress_dir() / f"{analysis_id}.json"
        self._data = {
            "analysis_id": analysis_id,
            "status": "running",
            "stage": "validating",
            "stage_label": STAGES[0][1],
            "stage_index": 0,
            "total_stages": len(STAGES),
            "progress_percentage": 5,
            "llm_calls": 0,
            "estimated_llm_calls": estimate_llm_calls(len(analysts or [1])),
            "last_message": "",
            "start_time": time.time(),
            "elapsed_time": 0.0,
            "analysts": analysts or [],
            "raw_results": None,
            "error": None,
        }
        with _LOCK:
            _TRACKERS[analysis_id] = self
        self._save()

    # -- writer side (analysis thread) ------------------------------------

    def update_progress(self, message: str = "", stage: str | None = None):
        with self._lock:
            if stage and stage in _STAGE_ORDER and _STAGE_ORDER[stage] >= _STAGE_ORDER[self._data["stage"]]:
                self._data["stage"] = stage
                self._data["stage_label"] = dict(STAGES)[stage]
                self._data["stage_index"] = _STAGE_ORDER[stage]
            if message:
                self._data["last_message"] = message
            self._refresh_pct_locked()
            self._refresh_elapsed()
            self._save_locked()

    def bump_llm_calls(self):
        with self._lock:
            self._data["llm_calls"] += 1
            self._refresh_pct_locked()
            self._refresh_elapsed()
            self._save_locked()

    def mark_completed(self, results: dict):
        with self._lock:
            self._data["status"] = "completed"
            self._data["stage"] = "reports"
            self._data["stage_label"] = STAGES[-1][1]
            self._data["stage_index"] = len(STAGES) - 1
            self._data["progress_percentage"] = 100
            self._data["raw_results"] = results
            self._refresh_elapsed()
            self._save_locked()
            _TRACKERS.pop(self.analysis_id, None)

    def mark_failed(self, error: str):
        with self._lock:
            self._data["status"] = "failed"
            self._data["error"] = str(error)[:2000]
            self._refresh_elapsed()
            self._save_locked()
            _TRACKERS.pop(self.analysis_id, None)

    # -- internals ---------------------------------------------------------

    def _refresh_pct_locked(self):
        stage = self._data["stage"]
        base = _STAGE_BASE_PCT.get(stage, 0)
        if stage == "analysing" and self._data.get("estimated_llm_calls"):
            frac = min(
                self._data["llm_calls"] / self._data["estimated_llm_calls"], 1.0
            )
            base = base + frac * _ANALYSING_SPAN
        if self._data["status"] != "completed":
            self._data["progress_percentage"] = min(round(base), 95)

    def _refresh_elapsed(self):
        self._data["elapsed_time"] = round(time.time() - self._data["start_time"], 1)

    def _save_locked(self):
        try:
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception as exc:  # progress persistence must never kill a run
            logger.debug("progress save failed for %s: %s", self.analysis_id, exc)

    def _save(self):
        with self._lock:
            self._save_locked()


def get_progress_by_id(analysis_id: str) -> dict | None:
    """Read a run's progress; in-memory trackers first, then the JSON file."""
    with _LOCK:
        tracker = _TRACKERS.get(analysis_id)
    if tracker is not None:
        with tracker._lock:
            return dict(tracker._data)
    f = _progress_dir() / f"{analysis_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def latest_analysis_id() -> str | None:
    """The newest progress file's id — crash-recovery resume pointer."""
    files = sorted(_progress_dir().glob("*.json"))
    return files[-1].stem if files else None

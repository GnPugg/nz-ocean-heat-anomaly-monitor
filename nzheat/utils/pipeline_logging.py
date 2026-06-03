from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_pipeline_log_tables(engine: Engine) -> None:
    """
    Create PostgreSQL tables used for pipeline run logging.

    These tables store one row per pipeline execution and optional step-level
    log events linked to that run.
    """
    statements = [
        """
        CREATE SCHEMA IF NOT EXISTS meta;
        """,
        """
        CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
            run_id UUID PRIMARY KEY,
            pipeline_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            duration_seconds DOUBLE PRECISION,
            message TEXT,
            error_message TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS meta.pipeline_log_events (
            log_id BIGSERIAL PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES meta.pipeline_runs(run_id) ON DELETE CASCADE,
            logged_at TIMESTAMPTZ NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            extra JSONB
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_name
        ON meta.pipeline_runs (pipeline_name);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
        ON meta.pipeline_runs (started_at);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
        ON meta.pipeline_runs (status);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_pipeline_log_events_run_id
        ON meta.pipeline_log_events (run_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_pipeline_log_events_logged_at
        ON meta.pipeline_log_events (logged_at);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


class PipelineRunLogger:
    """
    Write pipeline-level run status and step events to PostgreSQL.

    This is intended for audit logging at pipeline/step level, not for noisy
    row-by-row or grid-cell-level logging.
    """

    def __init__(self, engine: Engine, pipeline_name: str) -> None:
        self.engine = engine
        self.pipeline_name = pipeline_name
        self.run_id: UUID = uuid4()
        self.started_at: datetime | None = None

    def start(self, message: str | None = None) -> UUID:
        ensure_pipeline_log_tables(self.engine)

        self.started_at = datetime.now(timezone.utc)

        with self.engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO meta.pipeline_runs (
                        run_id,
                        pipeline_name,
                        status,
                        started_at,
                        message
                    )
                    VALUES (
                        :run_id,
                        :pipeline_name,
                        :status,
                        :started_at,
                        :message
                    );
                    """),
                {
                    "run_id": str(self.run_id),
                    "pipeline_name": self.pipeline_name,
                    "status": "running",
                    "started_at": self.started_at,
                    "message": message,
                },
            )

        if message:
            self.info(message)

        return self.run_id

    def info(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self.log_event("INFO", message, extra)

    def warning(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self.log_event("WARNING", message, extra)

    def error(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self.log_event("ERROR", message, extra)

    def log_event(
        self,
        level: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO meta.pipeline_log_events (
                        run_id,
                        logged_at,
                        level,
                        message,
                        extra
                    )
                    VALUES (
                        :run_id,
                        :logged_at,
                        :level,
                        :message,
                        CAST(:extra AS jsonb)
                    );
                    """),
                {
                    "run_id": str(self.run_id),
                    "logged_at": datetime.now(timezone.utc),
                    "level": level.upper(),
                    "message": message,
                    "extra": None if extra is None else json.dumps(extra, default=str),
                },
            )

    def finish_success(self, message: str = "Pipeline completed successfully") -> None:
        self._finish(
            status="success",
            message=message,
            error_message=None,
        )
        self.info(message)

    def finish_failed(self, error: Exception) -> None:
        error_message = f"{type(error).__name__}: {error}"

        self.error(
            "Pipeline failed",
            {"error_message": error_message},
        )

        self._finish(
            status="failed",
            message="Pipeline failed",
            error_message=error_message,
        )

    def _finish(
        self,
        *,
        status: str,
        message: str,
        error_message: str | None,
    ) -> None:
        finished_at = datetime.now(timezone.utc)

        if self.started_at is None:
            duration_seconds = None
        else:
            duration_seconds = (finished_at - self.started_at).total_seconds()

        with self.engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE meta.pipeline_runs
                    SET
                        status = :status,
                        finished_at = :finished_at,
                        duration_seconds = :duration_seconds,
                        message = :message,
                        error_message = :error_message
                    WHERE run_id = :run_id;
                    """),
                {
                    "run_id": str(self.run_id),
                    "status": status,
                    "finished_at": finished_at,
                    "duration_seconds": duration_seconds,
                    "message": message,
                    "error_message": error_message,
                },
            )

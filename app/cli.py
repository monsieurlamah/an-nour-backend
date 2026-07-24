"""Console entrypoints exposed via Poetry scripts (e.g. ``poetry run dev``)."""

import asyncio
import subprocess
import sys
import time

import uvicorn

from app.core.config import settings


def dev() -> None:
    """Run the development server with autoreload."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )


def start() -> None:
    """Run the production server (no reload)."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )


def qa() -> None:
    """Run the full quality gate in one command: ``poetry run qa``.

    Steps, in order — stops at the first failure so broken code never reaches
    the next, slower step:
        1. ruff check app tests   (lint + line length + import order)
        2. pytest tests           (unit suite + MySQL integration, auto-skips
                                    the MySQL tests if the dev DB is unreachable)
        3. python -m compileall app (every module must at least byte-compile)
    Prints a pass/fail summary table at the end and exits non-zero if any
    step failed, so it doubles as a CI gate.
    """
    steps = [
        ("ruff", [sys.executable, "-m", "ruff", "check", "app", "tests"]),
        ("pytest", [sys.executable, "-m", "pytest", "tests"]),
        ("compileall", [sys.executable, "-m", "compileall", "-q", "app"]),
    ]

    results: list[tuple[str, bool, float]] = []
    for name, cmd in steps:
        print(f"\n{'=' * 60}\n▶ {name}\n{'=' * 60}")
        start_time = time.monotonic()
        proc = subprocess.run(cmd)
        elapsed = time.monotonic() - start_time
        ok = proc.returncode == 0
        results.append((name, ok, elapsed))
        if not ok:
            break  # fail fast — no point compiling if lint or tests are red

    print(f"\n{'=' * 60}\nRésumé\n{'=' * 60}")
    for name, ok, elapsed in results:
        status = "✅ OK" if ok else "❌ ÉCHEC"
        print(f"  {status:10} {name:12} ({elapsed:.2f}s)")

    all_ok = all(ok for _, ok, _ in results) and len(results) == len(steps)
    if not all_ok:
        print("\n❌ Quality gate FAILED.")
        sys.exit(1)
    print("\n✅ Quality gate PASSED — All checks passed.")


async def _check_overdue_creances() -> None:
    from app.core.logging import get_logger
    from app.database.session import SessionLocal, dispose_engine, init_models
    from app.modules.creances.services import CreanceService

    # This standalone script only imports the creances module directly — far
    # narrower than the real app's import graph (app.main pulls in every
    # router, which transitively registers every model). Without this,
    # SQLAlchemy can't resolve Notification.user_id's FK to "users" because
    # the User model class was never loaded into the mapper registry.
    init_models()
    logger = get_logger("creances.overdue")
    try:
        async with SessionLocal() as db:
            overdue_count, notified = await CreanceService(db).flag_overdue()
            await db.commit()
            logger.info(
                "%d créance(s) passée(s) en retard, %d notification(s) envoyée(s).",
                overdue_count,
                notified,
            )
    finally:
        await dispose_engine()


def check_overdue_creances() -> None:
    """Console entrypoint (`poetry run check-overdue-creances`) — meant to be
    run on a daily schedule (system cron / task scheduler); not triggered by
    any user action, since "overdue" is purely a function of time passing."""
    from app.core.logging import setup_logging

    setup_logging()
    asyncio.run(_check_overdue_creances())

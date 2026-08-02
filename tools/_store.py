"""Small JSON store shared by the goal tools and the handle stores.

Two processes touch these files: poll.py while you are chatting, and daily.py
when the scheduler fires. Both do read-modify-write, so without a lock the
20:00 check-in can silently drop a goal you added at 19:59 - the atomic
rename protects against a torn file, but not against a lost update.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 10.0
LOCK_POLL_SECONDS = 0.05


@contextmanager
def locked(path: Path):
    """Hold an exclusive lock on path for the duration of the block.

    O_CREAT|O_EXCL is atomic on Windows and POSIX alike, so whoever creates
    the lock file wins. If a holder dies without cleaning up, the lock is
    broken once it goes stale: a wedged lock would freeze the bot forever,
    which is a worse failure than the rare lost update it guards against.
    """

    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle = None

    while handle is None:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                logger.warning("Breaking stale lock on %s", path.name)
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            else:
                time.sleep(LOCK_POLL_SECONDS)

    try:
        yield
    finally:
        os.close(handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {} if default is None else default
    except json.JSONDecodeError:
        # Starting fresh here would orphan every other entry without a trace,
        # so keep the damaged file for recovery and say so loudly.
        damaged = path.with_suffix(".json.corrupt")
        path.replace(damaged)
        logger.error("%s was unreadable. Moved it to %s and started fresh.", path.name, damaged)
        return {} if default is None else default


def write_json(path: Path, data: Any) -> None:
    # Write to a temp file and swap it in, so an interrupted write cannot
    # leave a half-written file behind.
    temp_path = path.with_suffix(".json.tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    temp_path.replace(path)


def update_json(path: Path, mutate: Callable[[dict], Any]) -> Any:
    """Read, mutate and write back atomically with respect to other processes.

    mutate receives the loaded data, changes it in place, and returns whatever
    the caller wants back.
    """

    with locked(path):
        data = read_json(path)
        result = mutate(data)
        write_json(path, data)
        return result

import asyncio
from collections.abc import Coroutine

# Event loop тримає лише слабке посилання на задачу: без власного посилання вона може зникнути до завершення.
_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task

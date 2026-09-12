"""One elapsed-time allowance shared by routing, retrieval, calls and retries."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

deadline = ContextVar('inference_deadline', default=None)


class InferenceDeadlineExceeded(RuntimeError):
    code = 'answer_deadline_exceeded'

    def __init__(self):
        super().__init__('The answer could not be completed within the response time limit. Please retry.')


@contextmanager
def bound(seconds):
    end = time.monotonic() + seconds
    existing = deadline.get()
    token = deadline.set(min(existing, end) if existing is not None else end)
    try:
        yield
    finally:
        deadline.reset(token)


def remaining(cap):
    end = deadline.get()
    if end is None:
        return cap
    available = end - time.monotonic()
    if available <= 0:
        raise InferenceDeadlineExceeded()
    return min(cap, available)


def sleep(seconds):
    time.sleep(remaining(seconds))
    remaining(1)

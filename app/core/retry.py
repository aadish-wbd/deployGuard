"""Exponential backoff retry for Bedrock throttling (NFR-7)."""
import time
from functools import wraps
from typing import Callable, Tuple, Type


def retry_with_backoff(
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except retry_on:
                    attempt += 1
                    if attempt > max_retries:
                        raise
                    time.sleep(base_delay_seconds * (2 ** (attempt - 1)))

        return wrapper

    return decorator

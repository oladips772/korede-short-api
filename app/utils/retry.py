import asyncio
import functools
import structlog
import httpx

logger = structlog.get_logger()


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_status_codes: set[int] | None = None,
):
    """Exponential backoff retry decorator for async functions."""
    if retryable_status_codes is None:
        retryable_status_codes = {429, 500, 502, 503, 504}

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status not in retryable_status_codes:
                        logger.error(
                            "Non-retryable HTTP error",
                            func=func.__name__,
                            status=status,
                            attempt=attempt,
                        )
                        raise
                    last_exc = e
                except (httpx.TimeoutException, httpx.ConnectError, TimeoutError) as e:
                    last_exc = e
                except Exception as e:
                    raise

                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.warning(
                    "Retrying after error",
                    func=func.__name__,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                    error=str(last_exc),
                )
                await asyncio.sleep(delay)

            raise last_exc

        return wrapper

    return decorator

"""FlowOps 로그 헬퍼."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any


def log_event(
    logger: logging.Logger,
    level: str,
    message: str,
    **kwargs: Any,
) -> None:
    """key=value 형태로 추가 정보를 붙여 로그 출력.

    출력 예:
        [intent_classifier] 사용자 의도 분류 시작 prompt='GET API 찾아줘'
    """
    extra = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
    full_message = f"{message} {extra}".strip()
    getattr(logger, level)(full_message)


@contextmanager
def log_step(logger: logging.Logger, step_name: str, **kwargs: Any):
    """실행 시간 측정 + 시작/종료 로그.

    출력 예:
        >>> [intent_classifier] LLM 호출 시작
        <<< [intent_classifier] LLM 호출 완료 (320ms)
    """
    start = time.perf_counter()
    extra = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
    logger.info(f">>> [{step_name}] 시작 {extra}".strip())
    try:
        yield
        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"<<< [{step_name}] 완료 ({elapsed:.0f}ms)")
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error(f"<<< [{step_name}] 실패 ({elapsed:.0f}ms) error={e!r}")
        raise
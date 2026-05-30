"""테스트케이스 / 시나리오 공용 중복 판별용 지문(fingerprint) 유틸.

목적:
- 시나리오 step과 기존 테스트케이스가 '같은 테스트'인지 판별해
  중복 생성을 피하고 기존 테스트를 재사용하기 위함.
- testcase / scenario 양쪽이 동일 기준으로 중복을 판단하도록 공용화한다.

지문 구성: (apiId, test_case_type, body 필드 집합)
- 동일 API + 동일 분류(NORMAL / EXCEPTION / BOUNDARY) + 동일 요청 body 필드 구성을
  같은 테스트로 본다.
- 값까지 비교하지 않고 '필드 구성'으로 보는 이유: 같은 종류의 테스트는 예시 값만
  달라도 사실상 같은 케이스이기 때문. (값 단위 비교는 오히려 과도한 미탐을 만듦)
"""

from __future__ import annotations

from typing import Iterable


def make_fingerprint(
    *,
    api_id: str,
    test_case_type: str,
    body_fields: Iterable[str],
) -> frozenset:
    """중복 판별용 지문을 생성.

    Args:
        api_id: 대상 API 식별자 (scenario step의 apiId / TestCase의 endpoint_id)
        test_case_type: 공통 분류 값 (NORMAL / EXCEPTION / BOUNDARY)
        body_fields: 요청 body의 (최상위) 필드 이름들

    Returns:
        해시 가능한 frozenset 지문. set 비교로 중복 판별에 사용.
    """
    keys: set = {("apiId", api_id), ("tct", test_case_type or "")}
    keys.update(("body", f) for f in sorted({f for f in body_fields if f}))
    return frozenset(keys)
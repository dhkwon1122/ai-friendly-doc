"""규칙(Rule) 기본 클래스와 제안(Suggestion) 모델.

새 규칙을 추가하려면 Rule을 상속하고 check()를 구현한 뒤,
rules/__init__.py의 DEFAULT_RULES에 등록하면 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from ..parser import ParsedDoc


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Suggestion:
    rule_id: str
    severity: Severity
    location: str  # 사람이 읽을 수 있는 위치 설명 (예: "'설치 방법' 섹션의 표 #2")
    message: str  # 무엇이 문제인지
    suggestion: str  # 어떻게 고치면 좋을지


class Rule(ABC):
    id: str
    description: str

    @abstractmethod
    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        """문서를 검사해 개선 제안 목록을 반환한다."""

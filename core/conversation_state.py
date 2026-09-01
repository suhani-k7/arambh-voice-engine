from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from utils.logger import AppLogger

logger = AppLogger.get_instance()

class ConversationStage(Enum):
    GREETING          = "greeting"
    COLLECT_NAME      = "collect_name"
    COLLECT_PHONE     = "collect_phone"
    COLLECT_LOAN_AMT  = "collect_loan_amount"
    COLLECT_INCOME    = "collect_income"
    COLLECT_PURPOSE   = "collect_purpose"
    CONFIRMATION      = "confirmation"
    COMPLETED         = "completed"

@dataclass
class BorrowerProfile:
    name: str = ""
    phone: str = ""
    loan_amount: str = ""
    monthly_income: str = ""
    loan_purpose: str = ""

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.name:         missing.append("name")
        if not self.loan_amount:  missing.append("loan_amount")
        if not self.monthly_income: missing.append("monthly_income")
        if not self.loan_purpose: missing.append("loan_purpose")
        return missing

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phone": self.phone,
            "loan_amount": self.loan_amount,
            "monthly_income": self.monthly_income,
            "loan_purpose": self.loan_purpose,
            "is_complete": self.is_complete(),
        }

    def update_from_dict(self, data: dict) -> None:
        if not data:
            return
        if data.get("name"):
            self.name = str(data["name"]).strip()
        if data.get("phone"):
            self.phone = str(data["phone"]).strip()
        if data.get("loan_amount"):
            self.loan_amount = str(data["loan_amount"]).strip()
        if data.get("monthly_income"):
            self.monthly_income = str(data["monthly_income"]).strip()
        if data.get("loan_purpose"):
            self.loan_purpose = str(data["loan_purpose"]).strip()

    @classmethod
    def from_dict(cls, data: dict) -> "BorrowerProfile":
        profile = cls()
        profile.update_from_dict(data)
        return profile


@dataclass
class ConversationState:
    call_sid: str
    stream_sid: str = ""
    stage: ConversationStage = ConversationStage.GREETING
    borrower: BorrowerProfile = field(default_factory=BorrowerProfile)
    history: list[dict] = field(default_factory=list)
    turn_count: int = 0
    status: str = "in_progress"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: str = ""
    duration_seconds: float = 0.0

    def add_user_message(self, text: str) -> None:
        self.history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self.turn_count += 1
        logger.info("User [turn %d]: %s", self.turn_count, text)

    def add_assistant_message(self, text: str) -> None:
        self.history.append({
            "role": "assistant",
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.info("Assistant: %s", text)

    def advance_stage(self) -> None:
        stages = list(ConversationStage)
        current_index = stages.index(self.stage)
        if current_index < len(stages) - 1:
            self.stage = stages[current_index + 1]
            logger.info("Stage advanced to: %s", self.stage.value)

    def complete_call(self) -> None:
        self.status = "completed" if self.borrower.is_complete() else "partial"
        self.ended_at = datetime.now(timezone.utc).isoformat()
        try:
            start_dt = datetime.fromisoformat(self.started_at)
            end_dt = datetime.fromisoformat(self.ended_at)
            self.duration_seconds = round((end_dt - start_dt).total_seconds(), 2)
        except Exception:
            self.duration_seconds = 0.0

    def to_call_dict(self) -> dict:
        return {
            "call_sid": self.call_sid,
            "stream_sid": self.stream_sid,
            "stage": self.stage.value,
            "turn_count": self.turn_count,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
        }
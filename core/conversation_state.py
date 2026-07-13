from dataclasses import dataclass, field
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
        }


@dataclass
class ConversationState:
    call_sid: str
    stage: ConversationStage = ConversationStage.GREETING
    borrower: BorrowerProfile = field(default_factory=BorrowerProfile)
    history: list[dict] = field(default_factory=list)
    turn_count: int = 0

    def add_user_message(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})
        self.turn_count += 1
        logger.info("User [turn %d]: %s", self.turn_count, text)

    def add_assistant_message(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})
        logger.info("Assistant: %s", text)

    def advance_stage(self) -> None:
        stages = list(ConversationStage)
        current_index = stages.index(self.stage)
        if current_index < len(stages) - 1:
            self.stage = stages[current_index + 1]
            logger.info("Stage advanced to: %s", self.stage.value)
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(StrictInput):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RequestInput(StrictInput):
    title: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=5000)
    vendor: str = Field(default="", max_length=200)
    department_id: int | None = Field(default=None, gt=0)
    amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)


class ApprovalInput(StrictInput):
    comment: str = Field(default="", max_length=2000)


class ReturnInput(StrictInput):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A return reason is required.")
        return value.strip()


class ResubmitInput(StrictInput):
    comment: str = Field(default="", max_length=2000)


class UserOutput(BaseModel):
    id: int
    email: str
    full_name: str
    role: Literal["requester", "admin"]
    department_id: int | None
    department_name: str | None


class AuthOutput(BaseModel):
    user: UserOutput
    csrf_token: str

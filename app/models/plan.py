"""Execution plan and deterministic policy outcome contracts."""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.test_case import Browser, ModuleName, Region, TestScope

TEST_ID_PATTERN = r"^[A-Z]{3}-\d{3}$"


class PlanItem(BaseModel):
    """One selected test and the explanation for selecting it."""

    test_id: str = Field(pattern=TEST_ID_PATTERN)
    priority: int = Field(ge=1)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reasons: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reasons_must_be_meaningful(self) -> "PlanItem":
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("selection reasons must not be blank")
        return self


class PolicyViolation(BaseModel):
    """One deterministic rule failure, shaped for the API error model."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    test_id: Optional[str] = None
    field: Optional[str] = None


class PolicyResult(BaseModel):
    """Outcome of deterministic validation, produced by code and never an LLM."""

    passed: bool
    violations: List[PolicyViolation] = Field(default_factory=list)

    @model_validator(mode="after")
    def passing_results_carry_no_violations(self) -> "PolicyResult":
        if self.passed and self.violations:
            raise ValueError("a passing policy result cannot list violations")
        if not self.passed and not self.violations:
            raise ValueError("a failing policy result must explain why")
        return self


class ExecutionPlan(BaseModel):
    """A validated set of catalogued tests plus the context they run under."""

    module: ModuleName
    scope: TestScope
    browser: Browser
    region: Region
    environment: Optional[str] = None
    items: List[PlanItem] = Field(default_factory=list)
    policy_result: Optional[PolicyResult] = None

    @model_validator(mode="after")
    def plan_must_be_internally_consistent(self) -> "ExecutionPlan":
        test_ids = [item.test_id for item in self.items]
        if len(test_ids) != len(set(test_ids)):
            raise ValueError("a plan must not schedule the same test twice")
        if self.is_executable and not self.items:
            raise ValueError("a zero-test plan cannot pass policy validation")
        return self

    @property
    def is_executable(self) -> bool:
        """Report whether policy validation has explicitly cleared this plan."""
        return self.policy_result is not None and self.policy_result.passed

    @property
    def test_ids(self) -> List[str]:
        """Return selected test IDs in priority order."""
        return [item.test_id for item in sorted(self.items, key=lambda i: i.priority)]

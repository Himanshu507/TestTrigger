"""Structured HTTP error mapping.

One envelope for every expected domain error, so a client branches on a code
rather than parsing prose. Unknown failures return a safe generic message: no
stack trace, no prompt text, no credential ever reaches a response.
"""

from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.models.workflow import WorkflowStatus


class ErrorCode:
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NOT_CANCELLABLE = "NOT_CANCELLABLE"
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
    EXECUTION_UNAVAILABLE = "EXECUTION_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    value: Optional[Any] = None


class ErrorBody(BaseModel):
    code: str
    message: str
    workflow_id: Optional[str] = None
    details: List[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """An expected domain error with its HTTP status already decided."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        workflow_id: Optional[str] = None,
        details: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(
            code=code,
            message=message,
            workflow_id=workflow_id,
            details=[ErrorDetail(**detail) for detail in details or []],
        )

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=ErrorEnvelope(error=self.body).model_dump(mode="json"),
        )


# A workflow can finish in a state that is a correct outcome but not an
# executable one. Those map to 4xx/5xx so a client does not read a rejection as
# a successful run, while the workflow itself stays retrievable.
TERMINAL_STATUS_ERRORS = {
    WorkflowStatus.NEEDS_CLARIFICATION: (422, ErrorCode.NEEDS_CLARIFICATION),
    WorkflowStatus.RETRIEVAL_FAILED: (424, ErrorCode.RETRIEVAL_UNAVAILABLE),
    WorkflowStatus.EXECUTION_FAILED: (503, ErrorCode.EXECUTION_UNAVAILABLE),
}


def error_for_state(state: Dict[str, Any]) -> Optional[ApiError]:
    """Map a terminal workflow state onto the documented error response."""
    status = WorkflowStatus(state["status"])
    workflow_id = state["workflow_id"]

    if status is WorkflowStatus.REJECTED:
        policy = state.get("policy_result") or {}
        violations = policy.get("violations") or []
        code = violations[0]["code"] if violations else "REJECTED"
        return ApiError(
            status_code=422,
            code=code,
            message=state.get("summary") or "The request was rejected by policy.",
            workflow_id=workflow_id,
            details=[
                {"field": violation.get("field"), "value": violation.get("message")}
                for violation in violations
            ],
        )

    mapped = TERMINAL_STATUS_ERRORS.get(status)
    if mapped is None:
        return None

    status_code, code = mapped
    details = []
    clarification = state.get("clarification") or {}
    for field in clarification.get("missing_fields", []):
        details.append({"field": field, "value": None})

    return ApiError(
        status_code=status_code,
        code=code,
        message=state.get("summary") or f"The workflow ended as {status.value}.",
        workflow_id=workflow_id,
        details=details,
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return exc.response()


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Report input validation failures in the same envelope as everything else."""
    details = []
    for error in getattr(exc, "errors", list)():
        location = [part for part in error.get("loc", []) if part != "body"]
        details.append(
            {"field": ".".join(str(part) for part in location), "value": error.get("msg")}
        )
    return ApiError(
        status_code=400,
        code=ErrorCode.MALFORMED_REQUEST,
        message="The request could not be processed as submitted.",
        details=details,
    ).response()


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe generic message; diagnostic context stays server-side."""
    return ApiError(
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
    ).response()

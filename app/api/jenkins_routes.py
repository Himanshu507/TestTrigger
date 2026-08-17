"""HTTP surface for the mock Jenkins service.

Exposes the simulated CI system the way a real one would appear: submit a job,
poll it, cancel it. The Execution Agent still calls the service in-process —
there is no reason to add a network hop inside one deployment — but both paths
share the same instance, so what this endpoint reports is exactly what the
workflow saw.

These routes are not part of the product contract under /api/v1. They stand in
for an external system, and exist so the integration boundary is inspectable.
"""

from typing import List, Optional

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.api.errors import ApiError, ErrorEnvelope
from app.integrations.mock_jenkins import (
    JenkinsUnavailableError,
    JobNotFoundError,
    JobRequest,
    MockJenkinsService,
    build_job_request,
)
from app.models.execution import InvalidJobTransitionError

JENKINS_PREFIX = "/jobs"
TAG = "mock jenkins"

jenkins_router = APIRouter(tags=[TAG])


class SubmitJobRequest(BaseModel):
    """A job submission. Only catalog-shaped test IDs are accepted."""

    test_ids: List[str] = Field(min_length=1)
    browser: str = Field(min_length=1)
    region: str = Field(min_length=1)
    environment: Optional[str] = None


class TestResultView(BaseModel):
    test_id: str
    status: str
    duration_ms: int
    failure_reason: Optional[str] = None


class JobView(BaseModel):
    job_id: str
    status: str
    request: JobRequest
    results: List[TestResultView] = Field(default_factory=list)
    error: Optional[str] = None


ERROR_RESPONSES = {
    400: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def _service(request: Request) -> MockJenkinsService:
    service = getattr(request.app.state, "jenkins", None)
    if service is None:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="EXECUTION_UNAVAILABLE",
            message="The mock execution system is not configured.",
        )
    return service


def _view(job) -> JobView:
    return JobView(
        job_id=job.job_id,
        status=job.status.value,
        request=job.request,
        results=[
            TestResultView(
                test_id=result.test_id,
                status=result.status.value,
                duration_ms=result.duration_ms,
                failure_reason=result.failure_reason,
            )
            for result in job.results
        ],
        error=job.error,
    )


@jenkins_router.post(
    JENKINS_PREFIX,
    response_model=JobView,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="Submit a simulated CI job",
)
def submit_job(payload: SubmitJobRequest, request: Request) -> JobView:
    """Queue a job. Outcomes are seeded, so the same request always replays."""
    try:
        job_request = build_job_request(
            test_ids=payload.test_ids,
            browser=payload.browser,
            region=payload.region,
            environment=payload.environment,
        )
    except ValueError as error:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="MALFORMED_REQUEST",
            message=str(error),
        ) from error

    try:
        return _view(_service(request).submit(job_request))
    except JenkinsUnavailableError as error:
        raise _unavailable(error) from error


@jenkins_router.get(
    JENKINS_PREFIX + "/{job_id}",
    response_model=JobView,
    responses=ERROR_RESPONSES,
    summary="Poll a simulated CI job",
)
def get_job(job_id: str, request: Request) -> JobView:
    try:
        return _view(_service(request).get(job_id))
    except JobNotFoundError as error:
        raise _not_found(job_id) from error


@jenkins_router.post(
    JENKINS_PREFIX + "/{job_id}/advance",
    response_model=JobView,
    responses=ERROR_RESPONSES,
    summary="Advance a job one step along its lifecycle",
)
def advance_job(job_id: str, request: Request) -> JobView:
    """Step QUEUED to RUNNING to COMPLETED, as a poller would observe it."""
    try:
        return _view(_service(request).advance(job_id))
    except JobNotFoundError as error:
        raise _not_found(job_id) from error
    except InvalidJobTransitionError as error:
        raise _conflict(error) from error
    except JenkinsUnavailableError as error:
        raise _unavailable(error) from error


@jenkins_router.post(
    JENKINS_PREFIX + "/{job_id}/cancel",
    response_model=JobView,
    responses=ERROR_RESPONSES,
    summary="Cancel an active simulated CI job",
)
def cancel_job(job_id: str, request: Request) -> JobView:
    try:
        return _view(_service(request).cancel(job_id))
    except JobNotFoundError as error:
        raise _not_found(job_id) from error
    except InvalidJobTransitionError as error:
        raise _conflict(error) from error


def _not_found(job_id: str) -> ApiError:
    return ApiError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="JOB_NOT_FOUND",
        message=f"Job {job_id} does not exist.",
    )


def _conflict(error: InvalidJobTransitionError) -> ApiError:
    return ApiError(
        status_code=status.HTTP_409_CONFLICT,
        code="NOT_CANCELLABLE",
        message=str(error),
    )


def _unavailable(error: Exception) -> ApiError:
    return ApiError(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="EXECUTION_UNAVAILABLE",
        message=str(error),
    )

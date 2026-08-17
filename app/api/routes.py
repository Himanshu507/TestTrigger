"""FastAPI routes.

Routes validate input, call orchestration, and map outcomes to HTTP. They hold
no workflow logic: no catalog filtering, no vector queries, no prompts.
"""

from typing import Optional

from fastapi import APIRouter, Header, Request, Response, status

from app.agents.execution import ExecutionAgent, ExecutionError
from app.api.errors import ApiError, ErrorCode, ErrorEnvelope, error_for_state
from app.api.schemas import (
    CancelResponse,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    EventsResponse,
    HealthResponse,
    WorkflowDetailResponse,
)
from app.api.service import WorkflowInspector, check_dependencies
from app.models.execution import InvalidJobTransitionError
from app.orchestration.runner import WorkflowRunner

API_PREFIX = "/api/v1"

ERROR_RESPONSES = {
    400: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}

router = APIRouter()


def _runner(request: Request) -> WorkflowRunner:
    return request.app.state.runner


def _inspector(request: Request) -> WorkflowInspector:
    return request.app.state.inspector


@router.post(
    f"{API_PREFIX}/workflows",
    response_model=CreateWorkflowResponse,
    responses=ERROR_RESPONSES,
    summary="Start a workflow or a dry run",
)
def create_workflow(
    payload: CreateWorkflowRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> CreateWorkflowResponse:
    """Run a request to a terminal state and return its outcome.

    A repeated Idempotency-Key replays the original workflow instead of
    starting a second one.
    """
    runner = _runner(request)

    if idempotency_key:
        existing = runner.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.query != payload.query or existing.dry_run != payload.dry_run:
                raise ApiError(
                    status_code=status.HTTP_409_CONFLICT,
                    code=ErrorCode.DUPLICATE_REQUEST,
                    message="This Idempotency-Key was already used for a different request.",
                    workflow_id=existing.id,
                )
            response.status_code = status.HTTP_200_OK
            return _replay(_inspector(request), existing.id)

    state = runner.run(
        payload.query, dry_run=payload.dry_run, idempotency_key=idempotency_key
    )

    error = error_for_state(state)
    if error is not None:
        raise error

    response.status_code = status.HTTP_201_CREATED
    return CreateWorkflowResponse(
        workflow_id=state["workflow_id"],
        status=state["status"],
        summary=state.get("summary"),
        execution_id=state.get("execution_id"),
    )


def _replay(inspector: WorkflowInspector, workflow_id: str) -> CreateWorkflowResponse:
    """Rebuild the create response from the stored workflow."""
    detail = inspector.detail(workflow_id)
    return CreateWorkflowResponse(
        workflow_id=detail.workflow_id,
        status=detail.status,
        summary=detail.analysis.summary if detail.analysis else None,
        execution_id=detail.execution.execution_id if detail.execution else None,
    )


@router.get(
    f"{API_PREFIX}/workflows/{{workflow_id}}",
    response_model=WorkflowDetailResponse,
    responses=ERROR_RESPONSES,
    summary="Inspect the complete workflow snapshot",
)
def get_workflow(workflow_id: str, request: Request) -> WorkflowDetailResponse:
    detail = _inspector(request).detail(workflow_id)
    if detail is None:
        raise _not_found(workflow_id)
    return detail


@router.get(
    f"{API_PREFIX}/workflows/{{workflow_id}}/events",
    response_model=EventsResponse,
    responses=ERROR_RESPONSES,
    summary="Read the ordered workflow timeline",
)
def get_workflow_events(workflow_id: str, request: Request) -> EventsResponse:
    inspector = _inspector(request)
    if not inspector.exists(workflow_id):
        raise _not_found(workflow_id)
    return EventsResponse(
        workflow_id=workflow_id, events=inspector.timeline(workflow_id)
    )


@router.post(
    f"{API_PREFIX}/workflows/{{workflow_id}}/cancel",
    response_model=CancelResponse,
    responses=ERROR_RESPONSES,
    summary="Cancel an active external job",
)
def cancel_workflow(workflow_id: str, request: Request) -> CancelResponse:
    """Cancel only a job that is still cancellable; a finished one is a conflict."""
    inspector = _inspector(request)
    if not inspector.exists(workflow_id):
        raise _not_found(workflow_id)

    agent: ExecutionAgent = request.app.state.execution_agent
    try:
        execution = agent.cancel(workflow_id)
    except InvalidJobTransitionError as error:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code=ErrorCode.NOT_CANCELLABLE,
            message=f"The job has already finished as {error.current.value}.",
            workflow_id=workflow_id,
        ) from error
    except ExecutionError as error:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code=ErrorCode.NOT_CANCELLABLE,
            message=str(error),
            workflow_id=workflow_id,
        ) from error

    return CancelResponse(
        workflow_id=workflow_id,
        execution_id=execution.external_job_id,
        status=execution.status.value,
    )


@router.get("/health", response_model=HealthResponse, summary="Report readiness")
def health(request: Request, response: Response) -> HealthResponse:
    """Report per-dependency readiness without leaking connection details."""
    dependencies = check_dependencies(
        workflows=request.app.state.workflows,
        store=getattr(request.app.state, "vector_store", None),
        jenkins=getattr(request.app.state, "jenkins", None),
    )
    ready = all(dependency.ready for dependency in dependencies)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ready" if ready else "degraded", dependencies=dependencies
    )


def _not_found(workflow_id: str) -> ApiError:
    return ApiError(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ErrorCode.WORKFLOW_NOT_FOUND,
        message=f"Workflow {workflow_id} does not exist.",
        workflow_id=workflow_id,
    )

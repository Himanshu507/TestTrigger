"""Application assembly.

The one place real collaborators are constructed. Everything below the API
receives them, which is what keeps routes thin and tests able to swap any
boundary.
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agents.analysis import ResultAnalyzer
from app.agents.execution import ExecutionAgent
from app.agents.intent import IntentAgent
from app.agents.retrieval import RetrievalAgent
from app.api.errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.jenkins_routes import jenkins_router
from app.api.routes import router
from app.api.service import WorkflowInspector
from app.catalog import TestCatalog
from app.config import AppSettings
from app.db.database import Database
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    ExecutionRepository,
    PlanRepository,
    WorkflowRepository,
)
from app.integrations.mock_jenkins import MockJenkinsService
from app.llm.embeddings import NullEmbeddingProvider, OpenAIEmbeddingProvider
from app.llm.errors import ProviderNotConfiguredError
from app.llm.openai_provider import OpenAIProvider
from app.llm.provider import NullProvider
from app.observability.logging import configure_logging
from app.orchestration.dependencies import WorkflowDependencies
from app.services.planning_service import PlanningService
from app.orchestration.runner import WorkflowRunner
from app.retrieval.store import ChromaVectorStore

TITLE = "Test Trigger"
DESCRIPTION = (
    "Turns a natural-language testing request into a policy-validated, "
    "executed, and evidence-grounded workflow."
)
VERSION = "0.1.0"
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app(
    settings: Optional[AppSettings] = None,
    *,
    dependencies: Optional[WorkflowDependencies] = None,
    vector_store=None,
    jenkins=None,
) -> FastAPI:
    """Build the API.

    Passing ``dependencies`` skips real provider construction, which is how the
    tests run the full HTTP surface offline.
    """
    settings = settings or AppSettings.from_environment()
    configure_logging()

    if dependencies is None:
        dependencies, vector_store, jenkins = _build_dependencies(settings)

    application = FastAPI(title=TITLE, description=DESCRIPTION, version=VERSION)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    application.state.settings = settings
    application.state.runner = WorkflowRunner(dependencies)
    application.state.workflows = dependencies.workflows
    application.state.execution_agent = dependencies.execution_agent
    application.state.vector_store = vector_store
    application.state.jenkins = jenkins
    application.state.inspector = _build_inspector(dependencies)

    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(router)
    application.include_router(jenkins_router)
    _mount_frontend(application)
    return application


def _mount_frontend(application: FastAPI) -> None:
    """Serve the local chat client alongside the API when it is present.

    Convenience for a single-command local run. The page is still a plain HTTP
    client of /api/v1, so it works equally well served from anywhere else.
    """
    if not FRONTEND_DIR.is_dir():
        return

    application.mount(
        "/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui"
    )

    @application.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")


def _build_inspector(dependencies: WorkflowDependencies) -> WorkflowInspector:
    database = dependencies.workflows.database
    return WorkflowInspector(
        workflows=dependencies.workflows,
        plans=PlanRepository(database),
        executions=ExecutionRepository(database),
        analyses=dependencies.analysis or AnalysisRepository(database),
        events=dependencies.events,
    )


def _build_dependencies(settings: AppSettings):
    """Construct real collaborators from settings.

    A missing API key disables the LLM paths rather than failing startup: intent
    parsing then reports a provider error and analysis uses the deterministic
    fallback, which keeps the deterministic core serviceable.
    """
    database = Database(settings.database_path)
    database.initialize()

    workflows = WorkflowRepository(database)
    catalog = TestCatalog.load_default()
    executions = ExecutionRepository(database)
    # Continue the job sequence, since job state is in-memory but the
    # executions it produced are durable and their IDs are unique.
    jenkins = MockJenkinsService(
        start_number=executions.next_external_job_number()
    )

    try:
        provider = OpenAIProvider(settings, timeout_seconds=settings.llm_timeout_seconds)
        embedder = OpenAIEmbeddingProvider(
            settings, timeout_seconds=settings.llm_timeout_seconds
        )
        configured = True
    except ProviderNotConfiguredError:
        provider = NullProvider()
        embedder = NullEmbeddingProvider()
        configured = False

    store = ChromaVectorStore(settings.chroma_persist_directory)

    dependencies = WorkflowDependencies(
        intent_agent=IntentAgent(
            provider,
            confidence_threshold=settings.intent_confidence_threshold,
            repository=workflows,
        ),
        retrieval_agent=RetrievalAgent(store, embedder, catalog, repository=workflows),
        planning_service=PlanningService(
            catalog, repository=workflows, plan_repository=PlanRepository(database)
        ),
        execution_agent=ExecutionAgent(jenkins, executions, repository=workflows),
        workflows=workflows,
        events=EventRepository(database),
        analysis=AnalysisRepository(database),
        analyzer=(
            ResultAnalyzer(
                provider,
                provider_model=settings.openai_model,
                repository=workflows,
            )
            if configured
            else None
        ),
    )
    return dependencies, store, jenkins


def build() -> FastAPI:
    """Entry point for `uvicorn app.api.main:build --factory`."""
    return create_app()

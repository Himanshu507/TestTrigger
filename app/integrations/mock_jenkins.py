"""Mock Jenkins: a CI-like external system with deterministic outcomes.

Behaves like an external job runner — submit, poll, cancel — so the workflow
exercises a real integration shape without browser automation or a CI server.
Outcomes are seeded, so a demo and a test suite replay identically.
"""

import hashlib
import re
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from app.models.execution import (
    ExecutionResult,
    ExecutionStatus,
    InvalidJobTransitionError,
    TestOutcome,
    can_transition_job,
)
from app.models.plan import TEST_ID_PATTERN

DEFAULT_SEED = "test-trigger"
JOB_ID_PREFIX = "JOB-"
FIRST_JOB_NUMBER = 2001

# One in six simulated tests fails. Low enough that a demo mostly passes, high
# enough that a small plan usually surfaces something to analyze.
FAILURE_THRESHOLD = 42
MIN_DURATION_MS = 400
MAX_DURATION_MS = 2600

FAILURE_REASONS = (
    "assertion failed on the confirmation screen",
    "element not found before timeout",
    "gateway returned 504 during the request",
    "redirect timed out waiting for the callback",
    "unexpected validation error on submit",
)


class JobNotFoundError(LookupError):
    """Raised when a job ID does not exist."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} does not exist")
        self.job_id = job_id


class JenkinsUnavailableError(RuntimeError):
    """Raised when the external system cannot accept or advance a job."""


class JobRequest(BaseModel):
    """What the execution adapter sends. Only catalogued IDs reach it."""

    test_ids: List[str] = Field(min_length=1)
    browser: str = Field(min_length=1)
    region: str = Field(min_length=1)
    environment: Optional[str] = None

    def fingerprint(self) -> str:
        """Stable hash of the request, used to seed reproducible outcomes."""
        parts = [",".join(self.test_ids), self.browser, self.region, self.environment or ""]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class Job(BaseModel):
    """External job state as the mock system reports it."""

    job_id: str
    status: ExecutionStatus
    request: JobRequest
    results: List[ExecutionResult] = Field(default_factory=list)
    error: Optional[str] = None


class MockJenkinsService:
    """In-process stand-in for an external CI system.

    ``seed`` fixes the simulated outcomes. ``force_job_failure`` simulates an
    infrastructure fault so failure paths can be exercised on demand.
    """

    def __init__(
        self,
        *,
        seed: str = DEFAULT_SEED,
        force_job_failure: bool = False,
        unavailable: bool = False,
    ) -> None:
        self._seed = seed
        self._force_job_failure = force_job_failure
        self._unavailable = unavailable
        self._jobs: Dict[str, Job] = {}
        self._next_number = FIRST_JOB_NUMBER

    def submit(self, request: JobRequest) -> Job:
        """Accept a job and return it queued with a stable JOB-* identifier."""
        if self._unavailable:
            raise JenkinsUnavailableError("mock Jenkins is unavailable")

        job_id = f"{JOB_ID_PREFIX}{self._next_number}"
        self._next_number += 1
        job = Job(job_id=job_id, status=ExecutionStatus.QUEUED, request=request)
        self._jobs[job_id] = job
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> Job:
        return self._job(job_id).model_copy(deep=True)

    def advance(self, job_id: str) -> Job:
        """Move a job one step along its lifecycle."""
        job = self._job(job_id)
        if self._unavailable:
            raise JenkinsUnavailableError("mock Jenkins is unavailable")

        if job.status is ExecutionStatus.QUEUED:
            return self._transition(job, ExecutionStatus.RUNNING)

        if job.status is ExecutionStatus.RUNNING:
            if self._force_job_failure:
                job.error = "simulated CI infrastructure failure"
                return self._transition(job, ExecutionStatus.FAILED)
            job.results = self._simulate(job.request)
            return self._transition(job, ExecutionStatus.COMPLETED)

        raise InvalidJobTransitionError(job.status, job.status)

    def run_to_completion(self, job_id: str) -> Job:
        """Drive a job to a terminal state, as the synchronous demo path does."""
        job = self._job(job_id)
        while not job.status.is_terminal:
            self.advance(job_id)
            job = self._job(job_id)
        return job.model_copy(deep=True)

    def cancel(self, job_id: str) -> Job:
        """Cancel an active job. A terminal job cannot be cancelled."""
        job = self._job(job_id)
        if job.status.is_terminal:
            raise InvalidJobTransitionError(job.status, ExecutionStatus.CANCELLED)
        return self._transition(job, ExecutionStatus.CANCELLED)

    def _job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def _transition(self, job: Job, target: ExecutionStatus) -> Job:
        if not can_transition_job(job.status, target):
            raise InvalidJobTransitionError(job.status, target)
        job.status = target
        return job.model_copy(deep=True)

    def _simulate(self, request: JobRequest) -> List[ExecutionResult]:
        """Produce one result per requested test, and nothing else.

        Outcomes derive from the seed and the request, so the same inputs always
        replay the same pass/fail and durations.
        """
        return [
            _simulate_test(self._seed, request.fingerprint(), test_id)
            for test_id in request.test_ids
        ]


def _simulate_test(seed: str, fingerprint: str, test_id: str) -> ExecutionResult:
    digest = hashlib.sha256(f"{seed}|{fingerprint}|{test_id}".encode("utf-8")).digest()

    duration = MIN_DURATION_MS + (
        int.from_bytes(digest[1:3], "big") % (MAX_DURATION_MS - MIN_DURATION_MS)
    )
    if digest[0] >= FAILURE_THRESHOLD:
        return ExecutionResult(
            test_id=test_id, status=TestOutcome.PASSED, duration_ms=duration
        )

    reason = FAILURE_REASONS[digest[3] % len(FAILURE_REASONS)]
    return ExecutionResult(
        test_id=test_id,
        status=TestOutcome.FAILED,
        duration_ms=duration,
        failure_reason=f"{test_id}: {reason}",
    )


def build_job_request(
    *,
    test_ids: Sequence[str],
    browser: str,
    region: str,
    environment: Optional[str] = None,
) -> JobRequest:
    """Build a request, rejecting anything that is not a catalog-shaped ID."""
    for test_id in test_ids:
        if not re.match(TEST_ID_PATTERN, test_id):
            raise ValueError(f"{test_id!r} is not a valid test ID")
    return JobRequest(
        test_ids=list(test_ids),
        browser=browser,
        region=region,
        environment=environment,
    )

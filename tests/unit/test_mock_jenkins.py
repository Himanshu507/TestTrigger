import pytest

from app.integrations.mock_jenkins import (
    JenkinsUnavailableError,
    JobNotFoundError,
    MockJenkinsService,
    build_job_request,
)
from app.models.execution import ExecutionStatus, InvalidJobTransitionError, TestOutcome

TEST_IDS = ["PAY-001", "PAY-003"]


def _request(test_ids=None, **overrides):
    values = {
        "test_ids": TEST_IDS if test_ids is None else test_ids,
        "browser": "chrome",
        "region": "US",
        "environment": "staging",
    }
    values.update(overrides)
    return build_job_request(**values)


def test_submission_returns_a_stable_job_id_and_queued_status() -> None:
    job = MockJenkinsService().submit(_request())

    assert job.job_id.startswith("JOB-")
    assert job.status is ExecutionStatus.QUEUED
    assert job.results == []


def test_job_ids_are_unique_per_submission() -> None:
    service = MockJenkinsService()

    first = service.submit(_request())
    second = service.submit(_request())

    assert first.job_id != second.job_id


def test_lifecycle_runs_queued_to_running_to_completed() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())

    assert service.advance(job.job_id).status is ExecutionStatus.RUNNING
    assert service.advance(job.job_id).status is ExecutionStatus.COMPLETED


def test_a_terminal_job_cannot_restart() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())
    service.run_to_completion(job.job_id)

    with pytest.raises(InvalidJobTransitionError):
        service.advance(job.job_id)


def test_a_terminal_job_cannot_be_cancelled() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())
    service.run_to_completion(job.job_id)

    with pytest.raises(InvalidJobTransitionError):
        service.cancel(job.job_id)


def test_an_active_job_can_be_cancelled() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())

    cancelled = service.cancel(job.job_id)

    assert cancelled.status is ExecutionStatus.CANCELLED
    assert service.get(job.job_id).status is ExecutionStatus.CANCELLED


def test_an_unknown_job_is_reported() -> None:
    with pytest.raises(JobNotFoundError):
        MockJenkinsService().get("JOB-9999")


def test_results_cover_exactly_the_requested_tests() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())

    finished = service.run_to_completion(job.job_id)

    assert [result.test_id for result in finished.results] == TEST_IDS


def test_the_same_seed_and_request_replay_identically() -> None:
    first = MockJenkinsService(seed="demo")
    second = MockJenkinsService(seed="demo")

    left = first.run_to_completion(first.submit(_request()).job_id)
    right = second.run_to_completion(second.submit(_request()).job_id)

    assert [r.model_dump() for r in left.results] == [
        r.model_dump() for r in right.results
    ]


def test_a_different_seed_can_change_outcomes() -> None:
    outcomes = set()
    for seed in [str(index) for index in range(12)]:
        service = MockJenkinsService(seed=seed)
        finished = service.run_to_completion(service.submit(_request()).job_id)
        outcomes.add(tuple(result.status for result in finished.results))

    assert len(outcomes) > 1


def test_a_different_request_changes_outcomes_for_the_same_seed() -> None:
    service = MockJenkinsService(seed="demo")

    us = service.run_to_completion(service.submit(_request()).job_id)
    eu = service.run_to_completion(service.submit(_request(region="EU")).job_id)

    assert [r.duration_ms for r in us.results] != [r.duration_ms for r in eu.results]


def test_failed_results_always_state_a_reason() -> None:
    for seed in [str(index) for index in range(20)]:
        service = MockJenkinsService(seed=seed)
        finished = service.run_to_completion(service.submit(_request()).job_id)
        for result in finished.results:
            if result.status is TestOutcome.FAILED:
                assert result.failure_reason
            else:
                assert result.failure_reason is None


def test_durations_stay_within_the_configured_band() -> None:
    service = MockJenkinsService(seed="demo")
    finished = service.run_to_completion(service.submit(_request()).job_id)

    for result in finished.results:
        assert 400 <= result.duration_ms < 2600


def test_a_forced_infrastructure_failure_ends_the_job_as_failed() -> None:
    service = MockJenkinsService(force_job_failure=True)
    job = service.submit(_request())

    finished = service.run_to_completion(job.job_id)

    assert finished.status is ExecutionStatus.FAILED
    assert finished.results == []
    assert "simulated CI infrastructure failure" in finished.error


def test_an_unavailable_service_refuses_submission() -> None:
    with pytest.raises(JenkinsUnavailableError):
        MockJenkinsService(unavailable=True).submit(_request())


def test_a_request_cannot_contain_an_invented_test_id() -> None:
    with pytest.raises(ValueError, match="not a valid test ID"):
        _request(test_ids=["PAY-001", "made-up"])


def test_an_empty_request_is_rejected() -> None:
    with pytest.raises(ValueError):
        _request(test_ids=[])


def test_reading_a_job_does_not_expose_mutable_internal_state() -> None:
    service = MockJenkinsService()
    job = service.submit(_request())

    snapshot = service.get(job.job_id)
    snapshot.status = ExecutionStatus.COMPLETED

    assert service.get(job.job_id).status is ExecutionStatus.QUEUED

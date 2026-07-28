"""Parsing과 비식별화 단계에 따른 실험 상태 계산을 검증한다."""

from types import SimpleNamespace

from app.db.models.experiment import DeidentificationStatus, ParseStatus
from app.services.experiment_service import calculate_experiment_status


def runs(*statuses: ParseStatus) -> list[SimpleNamespace]:
    return [SimpleNamespace(parse_status=status) for status in statuses]


def deidentified_run(status: DeidentificationStatus) -> SimpleNamespace:
    return SimpleNamespace(
        parse_status=ParseStatus.SUCCEEDED,
        deidentification_status=status,
    )


def test_experiment_status_transitions() -> None:
    assert calculate_experiment_status([]) == "PENDING"
    assert calculate_experiment_status(runs(ParseStatus.PENDING)) == "PENDING"
    assert calculate_experiment_status(runs(ParseStatus.RUNNING, ParseStatus.PENDING)) == "RUNNING"
    assert (
        calculate_experiment_status(runs(ParseStatus.SUCCEEDED, ParseStatus.SUCCEEDED))
        == "COMPLETED"
    )
    assert (
        calculate_experiment_status(runs(ParseStatus.SUCCEEDED, ParseStatus.FAILED))
        == "PARTIALLY_COMPLETED"
    )
    assert calculate_experiment_status(runs(ParseStatus.FAILED)) == "FAILED"
    assert (
        calculate_experiment_status([deidentified_run(DeidentificationStatus.RUNNING)]) == "RUNNING"
    )
    assert (
        calculate_experiment_status([deidentified_run(DeidentificationStatus.FAILED)])
        == "PARTIALLY_COMPLETED"
    )
    assert (
        calculate_experiment_status([deidentified_run(DeidentificationStatus.SUCCEEDED)])
        == "COMPLETED"
    )

"""M1: the alarm record and its JSON shape.

Every time in here is a literal. Nothing reads the clock.
"""

from datetime import datetime, timedelta, timezone

import pytest

from alarm_cli.model import Alarm, AlarmState

IST = timezone(timedelta(hours=5, minutes=30))
FIRE_AT = datetime(2026, 9, 17, 7, 0, tzinfo=IST)
CREATED_AT = datetime(2026, 9, 16, 22, 48, 11, tzinfo=IST)
RESOLVED_AT = datetime(2026, 9, 17, 7, 0, 0, 500000, tzinfo=IST)


def armed(**overrides) -> Alarm:
    fields = {
        "id": 1,
        "message": "standup",
        "fire_at": FIRE_AT,
        "created_at": CREATED_AT,
    }
    return Alarm(**(fields | overrides))


def test_only_armed_is_non_terminal():
    assert not AlarmState.ARMED.is_terminal
    assert all(
        state.is_terminal
        for state in (AlarmState.FIRED, AlarmState.MISSED, AlarmState.CANCELLED)
    )


def test_a_new_alarm_is_armed_and_unresolved():
    alarm = armed()
    assert alarm.state is AlarmState.ARMED
    assert alarm.resolved_at is None


def test_round_trips_through_a_dict():
    alarm = armed().resolve(AlarmState.FIRED, RESOLVED_AT)
    assert Alarm.from_dict(alarm.to_dict()) == alarm


def test_serialises_to_the_documented_shape():
    assert armed().to_dict() == {
        "id": 1,
        "message": "standup",
        "fire_at": "2026-09-17T07:00:00+05:30",
        "created_at": "2026-09-16T22:48:11+05:30",
        "state": "armed",
        "resolved_at": None,
    }


def test_a_message_is_optional():
    alarm = armed(message=None)
    assert alarm.to_dict()["message"] is None
    assert Alarm.from_dict(alarm.to_dict()).message is None


def test_resolving_returns_a_new_alarm_and_leaves_the_old_one_alone():
    alarm = armed()
    fired = alarm.resolve(AlarmState.FIRED, RESOLVED_AT)
    assert fired.state is AlarmState.FIRED
    assert fired.resolved_at == RESOLVED_AT
    assert alarm.state is AlarmState.ARMED
    assert alarm.resolved_at is None


def test_resolving_to_armed_is_refused():
    with pytest.raises(ValueError, match="not a terminal state"):
        armed().resolve(AlarmState.ARMED, RESOLVED_AT)


def test_a_terminal_alarm_cannot_be_resolved_again():
    cancelled = armed().resolve(AlarmState.CANCELLED, RESOLVED_AT)
    with pytest.raises(ValueError, match="already cancelled"):
        cancelled.resolve(AlarmState.FIRED, RESOLVED_AT)


@pytest.mark.parametrize("field", ["fire_at", "created_at"])
def test_a_naive_datetime_is_refused(field):
    # FR-10: an alarm stores an absolute instant, or missed detection across a
    # restart on a later day has nothing to compare.
    with pytest.raises(ValueError, match="no UTC offset"):
        armed(**{field: datetime(2026, 9, 17, 7, 0)})


def test_a_naive_resolved_at_is_refused():
    with pytest.raises(ValueError, match="no UTC offset"):
        Alarm(
            id=1,
            message=None,
            fire_at=FIRE_AT,
            created_at=CREATED_AT,
            state=AlarmState.FIRED,
            resolved_at=datetime(2026, 9, 17, 7, 0),
        )


def test_a_terminal_state_without_resolved_at_is_refused():
    with pytest.raises(ValueError, match="needs a resolved_at"):
        armed(state=AlarmState.FIRED)


def test_an_armed_alarm_with_resolved_at_is_refused():
    with pytest.raises(ValueError, match="cannot have a resolved_at"):
        armed(resolved_at=RESOLVED_AT)


def test_an_alarm_is_immutable():
    with pytest.raises(AttributeError):
        armed().state = AlarmState.FIRED


def _raw(**overrides) -> dict:
    return armed().to_dict() | overrides


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (["not", "an", "object"], "expected an alarm object"),
        ({"id": 1}, "is missing"),
        (_raw(id="1"), "id must be an integer"),
        (_raw(id=True), "id must be an integer"),
        (_raw(message=7), "message must be a string or null"),
        (_raw(state="ringing"), "unknown state"),
        (_raw(fire_at="tomorrow at seven"), "not an ISO 8601 date-time"),
        (_raw(fire_at=1758070800), "must be an ISO 8601 string"),
        (_raw(fire_at="2026-09-17T07:00:00"), "no UTC offset"),
        (_raw(state="fired"), "needs a resolved_at"),
    ],
)
def test_malformed_records_are_refused_with_a_reason(raw, message):
    with pytest.raises(ValueError, match=message):
        Alarm.from_dict(raw)


def test_an_offset_other_than_the_local_one_survives():
    # Whatever offset was in force when the alarm was created is what is stored.
    utc_alarm = armed(fire_at=datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc))
    assert utc_alarm.to_dict()["fire_at"].endswith("+00:00")
    assert Alarm.from_dict(utc_alarm.to_dict()).fire_at == utc_alarm.fire_at

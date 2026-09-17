"""M2: resolving "HH:MM" to the next instant it names.

Every `now` here is a literal. Nothing in this file reads the clock.
"""

from datetime import datetime, timedelta, timezone

import pytest

from alarm_cli.timeparse import ACCEPTED_FORMAT, TimeFormatError, next_occurrence

IST = timezone(timedelta(hours=5, minutes=30))


def at(*args) -> datetime:
    return datetime(*args, tzinfo=IST)


# --- today or tomorrow -----------------------------------------------------


def test_a_time_still_ahead_today_resolves_to_today():
    assert next_occurrence("14:30", at(2026, 9, 16, 9, 5)) == at(2026, 9, 16, 14, 30)


def test_a_time_already_past_resolves_to_tomorrow():
    assert next_occurrence("07:00", at(2026, 9, 16, 22, 48)) == at(2026, 9, 17, 7, 0)


def test_one_minute_before_resolves_to_today():
    assert next_occurrence("14:30", at(2026, 9, 16, 14, 29)) == at(2026, 9, 16, 14, 30)


def test_one_minute_after_resolves_to_tomorrow():
    assert next_occurrence("14:30", at(2026, 9, 16, 14, 31)) == at(2026, 9, 17, 14, 30)


def test_one_second_into_the_minute_resolves_to_tomorrow():
    # 14:30:00 is behind us, however narrowly; an alarm is never set in the past.
    assert next_occurrence("14:30", at(2026, 9, 16, 14, 30, 1)) == at(2026, 9, 17, 14, 30)


def test_exactly_now_resolves_to_tomorrow():
    # "Strictly after", so `alarm add` at the very second named means tomorrow
    # rather than an alarm that is due the instant it is created.
    assert next_occurrence("14:30", at(2026, 9, 16, 14, 30)) == at(2026, 9, 17, 14, 30)


def test_midnight_just_before_resolves_to_today():
    assert next_occurrence("00:00", at(2026, 9, 16, 23, 59, 59)) == at(2026, 9, 17, 0, 0)


def test_midnight_just_after_resolves_to_the_next_day():
    assert next_occurrence("00:00", at(2026, 9, 17, 0, 0, 1)) == at(2026, 9, 18, 0, 0)


def test_the_last_minute_of_the_day():
    assert next_occurrence("23:59", at(2026, 9, 16, 23, 58)) == at(2026, 9, 16, 23, 59)
    assert next_occurrence("23:59", at(2026, 9, 16, 23, 59, 30)) == at(2026, 9, 17, 23, 59)


def test_tomorrow_can_be_the_first_of_the_next_month():
    assert next_occurrence("07:00", at(2026, 9, 30, 8, 0)) == at(2026, 10, 1, 7, 0)


def test_tomorrow_can_be_the_first_of_the_next_year():
    assert next_occurrence("07:00", at(2026, 12, 31, 8, 0)) == at(2027, 1, 1, 7, 0)


def test_tomorrow_can_be_the_29th_of_february():
    assert next_occurrence("07:00", at(2028, 2, 28, 8, 0)) == at(2028, 2, 29, 7, 0)


# --- the shape of the result -----------------------------------------------


def test_the_result_lands_exactly_on_the_minute():
    # The daemon wakes on the minute boundary and nowhere else, so a fire_at
    # with seconds on it would be unreachable.
    resolved = next_occurrence("07:00", at(2026, 9, 16, 22, 48, 11, 123456))
    assert (resolved.second, resolved.microsecond) == (0, 0)


def test_the_result_carries_the_timezone_of_now():
    resolved = next_occurrence("07:00", at(2026, 9, 16, 22, 48))
    assert resolved.tzinfo is IST
    assert resolved.utcoffset() == timedelta(hours=5, minutes=30)


def test_a_different_zone_is_respected_rather_than_replaced():
    utc_now = datetime(2026, 9, 16, 22, 48, tzinfo=timezone.utc)
    resolved = next_occurrence("07:00", utc_now)
    assert resolved == datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc)


# --- rejections ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "7:00",       # not zero-padded
        "0700",       # no separator
        "25:00",      # no such hour
        "24:00",      # midnight is 00:00
        "07:60",      # no such minute
        "",
        "abc",
        "07:0",
        "07:000",
        "7am",
        "07.00",
        "07:00:00",   # seconds cannot be expressed; the daemon wakes on the minute
        "-7:00",
        "07:00pm",
        "１２:３０",   # full-width digits: \d matches them, the time does not exist
    ],
)
def test_malformed_input_is_refused(bad):
    with pytest.raises(TimeFormatError) as exc:
        next_occurrence(bad, at(2026, 9, 16, 9, 5))
    # FR-2: the message has to say what *would* have worked.
    assert ACCEPTED_FORMAT in str(exc.value)


def test_the_rejection_quotes_what_the_user_typed():
    with pytest.raises(TimeFormatError, match="'25:00'"):
        next_occurrence("25:00", at(2026, 9, 16, 9, 5))


def test_an_out_of_range_hour_says_so():
    with pytest.raises(TimeFormatError, match="no hour 25"):
        next_occurrence("25:00", at(2026, 9, 16, 9, 5))


def test_an_out_of_range_minute_says_so():
    with pytest.raises(TimeFormatError, match="no minute 60"):
        next_occurrence("07:60", at(2026, 9, 16, 9, 5))


def test_surrounding_whitespace_is_tolerated():
    # A shell artefact, not a different time.
    assert next_occurrence("  07:00 ", at(2026, 9, 16, 22, 48)) == at(2026, 9, 17, 7, 0)


def test_a_time_format_error_is_a_value_error():
    # So a caller that has not learned about the specific type still catches it.
    assert issubclass(TimeFormatError, ValueError)


def test_a_naive_now_is_a_caller_bug_not_a_user_error():
    with pytest.raises(ValueError) as exc:
        next_occurrence("07:00", datetime(2026, 9, 16, 22, 48))
    assert not isinstance(exc.value, TimeFormatError)

from finance_service.domain.errors import InvalidField


def test_the_error_message_names_the_field_and_the_rule() -> None:
    assert str(InvalidField("cut_day", "range")) == "cut_day: range"

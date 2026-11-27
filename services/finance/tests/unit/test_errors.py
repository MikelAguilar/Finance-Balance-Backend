from finance_service.domain.errors import InvalidField


def test_the_error_message_names_the_field_and_the_rule() -> None:
    assert str(InvalidField("cut_day", "range")) == "cut_day: range"


def test_inside_an_upload_the_error_also_says_where() -> None:
    error = InvalidField("cut_day", "range").at("changes.cards[2]")
    assert (error.path, error.field, error.rule) == ("changes.cards[2]", "cut_day", "range")
    assert str(error) == "changes.cards[2]: cut_day: range"

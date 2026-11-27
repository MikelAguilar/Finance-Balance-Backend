from sqlalchemy import text


def change_seqs(engine) -> list[tuple[str, int]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT 'cards', change_seq FROM finance.cards "
                "UNION ALL SELECT 'movements', change_seq FROM finance.movements "
                "UNION ALL SELECT 'monthly_income', change_seq FROM finance.monthly_income "
                "ORDER BY change_seq"
            )
        )
        return [(table, seq) for table, seq in rows]


def test_every_write_takes_the_next_number_of_one_sequence_shared_by_all_tables(
    engine, insert, make_card, make_movement, make_income
) -> None:
    # El cursor de la descarga es este número: las tres tablas lo comparten para que una sola
    # posición diga hasta dónde llegó la app.
    card = make_card()
    insert("cards", card)
    insert("monthly_income", make_income(user_id=card["user_id"]))
    insert("movements", make_movement(card))

    seqs = change_seqs(engine)
    assert [table for table, _ in seqs] == ["cards", "monthly_income", "movements"]
    numbers = [seq for _, seq in seqs]
    assert numbers == sorted(set(numbers))

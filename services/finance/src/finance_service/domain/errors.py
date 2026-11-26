class InvalidField(ValueError):
    """Un dato de la app que no cumple una regla.

    `field` y `rule` son los mismos que usan los casos compartidos con la app
    (contract/validation-cases.json): así los dos lados rechazan lo mismo y por la misma razón.
    """

    def __init__(self, field: str, rule: str) -> None:
        super().__init__(f"{field}: {rule}")
        self.field = field
        self.rule = rule

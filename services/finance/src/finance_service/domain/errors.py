class InvalidField(ValueError):
    """Un dato de la app que no cumple una regla.

    `field` y `rule` son los mismos que usan los casos compartidos con la app
    (contract/validation-cases.json): así los dos lados rechazan lo mismo y por la misma razón.
    `path` dice dónde está el dato dentro de una subida (`changes.movements[2]`); vacío, en la raíz.
    """

    def __init__(self, field: str, rule: str, path: str = "") -> None:
        super().__init__(f"{path}: {field}: {rule}" if path else f"{field}: {rule}")
        self.field = field
        self.rule = rule
        self.path = path

    def at(self, path: str) -> "InvalidField":
        return InvalidField(self.field, self.rule, path)

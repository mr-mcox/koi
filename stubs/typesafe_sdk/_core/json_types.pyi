from collections.abc import Mapping, Sequence

type JSONValue = str | int | float | bool | Sequence[JSONValue | None] | Mapping[str, JSONValue | None]
type JSONContent = str | Mapping[str, JSONValue | None] | Sequence[JSONValue | None]

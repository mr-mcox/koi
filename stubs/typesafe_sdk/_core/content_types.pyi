from collections.abc import Mapping, Sequence

from typesafe_sdk._core.assets import Asset

type ContentValue = (
    str | int | float | bool | Sequence[ContentValue | None] | Mapping[str, ContentValue | None] | Asset
)
type Content = str | Mapping[str, ContentValue | None] | Sequence[ContentValue | None] | Asset

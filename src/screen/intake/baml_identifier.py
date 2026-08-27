"""Live BAML adapter for the intake identification seam."""

from screen.baml_client.baml_client.sync_client import b
from screen.types import IdentificationResult


class BAMLIdentifier:
    """Calls the generated BAML `IdentifyOpening` function synchronously."""

    def identify_opening(self, page_content: str) -> IdentificationResult:
        result = b.IdentifyOpening(page_content=page_content)
        return IdentificationResult(
            company_name=result.company_name,
            opening_title=result.opening_title,
            opening_notes=result.opening_notes,
        )

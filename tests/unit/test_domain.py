"""Domain validation tests."""

import pytest
from pydantic import ValidationError

from cyclescope.domain.entities import Industry
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.infrastructure.config import Settings


def test_industry_validates_code_and_name() -> None:
    assert Industry(code="STEEL", name="Steel").code == "STEEL"
    with pytest.raises(DomainValidationError):
        Industry(code="steel", name="Steel")
    with pytest.raises(DomainValidationError):
        Industry(code="STEEL", name=" ")


def test_settings_validate_log_level_and_timeout() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")
    with pytest.raises(ValidationError):
        Settings(api_timeout_seconds=0)

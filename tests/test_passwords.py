import pytest

from awas.auth.passwords import verify_password
from awas.services.auth import UserInputError, validate_new_password


def test_unknown_password_hash_is_rejected() -> None:
    assert verify_password("any-password", "not-a-supported-password-hash") is False


def test_short_password_is_allowed() -> None:
    validate_new_password("x", "x")


def test_empty_password_is_rejected() -> None:
    with pytest.raises(UserInputError, match="nicht leer"):
        validate_new_password("", "")


def test_password_confirmation_must_match() -> None:
    with pytest.raises(UserInputError, match="stimmen nicht überein"):
        validate_new_password("x", "y")

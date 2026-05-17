"""Unit tests for the four-step rotation protocol handlers.

Tests run with stub Vault and mock Target clients — no OCI connection required.
"""

import pytest
from oci.exceptions import ServiceError

from rotation import (
    create_pending_version,
    promote_pending_version,
    update_target_system,
    verify_connection,
)
from target_client import MockTargetClient, TargetUpdateError

_FAKE_SECRET_ID = "ocid1.vaultsecret.oc1.us-chicago-1.fake"


class _StubVaultClient:
    """Minimal VaultClient substitute with configurable return values and failure injection."""

    def __init__(
        self,
        *,
        current_version: int = 1,
        current_content: str = "old-credential",
        pending: tuple[int, str] | None = None,
        version_stages: list[str] | None = None,
        fail_get_current_version: bool = False,
        fail_create_pending: bool = False,
        fail_create_pending_runtime: bool = False,
        fail_promote: bool = False,
    ) -> None:
        self._current_version = current_version
        self._current_content = current_content
        self._pending = pending
        self._version_stages = (
            version_stages if version_stages is not None else ["PENDING", "LATEST"]
        )
        self._fail_get_current_version = fail_get_current_version
        self._fail_create_pending = fail_create_pending
        self._fail_create_pending_runtime = fail_create_pending_runtime
        self._fail_promote = fail_promote
        self.create_pending_called: bool = False
        self.promote_called: bool = False
        self.last_created_content: str | None = None

    def get_current_version_number(self, secret_id: str) -> int:
        if self._fail_get_current_version:
            raise ServiceError(
                403, "NotAuthorizedOrNotFound", {}, "injected read failure"
            )
        return self._current_version

    def get_current_secret_content(self, secret_id: str) -> str:
        return self._current_content

    def get_pending_secret(self, secret_id: str) -> tuple[int, str] | None:
        return self._pending

    def get_secret_version_stages(
        self, secret_id: str, version_number: int
    ) -> list[str]:
        return self._version_stages

    def create_pending_version(self, secret_id: str, new_content: str) -> int:
        self.create_pending_called = True
        self.last_created_content = new_content
        if self._fail_create_pending:
            raise ServiceError(500, "InternalServerError", {}, "injected write failure")
        if self._fail_create_pending_runtime:
            raise RuntimeError(
                f"expected new version to be PENDING but got stages ['CURRENT'] "
                f"for secret {secret_id}"
            )
        return 2

    def promote_to_current(self, secret_id: str, version_number: int) -> None:
        self.promote_called = True
        if self._fail_promote:
            raise ServiceError(
                500, "InternalServerError", {}, "injected promote failure"
            )


# --- verify_connection ---


def test_verify_connection_returns_current_version() -> None:
    vault = _StubVaultClient(current_version=5)
    assert verify_connection(_FAKE_SECRET_ID, vault) == 5


def test_verify_connection_propagates_vault_error() -> None:
    vault = _StubVaultClient(fail_get_current_version=True)
    with pytest.raises(ServiceError):
        verify_connection(_FAKE_SECRET_ID, vault)


# --- create_pending_version ---


def test_create_pending_version_creates_when_none_exists() -> None:
    vault = _StubVaultClient(pending=None)
    version_no = create_pending_version(_FAKE_SECRET_ID, vault)
    assert version_no == 2
    assert vault.create_pending_called
    assert vault.last_created_content is not None
    assert len(vault.last_created_content) == 64  # 32 bytes → 64-char hex


def test_create_pending_version_reuses_existing_pending() -> None:
    vault = _StubVaultClient(pending=(7, "existing-credential"))
    version_no = create_pending_version(_FAKE_SECRET_ID, vault)
    assert version_no == 7
    assert not vault.create_pending_called


def test_create_pending_version_new_credentials_differ() -> None:
    """Each call with no existing PENDING generates a distinct credential."""
    vault_a = _StubVaultClient(pending=None)
    vault_b = _StubVaultClient(pending=None)
    create_pending_version(_FAKE_SECRET_ID, vault_a)
    create_pending_version(_FAKE_SECRET_ID, vault_b)
    assert vault_a.last_created_content != vault_b.last_created_content


def test_create_pending_version_propagates_vault_error() -> None:
    vault = _StubVaultClient(pending=None, fail_create_pending=True)
    with pytest.raises(ServiceError):
        create_pending_version(_FAKE_SECRET_ID, vault)


def test_create_pending_version_propagates_runtime_error() -> None:
    vault = _StubVaultClient(pending=None, fail_create_pending_runtime=True)
    with pytest.raises(RuntimeError):
        create_pending_version(_FAKE_SECRET_ID, vault)


# --- update_target_system ---


def test_update_target_system_pushes_pending_credential() -> None:
    vault = _StubVaultClient(
        pending=(2, "new-credential"), current_content="old-credential"
    )
    target = MockTargetClient(initial_credential="old-credential")

    version_no = update_target_system(_FAKE_SECRET_ID, vault, target)

    assert version_no == 2
    assert target.current_credential == "new-credential"
    assert target.update_count == 1


def test_update_target_system_raises_when_no_pending() -> None:
    vault = _StubVaultClient(pending=None)
    target = MockTargetClient()

    with pytest.raises(RuntimeError, match="no PENDING version"):
        update_target_system(_FAKE_SECRET_ID, vault, target)

    assert target.update_count == 0


def test_update_target_system_propagates_target_error() -> None:
    vault = _StubVaultClient(pending=(2, "new-credential"))
    target = MockTargetClient()
    target.fail_on_next_update = True

    with pytest.raises(TargetUpdateError):
        update_target_system(_FAKE_SECRET_ID, vault, target)

    assert target.update_count == 0


# --- promote_pending_version ---


def test_promote_pending_version_promotes_pending_version() -> None:
    vault = _StubVaultClient(version_stages=["PENDING", "LATEST"])
    version_no = promote_pending_version(_FAKE_SECRET_ID, 2, vault)
    assert version_no == 2
    assert vault.promote_called


def test_promote_pending_version_already_current_returns_without_promote() -> None:
    """Version already CURRENT is a success (retry convergence)."""
    vault = _StubVaultClient(version_stages=["CURRENT"])
    version_no = promote_pending_version(_FAKE_SECRET_ID, 2, vault)
    assert version_no == 2
    assert not vault.promote_called


def test_promote_pending_version_unexpected_stage_raises() -> None:
    """Version in DEPRECATED or other unexpected stage raises RuntimeError."""
    vault = _StubVaultClient(version_stages=["DEPRECATED"])
    with pytest.raises(RuntimeError, match="unexpected stages"):
        promote_pending_version(_FAKE_SECRET_ID, 2, vault)


def test_promote_pending_version_propagates_vault_error() -> None:
    vault = _StubVaultClient(version_stages=["PENDING", "LATEST"], fail_promote=True)
    with pytest.raises(ServiceError):
        promote_pending_version(_FAKE_SECRET_ID, 2, vault)

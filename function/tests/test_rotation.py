"""Unit tests for the rotation state machine.

Tests run with stub Vault and mock Target clients — no OCI connection required.
"""

import pytest
from oci.exceptions import ServiceError

from rotation import rotate
from target_client import MockTargetClient, TargetUpdateError


class _StubVaultClient:
    """Minimal VaultClient substitute that records calls and supports failure injection."""

    def __init__(
        self,
        current_content: str = "old-credential",
        fail_create_pending: bool = False,
        fail_create_pending_with_runtime_error: bool = False,
        fail_promote: bool = False,
    ) -> None:
        self._current_content = current_content
        self._fail_create_pending = fail_create_pending
        self._fail_create_pending_with_runtime_error = (
            fail_create_pending_with_runtime_error
        )
        self._fail_promote = fail_promote
        # Observation state
        self.create_pending_called: bool = False
        self.pending_version_number: int | None = None
        self.promote_called: bool = False

    def get_current_secret_content(self, secret_id: str) -> str:
        return self._current_content

    def create_pending_version(self, secret_id: str, new_content: str) -> int:
        self.create_pending_called = True
        if self._fail_create_pending:
            raise ServiceError(
                500, "InternalServerError", {}, "injected vault pending write failure"
            )
        if self._fail_create_pending_with_runtime_error:
            raise RuntimeError(
                f"expected new version to be PENDING but got stages ['CURRENT'] "
                f"for secret {secret_id} — secret may lack a rotation_config"
            )
        self.pending_version_number = 2
        return self.pending_version_number

    def promote_to_current(self, secret_id: str, version_number: int) -> None:
        self.promote_called = True
        if self._fail_promote:
            raise ServiceError(
                500, "InternalServerError", {}, "injected vault promote failure"
            )


_FAKE_SECRET_ID = "ocid1.vaultsecret.oc1.us-chicago-1.fake"


def test_rotate_happy_path() -> None:
    """Full rotation succeeds: target and Vault both reflect the new credential."""
    vault = _StubVaultClient(current_content="old-credential")
    target = MockTargetClient(initial_credential="old-credential")

    new_cred = rotate(
        secret_id=_FAKE_SECRET_ID, vault_client=vault, target_client=target
    )

    assert len(new_cred) == 64
    assert new_cred != "old-credential"
    assert target.current_credential == new_cred
    assert vault.create_pending_called
    assert vault.promote_called
    assert target.update_count == 1


def test_rotate_create_pending_fails() -> None:
    """Vault PENDING write fails before target is touched — state is consistent."""
    vault = _StubVaultClient(current_content="old-credential", fail_create_pending=True)
    target = MockTargetClient(initial_credential="old-credential")

    with pytest.raises(ServiceError):
        rotate(secret_id=_FAKE_SECRET_ID, vault_client=vault, target_client=target)

    assert vault.create_pending_called
    assert not vault.promote_called
    assert target.current_credential == "old-credential"
    assert target.update_count == 0


def test_rotate_create_pending_raises_runtime_error() -> None:
    """create_pending_version raises RuntimeError (e.g. missing rotation_config).

    Target is never touched — state is consistent and safe to retry after
    fixing the rotation_config.
    """
    vault = _StubVaultClient(
        current_content="old-credential",
        fail_create_pending_with_runtime_error=True,
    )
    target = MockTargetClient(initial_credential="old-credential")

    with pytest.raises(RuntimeError, match="rotation_config"):
        rotate(secret_id=_FAKE_SECRET_ID, vault_client=vault, target_client=target)

    assert vault.create_pending_called
    assert not vault.promote_called
    assert target.current_credential == "old-credential"
    assert target.update_count == 0


def test_rotate_target_fails_after_pending_created() -> None:
    """Target update fails after PENDING was created.

    PENDING version exists in Vault, but CURRENT is unchanged and the target
    still holds the old credential — consistent from the target's perspective.
    Re-triggering rotation creates a new PENDING (demoting the orphan) and
    retries cleanly.
    """
    vault = _StubVaultClient(current_content="old-credential")
    target = MockTargetClient(initial_credential="old-credential")
    target.fail_on_next_update = True

    with pytest.raises(TargetUpdateError):
        rotate(secret_id=_FAKE_SECRET_ID, vault_client=vault, target_client=target)

    assert vault.create_pending_called
    assert not vault.promote_called
    assert target.current_credential == "old-credential"
    assert target.update_count == 0


def test_rotate_promote_fails_after_target_update() -> None:
    """Vault promote fails after target was already updated — demonstrates inconsistent state.

    Target holds the new credential; Vault CURRENT still reflects the old one.
    Recovery path: re-trigger rotation. The target accepts an overwrite, and the
    promote is retried, restoring consistency.
    """
    vault = _StubVaultClient(current_content="old-credential", fail_promote=True)
    target = MockTargetClient(initial_credential="old-credential")

    with pytest.raises(ServiceError):
        rotate(secret_id=_FAKE_SECRET_ID, vault_client=vault, target_client=target)

    assert vault.create_pending_called
    assert vault.promote_called
    # Target holds the new credential while Vault CURRENT still reflects the old one.
    assert target.current_credential != "old-credential"
    assert target.update_count == 1

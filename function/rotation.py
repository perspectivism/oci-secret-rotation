"""Core rotation state machine.

rotate() orchestrates five phases:
  1. Read the current secret from Vault (CURRENT version)
  2. Generate a new credential
  3. Create a PENDING version in Vault with the new credential
  4. Update the target system with the new credential
  5. Promote the PENDING version to CURRENT

Failure handling:
  ServiceError (phase 3, create_pending) — target untouched; Vault unchanged;
    both sides hold the old credential; safe to retry.
  TargetUpdateError (phase 4) — PENDING version exists in Vault but CURRENT
    still holds the old credential; target unchanged. Re-triggering rotation
    creates a new PENDING (OCI demotes the orphaned PENDING to DEPRECATED)
    and retries from a clean state.
  ServiceError (phase 5, promote) — target holds the new credential but Vault
    is stuck at PENDING; CURRENT still reflects the old credential. Re-triggering
    rotation recovers: the target accepts the overwrite and the promote is retried.
"""

import logging
import secrets

from oci.exceptions import ServiceError

from target_client import TargetClient, TargetUpdateError
from vault_client import VaultClient

logger = logging.getLogger(__name__)

# 32 bytes → 64-character lowercase hex string. Long enough for any secret
# store and short enough to fit within OCI Vault's content size limits.
_CREDENTIAL_BYTE_LENGTH = 32


def rotate(
    secret_id: str,
    vault_client: VaultClient,
    target_client: TargetClient,
) -> str:
    """Execute one rotation cycle for a secret.

    Reads the current secret, generates a new credential, updates the target,
    then writes the new credential to Vault.

    Args:
        secret_id: OCID of the secret to rotate.
        vault_client: Vault wrapper for read/write operations.
        target_client: Target system wrapper for credential update.

    Returns:
        The new credential (plaintext). Returned so callers and tests can
        assert the value without reading back from Vault.

    Raises:
        oci.exceptions.ServiceError: Vault API call failed. If raised during
            create_pending (phase 3), state is consistent and rotation can be
            safely retried. If raised during promote (phase 5), the target
            already holds the new credential — re-trigger rotation to recover.
        TargetUpdateError: Target rejected the update (phase 4). A PENDING
            version exists in Vault but CURRENT is unchanged. Re-triggering
            rotation creates a fresh PENDING and retries cleanly.
    """
    logger.info("rotation started", extra={"secret_id": secret_id, "phase": "start"})

    # Phase 1: Read the current credential from Vault (CURRENT version).
    # Passed to update_credential so targets that require the current value
    # to authenticate a change (e.g. ALTER USER ... REPLACE ...) can use it.
    current_credential = vault_client.get_current_secret_content(secret_id)
    logger.info("current secret read", extra={"secret_id": secret_id, "phase": "read"})

    # Phase 2: Generate a new credential.
    new_credential = secrets.token_hex(_CREDENTIAL_BYTE_LENGTH)

    # Phase 3: Write the new credential to Vault as a PENDING version.
    # If this raises, neither the target nor CURRENT has been touched — safe
    # to retry. OCI demotes any existing PENDING to DEPRECATED on a new write,
    # so retries are idempotent.
    logger.info(
        "creating pending vault version",
        extra={"secret_id": secret_id, "phase": "vault_pending"},
    )
    try:
        pending_version = vault_client.create_pending_version(secret_id, new_credential)
    except ServiceError:
        logger.error(
            "vault pending write failed — target unchanged, state is consistent, safe to retry",
            extra={"secret_id": secret_id, "phase": "vault_pending_failed"},
        )
        raise

    # Phase 4: Push the new credential to the target.
    # If this raises, PENDING exists in Vault but CURRENT still holds the old
    # credential, so the target is consistent with CURRENT. Re-triggering
    # rotation creates a new PENDING (demoting the orphan) and retries cleanly.
    logger.info(
        "updating target",
        extra={"secret_id": secret_id, "phase": "target_update"},
    )
    try:
        target_client.update_credential(new_credential, current_credential)
    except TargetUpdateError:
        logger.error(
            "target update failed — vault has orphaned PENDING version, "
            "CURRENT unchanged. Re-trigger rotation to recover.",
            extra={"secret_id": secret_id, "phase": "target_update_failed"},
        )
        raise

    logger.info(
        "target updated, promoting vault version to current",
        extra={"secret_id": secret_id, "phase": "vault_promote"},
    )

    # Phase 5: Promote the PENDING version to CURRENT.
    # If this raises, the target already holds the new credential but Vault
    # CURRENT still reflects the old one. Re-triggering rotation recovers:
    # the target accepts the overwrite and the promote is retried.
    try:
        vault_client.promote_to_current(secret_id, pending_version)
    except ServiceError:
        logger.error(
            "vault promote failed after target update — INCONSISTENT STATE: "
            "target holds new credential, vault CURRENT holds old. "
            "Re-trigger rotation to recover.",
            extra={"secret_id": secret_id, "phase": "vault_promote_failed"},
        )
        raise

    logger.info(
        "rotation complete",
        extra={"secret_id": secret_id, "phase": "complete"},
    )
    return new_credential

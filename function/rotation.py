"""OCI Vault native rotation — four-step protocol handlers.

Each function corresponds to one step in OCI's rotation_config protocol:

  VERIFY_CONNECTION      → verify_connection()
  CREATE_PENDING_VERSION → create_pending_version()
  UPDATE_TARGET_SYSTEM   → update_target_system()
  PROMOTE_PENDING_VERSION → promote_pending_version()

func.py calls these after parsing the SecretRotationInput payload and maps
the return value to a SecretRotationOutput response. Step functions raise on
failure and return an int (versionNo) on success — no FDK or HTTP concerns.

Failure handling and retry behaviour:
  verify_connection(): read-only; safe to retry at any time.
  create_pending_version(): idempotent — if a PENDING version already exists
    it is reused without generating a new credential. OCI may call this step
    more than once; retries converge on the same version.
  update_target_system(): reads the PENDING credential from Vault at call
    time. ObjectStorageTargetClient overwrites unconditionally, so retries
    are safe for this reference target. Real targets should add target-specific
    retry/idempotency checks appropriate to their credential API.
  promote_pending_version(): three-way stage check before promoting:
    CURRENT → already done, success (retry convergence)
    PENDING → promote via vault.promote_to_current()
    other   → RuntimeError (unexpected state, fail loudly)
"""

import logging
import secrets

from target_client import TargetClient
from vault_client import VaultClient

logger = logging.getLogger(__name__)

# 32 bytes → 64-character lowercase hex string. Long enough for any secret
# store and short enough to fit within OCI Vault's content size limits.
_CREDENTIAL_BYTE_LENGTH = 32


def verify_connection(secret_id: str, vault: VaultClient) -> int:
    """VERIFY_CONNECTION: confirm Vault read access and return current version.

    OCI calls this step first. If it fails, rotation does not proceed.

    Object Storage is a write-only reference target and cannot authenticate using
    the credential it stores, so target connectivity is not verified here.
    VERIFY_CONNECTION validates that the Function's Resource Principal can
    read the secret from Vault — the readiness gate this reference target can validate honestly.

    Args:
        secret_id: OCID of the secret.
        vault: Vault client.

    Returns:
        Current secret version number.

    Raises:
        oci.exceptions.ServiceError: On Vault read failure.
    """
    version_no = vault.get_current_version_number(secret_id)
    logger.info(
        "VERIFY_CONNECTION succeeded",
        extra={"secret_id": secret_id, "version_no": version_no},
    )
    return version_no


def create_pending_version(secret_id: str, vault: VaultClient) -> int:
    """CREATE_PENDING_VERSION: create a PENDING secret version, or reuse one.

    Idempotent: if a PENDING version already exists it is returned without
    generating a new credential. This ensures OCI retries converge on the
    same version rather than accumulating orphaned credentials.

    Args:
        secret_id: OCID of the secret.
        vault: Vault client.

    Returns:
        Version number of the PENDING version (existing or newly created).

    Raises:
        oci.exceptions.ServiceError: On Vault read or write failure.
        RuntimeError: If the newly created version is not in PENDING stage.
    """
    existing = vault.get_pending_secret(secret_id)
    if existing is not None:
        version_no, _ = existing
        logger.info(
            "reusing existing PENDING version",
            extra={"secret_id": secret_id, "version_no": version_no},
        )
        return version_no

    new_credential = secrets.token_hex(_CREDENTIAL_BYTE_LENGTH)
    version_no = vault.create_pending_version(secret_id, new_credential)
    logger.info(
        "CREATE_PENDING_VERSION succeeded",
        extra={"secret_id": secret_id, "version_no": version_no},
    )
    return version_no


def update_target_system(
    secret_id: str,
    vault: VaultClient,
    target: TargetClient,
) -> int:
    """UPDATE_TARGET_SYSTEM: push the PENDING credential to the target system.

    Reads the PENDING version content from Vault at call time so no secret
    material passes through the OCI step payload. The current credential is
    also read from Vault for targets that require it to authenticate the
    change (e.g. ALTER USER ... REPLACE ...). ObjectStorageTargetClient
    ignores current_value and overwrites unconditionally.

    Args:
        secret_id: OCID of the secret.
        vault: Vault client.
        target: Target system client.

    Returns:
        Version number of the PENDING version that was pushed to the target.

    Raises:
        RuntimeError: If no PENDING version exists in Vault. This indicates
            CREATE_PENDING_VERSION did not run or did not succeed.
        oci.exceptions.ServiceError: On Vault read failure.
        TargetUpdateError: If the target rejects the credential update.
    """
    pending = vault.get_pending_secret(secret_id)
    if pending is None:
        raise RuntimeError(
            f"UPDATE_TARGET_SYSTEM: no PENDING version found for secret {secret_id}; "
            "CREATE_PENDING_VERSION must succeed before this step"
        )
    version_no, new_credential = pending
    current_credential = vault.get_current_secret_content(secret_id)
    target.update_credential(new_credential, current_credential)
    logger.info(
        "UPDATE_TARGET_SYSTEM succeeded",
        extra={"secret_id": secret_id, "version_no": version_no},
    )
    return version_no


def promote_pending_version(
    secret_id: str,
    version_no: int,
    vault: VaultClient,
) -> int:
    """PROMOTE_PENDING_VERSION: promote the given version to CURRENT.

    Three-way stage check:
      CURRENT → already promoted, return success (retry convergence).
      PENDING → promote via vault.promote_to_current().
      other   → RuntimeError; version is in an unexpected stage
                (DEPRECATED, PREVIOUS, etc.) — fail loudly rather than
                attempt a promote that would silently misbehave.

    Args:
        secret_id: OCID of the secret.
        version_no: Version number to promote. Supplied by OCI in the step
            payload; must match the version created in CREATE_PENDING_VERSION.
        vault: Vault client.

    Returns:
        version_no (unchanged).

    Raises:
        oci.exceptions.ServiceError: On Vault read or promote failure.
        RuntimeError: If version_no is in an unexpected stage.
    """
    stages = vault.get_secret_version_stages(secret_id, version_no)

    if "CURRENT" in stages:
        logger.info(
            "version already CURRENT, promotion already done",
            extra={"secret_id": secret_id, "version_no": version_no},
        )
        return version_no

    if "PENDING" not in stages:
        raise RuntimeError(
            f"PROMOTE_PENDING_VERSION: version {version_no} has unexpected stages "
            f"{stages} for secret {secret_id}; expected PENDING or CURRENT"
        )

    vault.promote_to_current(secret_id, version_no)
    logger.info(
        "PROMOTE_PENDING_VERSION succeeded",
        extra={"secret_id": secret_id, "version_no": version_no},
    )
    return version_no

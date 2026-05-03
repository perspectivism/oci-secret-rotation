"""OCI Vault and Secrets SDK wrapper used by the rotation handler."""

import base64
import logging

import oci
from oci.exceptions import ServiceError
from oci.secrets import SecretsClient
from oci.vault import VaultsClient
from oci.vault.models import Base64SecretContentDetails, UpdateSecretDetails

logger = logging.getLogger(__name__)

# Maximum retries for update_secret when the secret is transiently UPDATING.
_UPDATE_MAX_RETRIES = 3


class VaultClient:
    """Wraps the OCI Vault read/write operations needed by the rotation handler.

    Authenticates via Resource Principal by default — the correct signer for a
    deployed OCI Function. Pass an explicit signer to use config-file auth
    during local development or testing.
    """

    def __init__(self, signer: object | None = None) -> None:
        """Initialise the Secrets and Vaults client pair.

        Args:
            signer: OCI request signer. Defaults to Resource Principal.
        """
        if signer is None:
            signer = oci.auth.signers.get_resource_principals_signer()
        # SecretsClient reads secret bundle values (plaintext retrieval endpoint).
        # VaultsClient manages secret metadata and versions (management endpoint).
        self._secrets = SecretsClient(config={}, signer=signer)
        self._vaults = VaultsClient(config={}, signer=signer)

    def _wait_until_active(self, secret_id: str) -> None:
        """Poll until the secret lifecycle_state returns to ACTIVE.

        OCI's update_secret is asynchronous — the secret enters UPDATING state
        briefly after the call returns. Subsequent calls (list_secret_versions,
        promote, another update_secret) will 409 if made while UPDATING.
        """
        oci.wait_until(
            self._vaults,
            self._vaults.get_secret(secret_id=secret_id),
            "lifecycle_state",
            "ACTIVE",
            max_wait_seconds=30,
        )

    def _update_secret_with_retry(
        self, secret_id: str, update_details: UpdateSecretDetails
    ) -> None:
        """Call update_secret, retrying on transient 409 UPDATING responses.

        OCI returns 409 IncorrectState when update_secret is called while the
        secret is already in UPDATING state. This waits for ACTIVE and retries
        up to _UPDATE_MAX_RETRIES times before giving up.
        """
        for attempt in range(1, _UPDATE_MAX_RETRIES + 1):
            try:
                self._vaults.update_secret(
                    secret_id=secret_id,
                    update_secret_details=update_details,
                )
                return
            except ServiceError as exc:
                if (
                    exc.status == 409
                    and exc.code == "IncorrectState"
                    and "UPDATING" in (exc.message or "")
                    and attempt < _UPDATE_MAX_RETRIES
                ):
                    logger.warning(
                        "secret is UPDATING, waiting for ACTIVE before retry",
                        extra={
                            "secret_id": secret_id,
                            "attempt": attempt,
                            "max_retries": _UPDATE_MAX_RETRIES,
                        },
                    )
                    self._wait_until_active(secret_id)
                else:
                    raise

    def get_current_secret_content(self, secret_id: str) -> str:
        """Return the decoded plaintext of the CURRENT secret version.

        Args:
            secret_id: OCID of the secret to read.

        Returns:
            Decoded string value of the current secret version.

        Raises:
            oci.exceptions.ServiceError: On non-2xx response from Vault
                (e.g. secret not found, permission denied).
        """
        logger.debug("reading current secret bundle", extra={"secret_id": secret_id})
        try:
            bundle = self._secrets.get_secret_bundle(secret_id=secret_id)
        except ServiceError as exc:
            logger.error(
                "failed to read secret bundle",
                extra={"secret_id": secret_id, "status": exc.status, "code": exc.code},
            )
            raise
        raw = bundle.data.secret_bundle_content.content
        return base64.b64decode(raw).decode()

    def create_pending_version(self, secret_id: str, new_content: str) -> int:
        """Create a new PENDING secret version with the given content.

        OCI Vault automatically moves any existing PENDING version to
        DEPRECATED when a new one is created (empirically verified) — so this is safe to call on
        retry after a previous partial rotation. Raises RuntimeError if the
        new version is not PENDING — the stage is set explicitly, so this
        would indicate an unexpected OCI API behavior.

        Args:
            secret_id: OCID of the secret to update.
            new_content: Plaintext string to store. Base64-encoded before
                         transmission; Vault stores and returns it encoded.

        Returns:
            The version number of the newly created PENDING version. Pass
            this to promote_to_current() to complete the rotation.

        Raises:
            oci.exceptions.ServiceError: On non-2xx response from Vault.
            RuntimeError: If the updated secret version cannot be found or is
                not PENDING.
        """
        encoded = base64.b64encode(new_content.encode()).decode()
        update_details = UpdateSecretDetails(
            secret_content=Base64SecretContentDetails(
                content_type=Base64SecretContentDetails.CONTENT_TYPE_BASE64,
                stage=Base64SecretContentDetails.STAGE_PENDING,
                content=encoded,
            )
        )
        try:
            self._update_secret_with_retry(secret_id, update_details)
        except ServiceError as exc:
            logger.error(
                "failed to create pending secret version",
                extra={"secret_id": secret_id, "status": exc.status, "code": exc.code},
            )
            raise

        self._wait_until_active(secret_id)

        try:
            versions = self._vaults.list_secret_versions(secret_id=secret_id).data
        except ServiceError as exc:
            logger.error(
                "secret update succeeded but failed to list secret versions",
                extra={"secret_id": secret_id, "status": exc.status, "code": exc.code},
            )
            raise

        latest = next(
            (v for v in versions if "LATEST" in (v.stages or [])),
            None,
        )
        if latest is None:
            raise RuntimeError(
                f"no LATEST version found after update_secret for secret {secret_id}"
            )
        if "PENDING" not in (latest.stages or []):
            raise RuntimeError(
                f"expected new version to be PENDING but got stages {latest.stages} "
                f"for secret {secret_id}; expected explicit PENDING stage to be honored"
            )
        logger.info(
            "new PENDING secret version created",
            extra={
                "secret_id": secret_id,
                "version": latest.version_number,
                "stages": latest.stages,
            },
        )
        return latest.version_number

    def promote_to_current(self, secret_id: str, version_number: int) -> None:
        """Promote a PENDING secret version to CURRENT.

        OCI Vault automatically moves the previous CURRENT version to
        PREVIOUS when the new version is promoted.

        Uses update_secret with current_version_number — the SDK mechanism
        for promoting a specific version without changing secret content.

        Args:
            secret_id: OCID of the secret.
            version_number: The PENDING version number returned by
                            create_pending_version().

        Raises:
            oci.exceptions.ServiceError: On non-2xx response from Vault.
        """
        try:
            version = self._vaults.get_secret_version(
                secret_id=secret_id,
                secret_version_number=version_number,
            ).data
        except ServiceError as exc:
            logger.error(
                "failed to retrieve secret version before promote",
                extra={
                    "secret_id": secret_id,
                    "version_number": version_number,
                    "status": exc.status,
                    "code": exc.code,
                },
            )
            raise

        if "CURRENT" in (version.stages or []):
            logger.info(
                "secret version already current, skipping promote",
                extra={"secret_id": secret_id, "version_number": version_number},
            )
            return

        promote_details = UpdateSecretDetails(current_version_number=version_number)
        try:
            self._update_secret_with_retry(secret_id, promote_details)
        except ServiceError as exc:
            logger.error(
                "failed to promote secret version to current",
                extra={
                    "secret_id": secret_id,
                    "version_number": version_number,
                    "status": exc.status,
                    "code": exc.code,
                },
            )
            raise

        self._wait_until_active(secret_id)
        logger.info(
            "secret version promoted to current",
            extra={"secret_id": secret_id, "version_number": version_number},
        )

"""OCI Vault and Secrets SDK wrapper used by the rotation handler."""

import base64
import logging
from typing import Optional

import oci
from oci.exceptions import ServiceError
from oci.secrets import SecretsClient
from oci.vault import VaultsClient
from oci.vault.models import Base64SecretContentDetails, UpdateSecretDetails

logger = logging.getLogger(__name__)


class VaultClient:
    """Wraps the OCI Vault read/write operations needed by the rotation handler.

    Authenticates via Resource Principal by default — the correct signer for a
    deployed OCI Function. Pass an explicit signer to use config-file auth
    during local development or testing.
    """

    def __init__(self, signer: Optional[object] = None) -> None:
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
        DEPRECATED when a new one is created, so this is safe to call on
        retry after a previous partial rotation.

        Args:
            secret_id: OCID of the secret to update.
            new_content: Plaintext string to store. Base64-encoded before
                         transmission; Vault stores and returns it encoded.

        Returns:
            The version number of the newly created PENDING version. Pass
            this to promote_to_current() to complete the rotation.

        Raises:
            oci.exceptions.ServiceError: On non-2xx response from Vault.
        """
        encoded = base64.b64encode(new_content.encode()).decode()
        update_details = UpdateSecretDetails(
            secret_content=Base64SecretContentDetails(
                content_type=Base64SecretContentDetails.CONTENT_TYPE_BASE64,
                content=encoded,
            )
        )
        try:
            self._vaults.update_secret(
                secret_id=secret_id,
                update_secret_details=update_details,
            )
            versions = self._vaults.list_secret_versions(secret_id=secret_id).data
        except ServiceError as exc:
            logger.error(
                "failed to create pending secret version",
                extra={"secret_id": secret_id, "status": exc.status, "code": exc.code},
            )
            raise

        pending = next(
            (v for v in versions if "PENDING" in (v.stages or [])),
            None,
        )
        if pending is None:
            raise RuntimeError(
                f"no PENDING version found after update_secret for secret {secret_id}"
            )
        pending_version = pending.version_number
        logger.info(
            "pending secret version created",
            extra={"secret_id": secret_id, "pending_version": pending_version},
        )
        return pending_version

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
            self._vaults.update_secret(
                secret_id=secret_id,
                update_secret_details=UpdateSecretDetails(
                    current_version_number=version_number,
                ),
            )
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
        logger.info(
            "secret version promoted to current",
            extra={"secret_id": secret_id, "version_number": version_number},
        )

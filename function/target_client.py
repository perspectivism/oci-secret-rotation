"""Target client interface and Object Storage / mock implementations.

ObjectStorageTargetClient is the demo target: it writes the new credential as
a plain-text object to a private OCI bucket after each rotation, making the
update immediately observable via console or CLI.

In a production deployment, substitute a concrete implementation that calls the
real target's credential API (e.g. ALTER USER for a database). Only this file
changes — rotation.py and vault_client.py are target-agnostic.
"""

import abc
import logging

import oci
from oci.exceptions import ServiceError
from oci.object_storage import ObjectStorageClient

logger = logging.getLogger(__name__)


class TargetUpdateError(Exception):
    """Raised when the target system rejects or fails a credential update.

    Rotation treats this as a recoverable abort: a PENDING Vault version may
    exist, but CURRENT remains unchanged and the target still holds the old
    credential.
    """


class TargetClient(abc.ABC):
    """Interface that every target implementation must satisfy."""

    @abc.abstractmethod
    def update_credential(self, new_value: str, current_value: str = "") -> None:
        """Apply new_value as the active credential on the target system.

        Args:
            new_value: The new credential string to apply.
            current_value: The current credential, for targets that require it
                           to authenticate the change. May be ignored.

        Raises:
            TargetUpdateError: If the target rejects or cannot apply the update.
        """


class ObjectStorageTargetClient(TargetClient):
    """Writes the rotated credential to a private Object Storage object.

    Serves as a demo target: after each rotation the new credential is
    immediately readable via `oci os object get` or the OCI console.
    This is NOT a production pattern — real targets are databases, APIs, or
    application config stores, not object storage.

    Authenticates via Resource Principal (the deployed Function's identity).
    """

    def __init__(
        self,
        namespace: str,
        bucket_name: str,
        object_name: str,
        signer: object | None = None,
    ) -> None:
        if signer is None:
            signer = oci.auth.signers.get_resource_principals_signer()
        self._client = ObjectStorageClient(config={}, signer=signer)
        self._namespace = namespace
        self._bucket_name = bucket_name
        self._object_name = object_name

    def update_credential(self, new_value: str, current_value: str = "") -> None:
        """Overwrite the target object with the new credential value.

        Args:
            new_value: New credential string to store.
            current_value: Unused — Object Storage overwrites unconditionally.

        Raises:
            TargetUpdateError: If the put_object call fails.
        """
        try:
            self._client.put_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=self._object_name,
                put_object_body=new_value.encode(),
            )
        except ServiceError as exc:
            logger.error(
                "failed to write credential to object storage",
                extra={
                    "bucket": self._bucket_name,
                    "object": self._object_name,
                    "status": exc.status,
                    "code": exc.code,
                },
            )
            raise TargetUpdateError(str(exc)) from exc
        logger.info(
            "target credential updated",
            extra={"bucket": self._bucket_name, "object": self._object_name},
        )


class MockTargetClient(TargetClient):
    """In-memory target that stores the current credential in an instance variable.

    Suitable for unit tests and end-to-end demonstrations where a real target
    system is not available. Supports failure injection via fail_on_next_update.
    """

    def __init__(self, initial_credential: str = "") -> None:
        """Initialise with an optional starting credential value.

        Args:
            initial_credential: Value to treat as the credential before any
                                 rotation has occurred.
        """
        self._credential = initial_credential
        # Set to True before a test call to simulate a target-side failure.
        # Automatically resets to False after the injected failure fires.
        self.fail_on_next_update: bool = False
        self.update_count: int = 0

    @property
    def current_credential(self) -> str:
        """The credential currently held by the mock target."""
        return self._credential

    def update_credential(self, new_value: str, current_value: str = "") -> None:
        """Store new_value as the active credential, or raise if failure injected.

        Args:
            new_value: Credential string to apply.
            current_value: Ignored by the mock.

        Raises:
            TargetUpdateError: If fail_on_next_update is True (resets after firing).
        """
        if self.fail_on_next_update:
            self.fail_on_next_update = False
            raise TargetUpdateError(
                "injected failure: target rejected credential update"
            )
        self._credential = new_value
        self.update_count += 1
        logger.info(
            "mock target credential updated",
            extra={"update_count": self.update_count},
        )

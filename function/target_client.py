"""Target client interface and in-memory mock implementation.

In a real deployment, replace MockTargetClient with a concrete implementation
that calls the target system's credential-rotation API (e.g. ALTER USER for a
database, or a vendor's key-rotation endpoint). Only target_client.py changes —
rotation.py and vault_client.py are target-agnostic.
"""

import abc
import logging

logger = logging.getLogger(__name__)


class TargetUpdateError(Exception):
    """Raised when the target system rejects or fails a credential update.

    Rotation treats this as a safe abort: if update_credential raises before
    the Vault write, state is consistent and rotation can be safely retried.
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
            raise TargetUpdateError("injected failure: target rejected credential update")
        self._credential = new_value
        self.update_count += 1
        logger.info(
            "mock target credential updated",
            extra={"update_count": self.update_count},
        )

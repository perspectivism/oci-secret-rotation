"""Unit tests for the rotation function handler (Phase B).

Tests cover request parsing, config validation, and all four rotation step
handlers with rotation.py and OCI clients patched.
"""

import io
import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

from oci.exceptions import ServiceError

import pytest

import func


class _MockCtx:
    """Minimal Fn context substitute."""

    def __init__(self, config: dict[str, str] | None = None) -> None:
        self._config = config or {}

    def Config(self) -> dict[str, str]:
        return self._config

    def SetResponseHeaders(self, headers: dict[str, str], _status_code: int) -> None:
        pass


_VALID_CONFIG = {
    "TARGET_BUCKET": "rotation-bucket",
    "TARGET_NAMESPACE": "myns",
    "TARGET_OBJECT": "credential",
    "ONS_TOPIC_ID": "ocid1.onstopic.oc1..fake",
}

_FAKE_SECRET_ID = "ocid1.vaultsecret.oc1.us-chicago-1.fake"


def _body(payload: dict[str, object]) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


@pytest.fixture(autouse=True)
def patches() -> Generator[dict, None, None]:
    """Patch OCI clients and rotation so tests run without credentials.

    Yields a dict of mocks for tests that need to adjust return values or
    inject failures:
        patches["rotation"]   — func.rotation module mock
        patches["ons_class"]  — NotificationDataPlaneClient class mock
        patches["ons_client"] — instance returned by NotificationDataPlaneClient()
    """
    mock_rotation = MagicMock()
    mock_rotation.verify_connection.return_value = 2
    mock_rotation.create_pending_version.return_value = 3
    mock_rotation.update_target_system.return_value = 3
    mock_rotation.promote_pending_version.return_value = 3

    mock_ons_client = MagicMock()
    mock_ons_class = MagicMock(return_value=mock_ons_client)

    with (
        patch(
            "oci.auth.signers.get_resource_principals_signer", return_value=MagicMock()
        ),
        patch("func.VaultClient", return_value=MagicMock()),
        patch("func.ObjectStorageTargetClient", return_value=MagicMock()),
        patch("func.rotation", mock_rotation),
        patch("func.NotificationDataPlaneClient", mock_ons_class),
    ):
        yield {
            "rotation": mock_rotation,
            "ons_class": mock_ons_class,
            "ons_client": mock_ons_client,
        }


# --- VERIFY_CONNECTION ---


def test_verify_connection_returns_current_version(patches) -> None:
    """VERIFY_CONNECTION returns valid SecretRotationOutput with current version."""
    patches["rotation"].verify_connection.return_value = 5
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "VERIFY_CONNECTION"})
    )

    assert resp.status_code == 200
    data = json.loads(resp.body())
    assert data["responseCode"] == 200
    assert data["versionNo"] == 5
    assert data["returnMessage"] == "VERIFY_CONNECTION succeeded"
    patches["rotation"].verify_connection.assert_called_once()


def test_verify_connection_failure_returns_400_response_code(patches) -> None:
    """Vault read failure during VERIFY_CONNECTION returns responseCode 400."""
    patches["rotation"].verify_connection.side_effect = ServiceError(
        403, "NotAuthorizedOrNotFound", {}, "injected failure"
    )
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "VERIFY_CONNECTION"})
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


def test_verify_connection_extra_fields_ignored() -> None:
    """Extra fields in a Vault-originated payload are ignored."""
    ctx = _MockCtx(_VALID_CONFIG)
    payload = {
        "secretId": _FAKE_SECRET_ID,
        "step": "VERIFY_CONNECTION",
        "extra": "ignored",
    }

    resp = func.handler(ctx, _body(payload))

    assert resp.status_code == 200
    assert json.loads(resp.body())["responseCode"] == 200


# --- CREATE_PENDING_VERSION ---


def test_create_pending_version_succeeds(patches) -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "CREATE_PENDING_VERSION"})
    )

    assert resp.status_code == 200
    data = json.loads(resp.body())
    assert data["responseCode"] == 200
    assert data["versionNo"] == 3
    assert data["returnMessage"] == "CREATE_PENDING_VERSION succeeded"
    patches["rotation"].create_pending_version.assert_called_once()


def test_create_pending_version_failure_returns_400(patches) -> None:
    patches["rotation"].create_pending_version.side_effect = RuntimeError("vault error")
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "CREATE_PENDING_VERSION"})
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


# --- UPDATE_TARGET_SYSTEM ---


def test_update_target_system_succeeds(patches) -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "UPDATE_TARGET_SYSTEM"})
    )

    assert resp.status_code == 200
    data = json.loads(resp.body())
    assert data["responseCode"] == 200
    assert data["versionNo"] == 3
    assert data["returnMessage"] == "UPDATE_TARGET_SYSTEM succeeded"
    patches["rotation"].update_target_system.assert_called_once()


def test_update_target_system_failure_returns_400(patches) -> None:
    patches["rotation"].update_target_system.side_effect = RuntimeError(
        "no PENDING version"
    )
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "UPDATE_TARGET_SYSTEM"})
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


# --- PROMOTE_PENDING_VERSION ---


def test_promote_pending_version_succeeds(patches) -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx,
        _body(
            {
                "secretId": _FAKE_SECRET_ID,
                "step": "PROMOTE_PENDING_VERSION",
                "versionNo": 3,
            }
        ),
    )

    assert resp.status_code == 200
    data = json.loads(resp.body())
    assert data["responseCode"] == 200
    assert data["versionNo"] == 3
    assert data["returnMessage"] == "PROMOTE_PENDING_VERSION succeeded"
    patches["rotation"].promote_pending_version.assert_called_once_with(
        _FAKE_SECRET_ID, 3, func.VaultClient.return_value
    )


def test_promote_pending_version_sends_ons_notification(patches) -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    func.handler(
        ctx,
        _body(
            {
                "secretId": _FAKE_SECRET_ID,
                "step": "PROMOTE_PENDING_VERSION",
                "versionNo": 3,
            }
        ),
    )

    patches["ons_client"].publish_message.assert_called_once()
    call_kwargs = patches["ons_client"].publish_message.call_args.kwargs
    assert call_kwargs["topic_id"] == _VALID_CONFIG["ONS_TOPIC_ID"]


def test_promote_pending_version_missing_version_no_returns_400() -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "PROMOTE_PENDING_VERSION"})
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert "versionNo" in data["returnMessage"]


@pytest.mark.parametrize(
    "version_no",
    ["abc", 3.7, True],
    ids=["string", "float", "bool"],
)
def test_promote_pending_version_non_integer_version_no_returns_400(version_no) -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx,
        _body(
            {
                "secretId": _FAKE_SECRET_ID,
                "step": "PROMOTE_PENDING_VERSION",
                "versionNo": version_no,
            }
        ),
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert "integer" in data["returnMessage"]


def test_promote_pending_version_failure_returns_400(patches) -> None:
    patches["rotation"].promote_pending_version.side_effect = RuntimeError(
        "unexpected stages"
    )
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx,
        _body(
            {
                "secretId": _FAKE_SECRET_ID,
                "step": "PROMOTE_PENDING_VERSION",
                "versionNo": 3,
            }
        ),
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


def test_promote_pending_version_ons_failure_does_not_fail_rotation(patches) -> None:
    """ONS notification failure is swallowed — rotation is already complete."""
    patches["ons_client"].publish_message.side_effect = Exception("ONS unavailable")
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx,
        _body(
            {
                "secretId": _FAKE_SECRET_ID,
                "step": "PROMOTE_PENDING_VERSION",
                "versionNo": 3,
            }
        ),
    )

    assert resp.status_code == 200
    assert json.loads(resp.body())["responseCode"] == 200


# --- Missing or unrecognized step ---


def test_non_string_step_returns_400_response_code() -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(ctx, _body({"secretId": _FAKE_SECRET_ID, "step": 123}))

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert "step" in data["returnMessage"].lower()


def test_missing_step_returns_400_response_code() -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(ctx, _body({"secretId": _FAKE_SECRET_ID}))

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None
    assert "step" in data["returnMessage"].lower()


def test_blank_step_returns_400_response_code() -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "   "}))

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


def test_unrecognized_step_returns_400_response_code() -> None:
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "BOGUS_STEP", "versionNo": 2})
    )

    assert resp.status_code == 500
    data = json.loads(resp.body())
    assert data["responseCode"] == 400
    assert data["versionNo"] is None


# --- Bad payload cases ---


@pytest.mark.parametrize(
    "data,expected_fragment",
    [
        (io.BytesIO(b""), "body"),
        (None, "body"),
        (io.BytesIO(b"not json {{{"), "invalid"),
        (io.BytesIO(b"\xff\xfe"), "invalid"),
        (io.BytesIO(b'{"step": "VERIFY_CONNECTION"}'), "secretId"),
        (io.BytesIO(b'{"secretId": "   "}'), "secretId"),
        (io.BytesIO(b'["secretId", "ocid1..."]'), "object"),
        (io.BytesIO(b'{"secretId": 123, "step": "VERIFY_CONNECTION"}'), "secretId"),
    ],
    ids=[
        "empty_body",
        "none_body",
        "malformed_json",
        "invalid_utf8",
        "missing_secret_id",
        "blank_secret_id",
        "non_object_json",
        "non_string_secret_id",
    ],
)
def test_bad_payload_returns_500(
    data: io.BytesIO | None, expected_fragment: str
) -> None:
    """All malformed or incomplete payload variants return HTTP 500."""
    ctx = _MockCtx(_VALID_CONFIG)

    resp = func.handler(ctx, data)

    assert resp.status_code == 500
    assert expected_fragment in json.loads(resp.body())["error"]


# --- Config validation ---


def test_missing_target_bucket_returns_500() -> None:
    config = {k: v for k, v in _VALID_CONFIG.items() if k != "TARGET_BUCKET"}
    ctx = _MockCtx(config)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "VERIFY_CONNECTION"})
    )

    assert resp.status_code == 500
    assert "TARGET_BUCKET" in json.loads(resp.body())["error"]


def test_missing_ons_topic_returns_500() -> None:
    config = {k: v for k, v in _VALID_CONFIG.items() if k != "ONS_TOPIC_ID"}
    ctx = _MockCtx(config)

    resp = func.handler(
        ctx, _body({"secretId": _FAKE_SECRET_ID, "step": "VERIFY_CONNECTION"})
    )

    assert resp.status_code == 500
    assert "ONS_TOPIC_ID" in json.loads(resp.body())["error"]

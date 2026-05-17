"""OCI Function entry point — Phase B rotation handler.

The Fn runtime calls handler() on each invocation. This module is a thin
adapter: it parses the SecretRotationInput payload, builds OCI clients from
Function config, delegates to the matching step function in rotation.py, and
maps the return value or exception to a SecretRotationOutput response.

Step functions in rotation.py raise on failure and return an int (versionNo)
on success. This module owns all FDK and HTTP concerns so rotation.py stays
target-agnostic and unit-testable without the FDK.
"""

import io
import json
import logging
import os
import sys

import oci
from oci.ons import NotificationDataPlaneClient
from oci.ons.models import MessageDetails

# The FDK loads func.py via importlib which does not add the file's directory
# to sys.path automatically. Insert it explicitly so that rotation.py,
# vault_client.py, and target_client.py are importable regardless of how the
# platform configures PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fdk import response

import rotation
from target_client import ObjectStorageTargetClient
from vault_client import VaultClient

# Standard LogRecord attributes excluded from the JSON extra-fields pass-through.
_LOG_RESERVED = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _JsonFormatter(logging.Formatter):
    """Emits one JSON object per log record for OCI Logging consumption."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RESERVED:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _configure_logging() -> None:
    # Called once at module load. Fn may reuse the same container across
    # invocations; initialising here prevents duplicate handlers accumulating.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.setLevel(logging.INFO)


_configure_logging()

logger = logging.getLogger(__name__)


def _error_response(
    ctx, message: str, version_no: int | None = None
) -> response.Response:
    """Return a SecretRotationOutput with responseCode 400."""
    return response.Response(
        ctx,
        response_data=json.dumps(
            {
                "responseCode": 400,
                "versionNo": version_no,
                "returnMessage": message,
            }
        ),
        headers={"Content-Type": "application/json"},
        status_code=500,
    )


def handler(ctx, data: io.BytesIO | None = None) -> response.Response:
    """Handle a single rotation invocation from the Fn runtime.

    Parses the SecretRotationInput payload, constructs OCI clients from
    Function config, and delegates to the matching step function in rotation.py.
    All four rotation steps are handled; PROMOTE_PENDING_VERSION additionally
    publishes an ONS notification on success (best-effort — rotation result is
    not affected if the notification fails).

    Args:
        ctx: Fn context — provides the Config dict and request metadata.
        data: Request body as JSON containing secretId, step, and optionally
              versionNo (required for PROMOTE_PENDING_VERSION).

    Returns:
        fdk.response.Response with a SecretRotationOutput-shaped JSON body.
        Failures return a SecretRotationOutput with responseCode 400; malformed
        non-protocol requests return a plain JSON error response.
    """
    body_bytes = data.read() if data is not None else b""
    if not body_bytes:
        logger.error("missing or empty request body")
        return response.Response(
            ctx,
            response_data=json.dumps({"error": "missing request body"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    try:
        payload = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("request body is not valid JSON", extra={"error": str(exc)})
        return response.Response(
            ctx,
            response_data=json.dumps({"error": f"invalid request body: {exc}"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    if not isinstance(payload, dict):
        logger.error("request body is not a JSON object")
        return response.Response(
            ctx,
            response_data=json.dumps({"error": "request body must be a JSON object"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    secret_id_raw = payload.get("secretId")
    if not isinstance(secret_id_raw, str) or not secret_id_raw.strip():
        logger.error("secretId missing, blank, or not a string in request body")
        return response.Response(
            ctx,
            response_data=json.dumps({"error": "missing secretId in request body"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )
    secret_id = secret_id_raw.strip()

    step_raw = payload.get("step")
    step = step_raw.strip() if isinstance(step_raw, str) else ""
    version_no_payload = payload.get("versionNo")

    logger.info(
        "rotation invocation received",
        extra={
            "step": step,
            "secret_id": secret_id,
            "version_no": version_no_payload,
        },
    )

    if not step:
        logger.error("step field missing or blank")
        return _error_response(ctx, "step field required")

    cfg = ctx.Config()
    target_bucket = cfg.get("TARGET_BUCKET", "").strip()
    target_namespace = cfg.get("TARGET_NAMESPACE", "").strip()
    target_object = cfg.get("TARGET_OBJECT", "").strip()
    ons_topic_id = cfg.get("ONS_TOPIC_ID", "").strip()

    missing = [
        k
        for k, v in {
            "TARGET_BUCKET": target_bucket,
            "TARGET_NAMESPACE": target_namespace,
            "TARGET_OBJECT": target_object,
            "ONS_TOPIC_ID": ons_topic_id,
        }.items()
        if not v
    ]
    if missing:
        logger.error(
            "missing required function config keys", extra={"missing": missing}
        )
        return response.Response(
            ctx,
            response_data=json.dumps({"error": f"missing config: {missing}"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    signer = oci.auth.signers.get_resource_principals_signer()
    vault = VaultClient(signer=signer)
    target = ObjectStorageTargetClient(
        namespace=target_namespace,
        bucket_name=target_bucket,
        object_name=target_object,
        signer=signer,
    )

    if step == "VERIFY_CONNECTION":
        try:
            version_no = rotation.verify_connection(secret_id, vault)
        except Exception as exc:
            logger.error(
                "VERIFY_CONNECTION failed",
                extra={"secret_id": secret_id, "error_type": type(exc).__name__},
                exc_info=True,
            )
            return _error_response(ctx, f"VERIFY_CONNECTION failed: {exc}")
        return response.Response(
            ctx,
            response_data=json.dumps(
                {
                    "responseCode": 200,
                    "versionNo": version_no,
                    "returnMessage": "VERIFY_CONNECTION succeeded",
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    if step == "CREATE_PENDING_VERSION":
        try:
            version_no = rotation.create_pending_version(secret_id, vault)
        except Exception as exc:
            logger.error(
                "CREATE_PENDING_VERSION failed",
                extra={"secret_id": secret_id, "error_type": type(exc).__name__},
                exc_info=True,
            )
            return _error_response(ctx, f"CREATE_PENDING_VERSION failed: {exc}")
        return response.Response(
            ctx,
            response_data=json.dumps(
                {
                    "responseCode": 200,
                    "versionNo": version_no,
                    "returnMessage": "CREATE_PENDING_VERSION succeeded",
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    if step == "UPDATE_TARGET_SYSTEM":
        try:
            version_no = rotation.update_target_system(secret_id, vault, target)
        except Exception as exc:
            logger.error(
                "UPDATE_TARGET_SYSTEM failed",
                extra={"secret_id": secret_id, "error_type": type(exc).__name__},
                exc_info=True,
            )
            return _error_response(ctx, f"UPDATE_TARGET_SYSTEM failed: {exc}")
        return response.Response(
            ctx,
            response_data=json.dumps(
                {
                    "responseCode": 200,
                    "versionNo": version_no,
                    "returnMessage": "UPDATE_TARGET_SYSTEM succeeded",
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    if step == "PROMOTE_PENDING_VERSION":
        if version_no_payload is None:
            logger.error("PROMOTE_PENDING_VERSION: versionNo missing from payload")
            return _error_response(
                ctx, "PROMOTE_PENDING_VERSION: versionNo required in payload"
            )
        if not isinstance(version_no_payload, int) or isinstance(
            version_no_payload, bool
        ):
            logger.error(
                "PROMOTE_PENDING_VERSION: versionNo is not a valid integer",
                extra={"version_no_payload": version_no_payload},
            )
            return _error_response(
                ctx, "PROMOTE_PENDING_VERSION: versionNo must be an integer"
            )
        promote_version_no = version_no_payload
        try:
            version_no = rotation.promote_pending_version(
                secret_id, promote_version_no, vault
            )
        except Exception as exc:
            logger.error(
                "PROMOTE_PENDING_VERSION failed",
                extra={"secret_id": secret_id, "error_type": type(exc).__name__},
                exc_info=True,
            )
            return _error_response(ctx, f"PROMOTE_PENDING_VERSION failed: {exc}")

        # Publish rotation notification — best-effort; rotation is already complete.
        try:
            ons = NotificationDataPlaneClient(config={}, signer=signer)
            ons.publish_message(
                topic_id=ons_topic_id,
                message_details=MessageDetails(
                    title="Secret rotated",
                    body=json.dumps({"secretId": secret_id, "versionNo": version_no}),
                ),
            )
            logger.info(
                "ONS notification sent",
                extra={"secret_id": secret_id, "version_no": version_no},
            )
        except Exception as exc:
            logger.warning(
                "ONS notification failed (rotation already complete)",
                extra={"secret_id": secret_id, "error_type": type(exc).__name__},
                exc_info=True,
            )

        return response.Response(
            ctx,
            response_data=json.dumps(
                {
                    "responseCode": 200,
                    "versionNo": version_no,
                    "returnMessage": "PROMOTE_PENDING_VERSION succeeded",
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    logger.error("unrecognized step", extra={"step": step})
    return _error_response(ctx, f"unrecognized step {step!r}")

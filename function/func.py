"""OCI Function entry point for secret rotation.

The Fn runtime calls handler() on each invocation. All rotation logic lives
in rotation.py; this module is responsible only for extracting config,
setting up logging, and mapping outcomes to HTTP responses.
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

from rotation import rotate
from target_client import ObjectStorageTargetClient
from vault_client import VaultClient

# Standard LogRecord attributes excluded from the JSON extra-fields pass-through.
_LOG_RESERVED = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "taskName", "thread", "threadName",
})


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


def handler(ctx, data: io.BytesIO = None) -> response.Response:
    """Handle a single rotation invocation from the Fn runtime.

    Reads SECRET_OCID from function config, delegates to rotate(), and returns
    a JSON response. Returns HTTP 500 on any failure so the Vault rotation
    scheduler can detect and report the error.

    Args:
        ctx: Fn context — provides the Config dict and request metadata.
        data: Request body (unused; Vault rotation invocations carry no body).

    Returns:
        fdk.response.Response with a JSON body and appropriate HTTP status.
    """
    cfg = ctx.Config()
    secret_id = cfg.get("SECRET_OCID", "").strip()
    target_bucket = cfg.get("TARGET_BUCKET", "").strip()
    target_namespace = cfg.get("TARGET_NAMESPACE", "").strip()
    target_object = cfg.get("TARGET_OBJECT", "").strip()
    ons_topic_id = cfg.get("ONS_TOPIC_ID", "").strip()

    missing = [k for k, v in {
        "SECRET_OCID": secret_id,
        "TARGET_BUCKET": target_bucket,
        "TARGET_NAMESPACE": target_namespace,
        "TARGET_OBJECT": target_object,
        "ONS_TOPIC_ID": ons_topic_id,
    }.items() if not v]
    if missing:
        logger.error("missing required function config keys", extra={"missing": missing})
        return response.Response(
            ctx,
            response_data=json.dumps({"error": f"missing config: {missing}"}),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    vault = VaultClient()
    target = ObjectStorageTargetClient(
        namespace=target_namespace,
        bucket_name=target_bucket,
        object_name=target_object,
    )

    try:
        rotate(secret_id=secret_id, vault_client=vault, target_client=target)
    except Exception as exc:
        logger.error(
            "rotation failed",
            extra={"secret_id": secret_id, "error_type": type(exc).__name__},
            exc_info=True,
        )
        return response.Response(
            ctx,
            response_data=json.dumps({
                "error": str(exc),
                "error_type": type(exc).__name__,
            }),
            headers={"Content-Type": "application/json"},
            status_code=500,
        )

    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        ons = NotificationDataPlaneClient(config={}, signer=signer)
        ons.publish_message(
            topic_id=ons_topic_id,
            message_details=MessageDetails(
                title="Secret rotation completed",
                body=json.dumps({"secret_id": secret_id, "status": "ok"}),
            ),
        )
    except Exception as exc:
        logger.warning(
            "rotation succeeded but notification failed",
            extra={"secret_id": secret_id, "error": str(exc)},
        )

    return response.Response(
        ctx,
        response_data=json.dumps({"status": "ok", "secret_id": secret_id}),
        headers={"Content-Type": "application/json"},
    )

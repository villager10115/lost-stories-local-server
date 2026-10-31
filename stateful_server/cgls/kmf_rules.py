"""Canonical KMF presentation values derived from persisted progress."""

import uuid

MAX_KMF_REVISION_CLASS = 4
LOCAL_CUSTOMIZATION_NAMESPACE = uuid.UUID(
    "f31c7d18-2f1b-4dc7-a75d-85e64ae6f6e1")


def customization_instance_id(user_kmf_id: str, customization_id: int) -> str:
    """Return the instance ID emitted by the preserved web page builder."""
    return str(uuid.uuid5(
        LOCAL_CUSTOMIZATION_NAMESPACE,
        "%s:%s" % (user_kmf_id, int(customization_id)),
    ))


def revision_class_for_revision(revision: int) -> int:
    """Return the initial weapon icon class used by the official client."""
    revision = int(revision)
    if revision < 0:
        raise ValueError("KMF revision must be nonnegative")
    return min(MAX_KMF_REVISION_CLASS, revision // 3 + 1)

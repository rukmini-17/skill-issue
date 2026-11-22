"""The seven update-approval policies (D12), each behind the ``Policy`` interface.

Import a policy by name via ``get_policy("pin_reapprove")`` or iterate
``POLICIES``. ``llm_reviewer`` needs a completion function injected (or B's
backend wired) before ``on_update`` can run; the others are ready as-is.
"""

from __future__ import annotations

from bench.policies.capability_diff import CapabilityDiffPolicy
from bench.policies.delegation_envelope import DelegationEnvelopePolicy
from bench.policies.deny_by_default_manifest import DenyByDefaultManifestPolicy
from bench.policies.llm_reviewer import LLMReviewerPolicy
from bench.policies.new_permissions_only import NewPermissionsOnlyPolicy
from bench.policies.none import NonePolicy
from bench.policies.pin_reapprove import PinReapprovePolicy

# name -> zero-arg constructor (llm_reviewer still needs a client to *run*).
POLICY_CLASSES = {
    "none": NonePolicy,
    "pin_reapprove": PinReapprovePolicy,
    "new_permissions_only": NewPermissionsOnlyPolicy,
    "capability_diff": CapabilityDiffPolicy,
    "deny_by_default_manifest": DenyByDefaultManifestPolicy,
    "delegation_envelope": DelegationEnvelopePolicy,
    "llm_reviewer": LLMReviewerPolicy,
}

POLICY_NAMES = tuple(POLICY_CLASSES)


def get_policy(name: str, **kwargs):
    """Instantiate a policy by name. kwargs are forwarded (e.g. llm_reviewer's complete=)."""
    try:
        cls = POLICY_CLASSES[name]
    except KeyError:
        raise KeyError(f"unknown policy {name!r}; known: {', '.join(POLICY_NAMES)}")
    return cls(**kwargs)


__all__ = [
    "POLICY_CLASSES",
    "POLICY_NAMES",
    "get_policy",
    "NonePolicy",
    "PinReapprovePolicy",
    "NewPermissionsOnlyPolicy",
    "CapabilityDiffPolicy",
    "DenyByDefaultManifestPolicy",
    "DelegationEnvelopePolicy",
    "LLMReviewerPolicy",
]

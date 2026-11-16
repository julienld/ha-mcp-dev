"""Only exact installed wheel receipts can avoid a paired URL reinstall."""

import pytest

from ._paired_wheel_core import WHEEL_DIGEST as _DIGEST
from ._paired_wheel_core import WHEEL_SPEC as _SPEC
from ._paired_wheel_core import WHEEL_URL as _URL
from ._paired_wheel_core import paired as paired


def test_exact_paired_wheel_receipt_is_read_without_importing_runtime(paired):
    module, _receipt, _distribution = paired
    assert module.paired_wheel_matches(_SPEC, "9.0.0.dev1", "9.0.0.dev1")


@pytest.mark.parametrize(
    "change",
    [
        "url",
        "hash",
        "loaded_version",
        "distribution_version",
        "vcs",
        "missing",
        "conflicting_legacy_hash",
    ],
)
def test_changed_or_unproven_installation_never_qualifies(paired, change):
    module, receipt, distribution = paired
    loaded = "9.0.0.dev1"
    if change == "url":
        receipt["url"] = _URL.replace("ha-mcp-native", "other-repository")
    elif change == "hash":
        receipt["archive_info"]["hashes"]["sha256"] = "0" * 64
    elif change == "loaded_version":
        loaded = "9.0.0.dev2"
    elif change == "distribution_version":
        distribution.version = "9.0.0.dev2"
    elif change == "vcs":
        receipt["vcs_info"] = {"vcs": "git", "commit_id": "a" * 40}
    elif change == "missing":
        receipt.clear()
    else:
        receipt["archive_info"]["hash"] = "sha256=" + "0" * 64
    assert not module.paired_wheel_matches(_SPEC, loaded, "9.0.0.dev1")


@pytest.mark.parametrize(
    "spec",
    [
        _URL,
        "ha-mcp==9.0.0.dev1",
        "ha-mcp @ " + _URL,
        _SPEC.replace("https:", "http:"),
        _SPEC.replace("github.com/", "credential@github.com/"),
        _SPEC.replace("#sha256=", "?signature=expires#sha256="),
    ],
)
def test_mutable_unhashed_or_credential_bearing_references_do_not_qualify(paired, spec):
    module, *_ = paired
    assert not module.paired_wheel_matches(spec, "9.0.0.dev1", "9.0.0.dev1")


def test_legacy_pep610_hash_field_is_accepted_only_when_no_hashes_map_exists(paired):
    module, receipt, _distribution = paired
    receipt["archive_info"] = {"hash": "sha256=" + _DIGEST}
    assert module.paired_wheel_matches(_SPEC, "9.0.0.dev1", "9.0.0.dev1")

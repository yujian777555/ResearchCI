from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from expcontractbench.phase1e import PosthocResearchCIAdapter, ProvenanceOnlyAdapter, SchemaValidationAdapter


def test_baseline_modules_do_not_import_researchci_engine():
    from expcontractbench import phase1e

    source = inspect.getsource(SchemaValidationAdapter)
    assert "InvariantEngine" not in source


def test_phase1e_adapters_have_common_names():
    assert SchemaValidationAdapter.name == "schema_validation"
    assert ProvenanceOnlyAdapter.name == "provenance_only"
    assert PosthocResearchCIAdapter.name == "posthoc_researchci"

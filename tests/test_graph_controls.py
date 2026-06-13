"""Graph-native detector tests.

Proves `vendor_collusion_ring` finds multi-vendor rings that the pairwise
`entity_resolution_duplicate` (F-004) cannot, and that it stays silent on plain
pairs (which F-004 already covers). Uses the real Tamween dataset as the base and
injects a third colluding vendor, so the bundle/graph plumbing is exercised
end-to-end rather than mocked.
"""

from __future__ import annotations

import pandas as pd

from strategyos_mvp.config import CONFIG
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.knowledge_graph import build_structural_graph
from strategyos_mvp.skills.graph_controls import (
    detect_vendor_collusion_ring,
    graph_detector_registry,
    _connected_vendor_components,
)


def _base_bundle():
    return load_dataset(CONFIG.source_dataset)


def test_registry_registers_vendor_collusion_ring():
    names = {d.name for d in graph_detector_registry()}
    assert "detect_vendor_collusion_ring" in names
    ring = next(d for d in graph_detector_registry() if d.name == "detect_vendor_collusion_ring")
    assert ring.pattern_type == "vendor_collusion_ring"
    assert set(ring.required_roles) == {"vendor_master", "ap_ledger"}


def test_pair_only_fixture_produces_no_ring():
    """Tamween has one 2-vendor shared-bank pair (V-1142/V-1187). Pairs belong to
    F-004, so the ring detector must stay silent — this is why the acceptance gate
    is unchanged."""
    bundle = _base_bundle()
    graph = build_structural_graph(bundle)
    assert detect_vendor_collusion_ring(graph, bundle) == []


def test_three_vendor_ring_is_detected_as_superset_of_pairwise():
    bundle = _base_bundle()
    # Inject a third vendor sharing V-1142/V-1187's bank account -> 3-vendor ring.
    shared_bank = "SA0380000000608010167519"
    extra = bundle.vendors[bundle.vendors["Vendor_ID"].astype(str) == "V-1142"].copy()
    extra["Vendor_ID"] = "V-9999"
    extra["Vendor_Name"] = "Rashid Holdings Front"
    extra["Bank_Account"] = shared_bank
    bundle.vendors = pd.concat([bundle.vendors, extra], ignore_index=True)

    graph = build_structural_graph(bundle)
    components = _connected_vendor_components(graph)
    ring_ids = next(
        (sorted(n.split(":")[-1] for n in c) for c in components if len(c) >= 3),
        None,
    )
    assert ring_ids == ["V-1142", "V-1187", "V-9999"]

    findings = detect_vendor_collusion_ring(graph, bundle)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_type == "vendor_collusion_ring"
    # Strict superset of pairwise: all three vendors in one finding.
    assert set(finding.vendor_id.split("/")) == {"V-1142", "V-1187", "V-9999"}
    assert finding.calculation["ring_size"] == 3
    # Standard Finding contract: confidence + citations present for the evidence gate.
    assert finding.confidence == "HIGH"
    assert len(finding.citations) >= 3

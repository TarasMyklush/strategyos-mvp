"""Graph-native detectors.

These run over the in-memory structural graph (`knowledge_graph.build_structural_graph`)
during the analyst stage and emit ordinary `Finding` objects through the same
contract as the row-wise detectors in `finance_controls`. They find multi-hop /
ring patterns that pairwise pandas detectors structurally cannot — e.g. three or
more vendors transitively linked by shared bank accounts / tax ids, which the
pairwise `entity_resolution_duplicate` (F-004) only catches as direct pairs.

Design mirrors `finance_controls`: a decorator registry, a runner signature, and
standard `Finding` outputs (citations, recoverable SAR, calculation block) so the
auditor, evidence QA, citation audit, and persistence treat them identically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..config import CONFIG
from ..ingestion import DataBundle
from ..knowledge_graph import StructuralGraph
from ..models import Citation, Finding
from ..sensitive_ids import tokenize_sensitive_identifier
from .finance_controls import excel_citation, unique_citations, usd, _role_source_path


GraphRunner = Callable[[StructuralGraph, DataBundle], list[Finding]]


@dataclass(frozen=True)
class GraphDetectorMetadata:
    name: str
    pattern_type: str
    required_roles: tuple[str, ...]
    runner: GraphRunner


GRAPH_DETECTOR_REGISTRY: list[GraphDetectorMetadata] = []


def register_graph_detector(pattern_type: str, required_roles: Iterable[str]):
    normalized_roles = tuple(str(role) for role in required_roles)

    def decorator(runner: GraphRunner) -> GraphRunner:
        metadata = GraphDetectorMetadata(
            name=runner.__name__,
            pattern_type=str(pattern_type),
            required_roles=normalized_roles,
            runner=runner,
        )
        if any(existing.name == metadata.name for existing in GRAPH_DETECTOR_REGISTRY):
            raise ValueError(f"Graph detector '{metadata.name}' is already registered.")
        if any(existing.pattern_type == metadata.pattern_type for existing in GRAPH_DETECTOR_REGISTRY):
            raise ValueError(f"Pattern type '{metadata.pattern_type}' is already registered.")
        GRAPH_DETECTOR_REGISTRY.append(metadata)
        return runner

    return decorator


def graph_detector_registry() -> tuple[GraphDetectorMetadata, ...]:
    return tuple(GRAPH_DETECTOR_REGISTRY)


def _vendor_id(node_id: str) -> str:
    """`Vendor:V-1142` -> `V-1142`."""
    return node_id.split(":", 1)[1] if ":" in node_id else node_id


def _connected_vendor_components(graph: StructuralGraph) -> list[set[str]]:
    """Connected components over the SAME_BANK_ACCOUNT_AS / SAME_TAX_ID_AS vendor
    edges. A component of size >= 3 is a ring that pairwise detection misses."""
    adjacency: dict[str, set[str]] = {}
    for label in ("SAME_BANK_ACCOUNT_AS", "SAME_TAX_ID_AS"):
        for edge in graph.edges_with_label(label):
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
    seen: set[str] = set()
    components: list[set[str]] = []
    for start in adjacency:
        if start in seen:
            continue
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.add(node)
            stack.extend(adjacency[node] - seen)
        components.append(component)
    return components


@register_graph_detector("vendor_collusion_ring", ("vendor_master", "ap_ledger"))
def detect_vendor_collusion_ring(graph: StructuralGraph, bundle: DataBundle) -> list[Finding]:
    """Three or more vendors transitively connected via shared bank account / tax
    id form a collusion ring. This generalizes the pairwise F-004
    `entity_resolution_duplicate`: a chain V-A~V-B~V-C (A and C share nothing
    directly) is one ring here but invisible to pairwise grouping."""
    findings: list[Finding] = []
    vendors = bundle.vendors
    for component in _connected_vendor_components(graph):
        vendor_ids = sorted(_vendor_id(node_id) for node_id in component)
        if len(vendor_ids) < 3:
            continue  # pairs are already covered by entity_resolution_duplicate (F-004)

        ring_vendors = vendors[vendors["Vendor_ID"].astype(str).isin(vendor_ids)]
        if ring_vendors.empty:
            continue
        ap_rows = bundle.ap[bundle.ap["Vendor_ID"].astype(str).isin(vendor_ids)]
        paid = ap_rows[ap_rows["Status"].eq("Paid")] if not ap_rows.empty else ap_rows
        exposure = float(paid["Amount_SAR"].sum()) if not paid.empty else 0.0

        vendor_names = ring_vendors["Vendor_Name"].astype(str).tolist()
        citations: list[Citation] = []
        for idx, row in ring_vendors.iterrows():
            citations.append(
                excel_citation(
                    bundle,
                    _role_source_path(bundle, "vendor_master"),
                    int(idx),
                    f"{row.Vendor_ID}; {row.Vendor_Name}; "
                    f"Tax_ID_token={tokenize_sensitive_identifier(row.get('Tax_ID'), field_name='Tax_ID') or 'none'}; "
                    f"Bank_Account_token={tokenize_sensitive_identifier(row.get('Bank_Account'), field_name='Bank_Account') or 'none'}; "
                    f"ring={'/'.join(vendor_ids)}",
                )
            )
        for vendor_id in vendor_ids:
            vendor_paid = paid[paid["Vendor_ID"].astype(str).eq(vendor_id)].sort_values("Payment_Date") if not paid.empty else paid
            if vendor_paid is None or vendor_paid.empty:
                continue
            top = vendor_paid.iloc[0]
            citations.append(
                excel_citation(
                    bundle,
                    _role_source_path(bundle, "ap_ledger"),
                    int(top.name),
                    f"{top.Invoice_ID}; {top.Vendor_ID}; ring member; paid SAR {top.Amount_SAR:,.2f}",
                )
            )
        citations = unique_citations(citations)

        findings.append(
            Finding(
                finding_id="draft",
                title=f"Vendor collusion ring across {', '.join(vendor_ids)}",
                pattern_type="vendor_collusion_ring",
                vendor_id="/".join(vendor_ids),
                vendor_name=" / ".join(vendor_names),
                leakage_sar=exposure,
                recoverable_sar=exposure,
                recoverable_usd=usd(exposure),
                confidence="HIGH",
                classification="CASH (recoverable/control dependent)",
                rationale=(
                    f"{len(vendor_ids)} active vendor records are transitively linked through shared "
                    "bank accounts or tax ids, forming a single beneficiary ring. This exceeds a direct "
                    "duplicate pair and indicates coordinated split or duplicate spend across the ring."
                ),
                remediation=(
                    "Vendor master owner should treat the ring as one beneficiary, freeze the non-contract "
                    "members, and review all paid invoices across the ring for duplicate and off-contract recovery."
                ),
                citations=citations,
                calculation={
                    "ring_size": len(vendor_ids),
                    "ring_vendor_ids": vendor_ids,
                    "paid_exposure_sar": exposure,
                },
            )
        )
    return findings

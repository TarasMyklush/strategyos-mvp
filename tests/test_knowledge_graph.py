from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.knowledge_graph import build_knowledge_graph
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def test_knowledge_graph_contains_core_finance_relationships():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    graph = build_knowledge_graph(bundle, findings)
    labels = {node["label"] for node in graph["nodes"]}
    edge_labels = {edge["label"] for edge in graph["edges"]}
    assert {"Vendor", "Invoice", "PurchaseOrder", "Contract", "Evidence", "Finding"}.issubset(labels)
    assert "SAME_TAX_ID_AS" in edge_labels
    assert "SUPPORTED_BY" in edge_labels
    assert graph["meta"]["node_count"] > 100
    assert graph["meta"]["edge_count"] > 100

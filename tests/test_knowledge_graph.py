import json

from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.knowledge_graph import build_knowledge_graph
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.sensitive_ids import tokenize_sensitive_identifier
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


def test_knowledge_graph_hardens_sensitive_identifiers_with_hmac_tokens():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    graph = build_knowledge_graph(bundle, findings)

    vendor_node = next(
        node for node in graph["nodes"] if node["label"] == "Vendor" and node["properties"].get("vendor_id") == "V-1142"
    )
    props = vendor_node["properties"]

    assert props["tax_id_hash"] == tokenize_sensitive_identifier("300187452100003", field_name="Tax_ID")
    assert props["bank_account_hash"] == tokenize_sensitive_identifier("SA0380000000608010167519", field_name="Bank_Account")
    assert props["tax_id_hash"].startswith("hmac:")
    assert props["bank_account_hash"].startswith("hmac:")
    assert "300187452100003" not in json.dumps(props)
    assert "SA0380000000608010167519" not in json.dumps(props)

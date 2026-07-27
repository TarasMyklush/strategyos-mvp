from openpyxl import Workbook

from strategyos_mvp.source_signals import derive_governed_signals


def test_signal_register_is_discovered_by_schema_and_rag_classified(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Signal_ID",
            "Detected",
            "Source type",
            "Source",
            "Type",
            "Affected BU(s)",
            "Signal",
            "Potential impact",
            "Probability",
            "Horizon",
            "Leading indicator to watch",
            "Recommended action",
        ]
    )
    sheet.append(
        [
            "SIG-1",
            "2026-06-01",
            "External",
            "Market brief",
            "Threat",
            "Distribution",
            "Tariff revision",
            "-SAR 7M",
            "High",
            "Sep-2026",
            "Final tariff",
            "Energy programme",
        ]
    )
    sheet.append(
        [
            "SIG-2",
            "2026-06-02",
            "Internal",
            "Order book",
            "Opportunity",
            "Logistics",
            "Cold-chain demand",
            "+SAR 12M",
            "High",
            "H2-2026",
            "Order volume",
            "Protect capacity",
        ]
    )
    workbook.save(tmp_path / "opaque.xlsx")

    payload = derive_governed_signals(tmp_path)

    assert payload["status"] == "ready"
    assert payload["total_item_count"] == 2
    assert payload["items"][0]["tone"] == "critical"
    assert payload["items"][0]["context"]["sources"] == ["External", "Market brief"]
    assert payload["items"][1]["tone"] == "positive"

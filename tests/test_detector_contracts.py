from pathlib import Path

import pandas as pd

from strategyos_mvp.detector_contracts import resolve_detector_contracts_partial


def test_resolve_detector_contracts_partial_follows_symlinked_directories(tmp_path: Path):
    raw_root = tmp_path / "raw"
    linked_root = tmp_path / "linked"
    erp_dir = raw_root / "02_ERP_Extracts"
    erp_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "Invoice_ID": "INV-1",
                "Vendor_ID": "V-1",
                "Amount_SAR": 100.0,
                "Payment_Date": "2026-01-01",
                "PO_Reference": "PO-1",
            }
        ]
    ).to_excel(erp_dir / "AP_Invoices_H1_2026.xlsx", index=False)

    linked_root.mkdir()
    (linked_root / "02_ERP_Extracts").symlink_to(erp_dir, target_is_directory=True)

    resolved, unresolved = resolve_detector_contracts_partial(linked_root)

    assert unresolved
    assert resolved["ap_ledger"].relative_path == "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx"
    assert resolved["ap_ledger"].resolution == "default_path"

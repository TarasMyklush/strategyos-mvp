from strategyos_mvp.state_store import persist_run_claim_snapshot


def test_replayed_snapshot_never_mutates_its_membership():
    class Cursor:
        statements = []
        def execute(self, sql, params):
            self.statements.append(sql)
        def fetchone(self):
            return None  # Existing immutable snapshot, ON CONFLICT DO NOTHING.
    cursor = Cursor()
    assert persist_run_claim_snapshot(cursor, tenant_id="tenant", batch_id="batch",
                                      run_id="run", as_of_at=None) == 0
    assert len(cursor.statements) == 1
    assert "strategyos_analysis_snapshot_claims" not in cursor.statements[0]

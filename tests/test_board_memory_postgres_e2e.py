import os
from uuid import uuid4

import pytest

from strategyos_mvp import board_memory


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated Postgres proof endpoint required.")
    import psycopg
    monkeypatch.setattr(board_memory.state_store, "database_connection", lambda: (psycopg.connect(url), None))
    return url


def test_closed_packet_survives_source_changes_reconnect_and_retries(database):
    import psycopg
    meeting = str(uuid4())
    context = {"approved_answers": {"What was revenue?": "Revenue was SAR 100."}}
    result = board_memory.close_meeting("tenant-a", meeting, run_id="approved-run", actor="ceo",
        approved_context=context, files={"board.pdf": b"original bytes"}, authority={"version": 2})
    original = board_memory.read_meeting("tenant-a", meeting)
    assert board_memory.close_meeting("tenant-a", meeting, run_id="approved-run", actor="ceo",
        approved_context=context, files={"board.pdf": b"original bytes"}, authority={"version": 2}) == result
    context["approved_answers"]["What was revenue?"] = "Revenue was SAR 999."
    reread = board_memory.read_meeting("tenant-a", meeting)
    assert reread == original
    assert "100" in board_memory.answer_from_snapshot(reread, "What was revenue?")["answer"]
    assert board_memory.answer_from_snapshot(reread, "Current salaries?")["matched"] is False
    assert board_memory.read_meeting("tenant-b", meeting) is None
    with pytest.raises(ValueError, match="already closed"):
        board_memory.close_meeting("tenant-a", meeting, run_id="approved-run", actor="ceo",
            approved_context=context, files={"board.pdf": b"changed"}, authority={"version": 3})
    for statement in ("UPDATE strategyos_board_snapshots SET digest='changed' WHERE meeting_id=%s",
                      "DELETE FROM strategyos_board_snapshots WHERE meeting_id=%s"):
        with psycopg.connect(database) as conn:
            with pytest.raises(psycopg.Error, match="immutable"):
                conn.execute(statement, (meeting,))
            conn.rollback()
    assert board_memory.read_meeting("tenant-a", meeting) == original

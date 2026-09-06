import pytest
from tests.test_cross_source_postgres_e2e import ledger
from strategyos_mvp.state_store import _execute_sql_statements

pytestmark = pytest.mark.integration


def test_migration_script_preserves_comments_literals_and_function_bodies(ledger):
    import psycopg
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        _execute_sql_statements(cur,"""
            -- Semicolon in a comment; not a statement boundary.
            create temporary table migration_parser_proof(value text);
            insert into migration_parser_proof values ('first;second');
            do $proof$ begin
                insert into migration_parser_proof values ('third;fourth');
            end $proof$;
        """)
        cur.execute('select value from migration_parser_proof order by value')
        assert cur.fetchall() == [('first;second',),('third;fourth',)]


def test_failed_script_is_atomic(ledger):
    import psycopg
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute('create temporary table migration_atomic_proof(value integer)')
        conn.commit()
        with pytest.raises(psycopg.errors.DivisionByZero):
            _execute_sql_statements(cur,'insert into migration_atomic_proof values (1); select 1/0;')
        conn.rollback()
        cur.execute('select count(*) from migration_atomic_proof')
        assert cur.fetchone()[0] == 0

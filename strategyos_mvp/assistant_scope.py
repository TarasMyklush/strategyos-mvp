"""Server-bound assistant authority for retrieval, independent of question wording."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Mapping

from .authority_matrix import DOMAINS, RIGHT_RANK, assistant_subject
from .governed_finance import FINANCE_HEADLINE_METRIC_KEYS, FINANCE_PRESENTATION_METRIC_KEYS

FINANCE_METRICS = FINANCE_HEADLINE_METRIC_KEYS | FINANCE_PRESENTATION_METRIC_KEYS


@dataclass(frozen=True)
class AssistantScope:
    subject: str
    domains: frozenset[str]


current_scope: ContextVar[AssistantScope | None] = ContextVar('assistant_authority_scope', default=None)


def request_persona(request) -> str:
    context = {**(getattr(request, 'context', None) or {}),
               **(getattr(request, 'assistant_context', None) or {})}
    return str(request.persona or context.get('active_persona') or context.get('persona') or 'ceo').strip().lower()


def metric_domain(metric: str) -> str | None:
    if metric in FINANCE_METRICS:
        return 'finance'
    namespace = str(metric).partition('.')[0]
    return namespace if namespace in DOMAINS else None


def metric_allowed(metric: str, domains: frozenset[str] | None) -> bool:
    return domains is None or metric_domain(metric) in domains


def metric_domain_sql(alias: str = 'f') -> str:
    # The alias is supplied only by repository code, never by a request.
    if alias not in {'f', 'af'}:
        raise ValueError('Unsupported claim-family SQL alias.')
    return f"case when {alias}.metric_key = any(%s::text[]) then 'finance' else split_part({alias}.metric_key, '.', 1) end"


def domain_read_predicate() -> str:
    """Check root and dependency classifications before selecting claim values."""
    domain = metric_domain_sql('af')
    return f"""(%s::text[] is null or not exists (
        with recursive authority_inputs(id) as (
            select r.id
            union
            select d.input_claim_revision_id from strategyos_claim_dependencies d
            join authority_inputs ai on ai.id=d.derived_claim_revision_id
        )
        select 1 from authority_inputs ai
        join strategyos_claim_revisions ar on ar.id=ai.id
        join strategyos_claim_families af on af.id=ar.claim_family_id
        where not (({domain}) = any(%s::text[]))
    ))"""


def domain_read_parameters(domains):
    values = None if domains is None else sorted(domains)
    return values, sorted(FINANCE_METRICS), values


@contextmanager
def bind_assistant(request, principal: Mapping, matrix: Mapping):
    persona = request_persona(request)
    subject = assistant_subject(persona)
    rows = {row['id']: row for row in matrix.get('subjects', [])}
    assistant = rows.get(subject, {}).get('rights', {})
    # An explicit user/persona row can narrow an assistant, never widen it.
    human = rows.get('user:' + str(principal.get('subject') or ''))
    human = human or rows.get('persona:' + ('gm' if persona == 'bu' else persona))
    domains = frozenset(domain for domain in DOMAINS
        if RIGHT_RANK.get(assistant.get(domain), 0) >= RIGHT_RANK['view']
        and (human is None or RIGHT_RANK.get(human.get('rights', {}).get(domain), 0) >= RIGHT_RANK['view']))
    token = current_scope.set(AssistantScope(subject, domains))
    try:
        yield
    finally:
        current_scope.reset(token)


def restrict_legacy_context(context: dict) -> dict:
    """Unclassified legacy prose is not an alternative to authorized records."""
    scope = current_scope.get()
    if scope is None or scope.domains == frozenset(DOMAINS):
        return context
    summary = context.get('summary') or {}
    # This metadata identifies the already-authorized run. Business content is
    # reconstructed separately from the filtered immutable claim snapshot.
    keys = ('run_id', '_backing_run_id', 'run_mode', 'status', 'tenant_context',
            'business_units', 'created_at', 'analysis_at', 'external_use_policy',
            '_claim_policy_context', 'canonical_claim_status', 'claim_snapshot',
            'claim_reconciliation', 'data_period')
    result = {key: summary[key] for key in keys if key in summary}
    if 'finance' in scope.domains and summary.get('canonical_claim_status') in {'ready', 'ready_with_quarantined_inputs'}:
        result['finance_kpi'] = summary.get('finance_kpi')
    return {**context, 'summary': result, 'findings': [], 'kg_nodes': [], 'kg_edges': []}

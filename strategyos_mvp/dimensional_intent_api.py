"""Authenticated dimensional Intent endpoints; no caller-selected filesystem roots."""
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import Field
import psycopg
import os

from .auth import require_role
from .dimensional_plan import Actuals, Contract, Name, Plan
from .plan_decomposition import DecompositionRequest, HistoricalDecompositionRequest
from .advisor_config import AdvisorConfiguration
from .tenant_structure import TenantStructureConfiguration
from . import advisor_config_store as advisor_store
from . import board_pack_store
from . import tenant_structure_store
from . import dimensional_intent_store as store
from .dimensional_intent_sources import SourceUnavailable

Key = Annotated[str, Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Version = Annotated[int, Field(ge=1, strict=True)]


class LimitedRequest(Request):
    async def body(self):
        if not hasattr(self, '_body'):
            chunks, size = [], 0
            async for chunk in self.stream():
                size += len(chunk)
                if size > store.MAX_BYTES:
                    raise HTTPException(413, 'Dimensional request exceeds the 2 MB limit.')
                chunks.append(chunk)
            self._body = b''.join(chunks)
        return self._body


class IntentRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def bounded(request):
            if request.method in {'POST', 'PUT'} and request.cookies.get('strategyos_session'):
                origin = urlsplit(request.headers.get('origin', ''))
                # TLS terminates at the hosted edge. Trust deployment configuration,
                # never caller-controlled forwarded headers, for its public origin.
                expected = urlsplit(os.environ.get('STRATEGYOS_PUBLIC_URL') or str(request.base_url))
                if (origin.scheme, origin.netloc) != (expected.scheme, expected.netloc):
                    raise HTTPException(403, 'A same-origin request is required for this session action.')
            response = await handler(LimitedRequest(request.scope, request.receive))
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        return bounded


router = APIRouter(prefix='/api/intent/dimensional', tags=['Dimensional Intent'], route_class=IntentRoute)


class PlanImport(Contract):
    source_pack_id: Key
    plan: Plan


class ActualImport(Contract):
    source_pack_id: Key
    actuals: Actuals


class RatifierChange(Contract):
    subject: Name
    enabled: bool = Field(strict=True)
    expected_revision: int = Field(ge=0, strict=True)


class Ratification(Contract):
    expected_digest: Digest
    note: str = Field(min_length=20, max_length=2000)


class AdvisorPublication(Contract):
    expected_digest: Digest


class AnalysisRequest(Contract):
    plan_id: Key
    plan_version: Version
    actual_revision: Key
    as_of: date


class RecordedPackRequest(Contract):
    template_id: Key
    template_version: Version
    language: Literal['en', 'ar', 'bilingual'] = 'bilingual'


def perform(fn):
    try:
        return fn()
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except store.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except (store.Conflict, SourceUnavailable) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (store.Unavailable, psycopg.Error) as exc:
        raise HTTPException(503, 'Dimensional Intent persistence is unavailable; contact the operator.') from exc


@router.post('/plans')
def import_plan(body: PlanImport, principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: store.import_plan(principal, body.plan, body.source_pack_id))


@router.get('/plans/{plan_id}/versions/{version}')
def read_plan(plan_id: str, version: Annotated[int, Path(ge=1)],
              principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: store.read_plan(principal, plan_id, version))


@router.post('/plans/{plan_id}/versions/{version}/decompose')
def decompose_plan(plan_id: str, version: Annotated[int, Path(ge=1)], body: DecompositionRequest,
                   principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: store.create_decomposition(principal, plan_id, version, body))


@router.get('/plans/{plan_id}/versions/{version}/history-candidates')
def history_candidates(plan_id: str, version: Annotated[int, Path(ge=1)],
                       parent_cell_id: Key, split_dimension: Key, actual_revision: Key,
                       principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: store.history_candidates(principal, plan_id, version, parent_cell_id,
                                                    split_dimension, actual_revision))


@router.post('/plans/{plan_id}/versions/{version}/decompose-from-history')
def decompose_plan_from_history(plan_id: str, version: Annotated[int, Path(ge=1)],
                                body: HistoricalDecompositionRequest,
                                principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: store.create_history_decomposition(principal, plan_id, version, body))


@router.post('/advisor/configurations')
def create_advisor_configuration(body: AdvisorConfiguration,
                                 principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: advisor_store.create(principal, body))


@router.post('/advisor/structure-configurations')
def create_structure_configuration(body: TenantStructureConfiguration,
                                   principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: tenant_structure_store.create(principal, body))


@router.get('/advisor/structure-configurations')
def structure_configurations(principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: tenant_structure_store.catalog(principal))


@router.get('/advisor/structure-configurations/{config_id}/versions/{version}')
def read_structure_configuration(config_id: str, version: Annotated[int, Path(ge=1)],
                                 principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: tenant_structure_store.read(principal, config_id, version))


@router.post('/advisor/structure-configurations/{config_id}/versions/{version}/approve')
def approve_structure_configuration(config_id: str, version: Annotated[int, Path(ge=1)], body: Ratification,
                                    principal: dict[str, Any] = require_role('tenant_admin')):
    return perform(lambda: tenant_structure_store.approve(
        principal, config_id, version, body.expected_digest, body.note))


@router.get('/advisor/configurations')
def advisor_configurations(principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: advisor_store.catalog(principal))


@router.get('/advisor/configurations/{config_id}/versions/{version}')
def read_advisor_configuration(config_id: str, version: Annotated[int, Path(ge=1)],
                               principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: advisor_store.read(principal, config_id, version))


@router.post('/advisor/configurations/{config_id}/versions/{version}/approve')
def approve_advisor_configuration(config_id: str, version: Annotated[int, Path(ge=1)], body: Ratification,
                                  principal: dict[str, Any] = require_role('reviewer', 'executive')):
    return perform(lambda: advisor_store.approve(principal, config_id, version, body.expected_digest, body.note))


@router.post('/advisor/configurations/{config_id}/versions/{version}/publish')
def publish_advisor_configuration(config_id: str, version: Annotated[int, Path(ge=1)], body: AdvisorPublication,
                                  principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: advisor_store.publish(principal, config_id, version, body.expected_digest))


@router.get('/advisor/configurations/{config_id}/versions/{version}/board-template')
def advisor_board_template(config_id: str, version: Annotated[int, Path(ge=1)],
                           principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: advisor_store.template(principal, config_id, version))


@router.post('/advisor/configurations/{config_id}/versions/{version}/board-template/register')
def register_advisor_board_template(config_id: str, version: Annotated[int, Path(ge=1)],
                                    principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: board_pack_store.register_advisor(principal, config_id, version))


@router.put('/plans/{plan_id}/ratifier')
def set_ratifier(plan_id: str, body: RatifierChange,
                 principal: dict[str, Any] = require_role('tenant_admin')):
    return perform(lambda: store.set_ratifier(principal, plan_id, body.subject, body.enabled, body.expected_revision))


@router.get('/plans/{plan_id}/ratifier')
def read_ratifier(plan_id: str, subject: Annotated[str, Query(min_length=1, max_length=160)],
                  principal: dict[str, Any] = require_role('tenant_admin')):
    return perform(lambda: store.read_ratifier(principal, plan_id, subject))


@router.post('/plans/{plan_id}/versions/{version}/ratify')
def ratify(plan_id: str, version: Annotated[int, Path(ge=1)], body: Ratification,
           principal: dict[str, Any] = require_role('executive', 'reviewer')):
    return perform(lambda: store.ratify(principal, plan_id, version, body.expected_digest, body.note))


@router.post('/actuals')
def import_actuals(body: ActualImport, principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: store.import_actuals(principal, body.actuals, body.source_pack_id))


@router.get('/actuals/{revision}')
def read_actuals(revision: str, principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: store.read_actuals(principal, revision))


@router.post('/analyses')
def create_analysis(body: AnalysisRequest, principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: store.create_analysis(principal, body.plan_id, body.plan_version, body.actual_revision, body.as_of))


@router.get('/analyses/{analysis_id}')
def read_analysis(analysis_id: str, principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: store.read_analysis(principal, analysis_id))


@router.get('/analyses/{analysis_id}/evidence')
def evidence(analysis_id: str, cell_id: Annotated[str, Query(min_length=1, max_length=160)],
             side: Literal['plan', 'actuals'],
             principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    filename, content = perform(lambda: store.evidence_bytes(principal, analysis_id, cell_id, side))
    return Response(content=content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


@router.get('/catalog')
def catalog(offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=50)] = 25,
            principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: store.catalog(principal, offset, limit))


@router.get('/plans/{plan_id}/versions/{version}/evidence')
def plan_evidence(plan_id: str, version: Annotated[int, Path(ge=1)],
                  cell_id: Annotated[str, Query(min_length=1, max_length=160)],
                  principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    filename, content = perform(lambda: store.plan_evidence_bytes(principal, plan_id, version, cell_id))
    return Response(content=content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


from . import board_pack


@router.get('/board-pack/template')
def board_template(principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    perform(lambda: store._scope(principal))
    return board_pack.PackTemplate().model_dump(mode='json')


@router.post('/board-templates')
def register_board_template(body: board_pack.PackTemplate,
                            principal: dict[str, Any] = require_role('operator')):
    return perform(lambda: board_pack_store.register(principal, body))


@router.get('/board-templates')
def board_templates(principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack_store.templates(principal))


@router.get('/board-templates/{template_id}/versions/{version}')
def read_board_template(template_id: str, version: Annotated[int, Path(ge=1)],
                        principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack_store.read_template(principal, template_id, version))


@router.post('/analyses/{analysis_id}/board-packs')
def create_recorded_board_pack(analysis_id: str, body: RecordedPackRequest,
                               principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack_store.create_pack(
        principal, analysis_id, body.template_id, body.template_version, body.language))


@router.get('/board-packs')
def board_pack_history(analysis_id: str | None = None,
                       limit: Annotated[int, Query(ge=1, le=50)] = 25,
                       principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack_store.packs(principal, analysis_id, limit))


@router.get('/board-packs/{pack_id}')
def read_recorded_board_pack(pack_id: str,
                             principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack_store.read_pack(principal, pack_id))


@router.get('/board-packs/{pack_id}/{format}')
def download_recorded_board_pack(pack_id: str, format: Literal['pdf', 'pptx'],
                                 principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    record = perform(lambda: board_pack_store.read_pack(principal, pack_id))
    origin = urlsplit(os.environ.get('STRATEGYOS_PUBLIC_URL', ''))
    public_url = f'{origin.scheme}://{origin.netloc}' if origin.scheme in {'https', 'http'} and origin.netloc else ''
    content = perform(lambda: (board_pack.export_pdf if format == 'pdf' else board_pack.export_pptx)(record['pack'], public_url))
    media = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    return Response(content=content, media_type=media, headers={
        'Content-Disposition': f'attachment; filename="kyvern-board-{pack_id[:16]}.{format}"',
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store',
        'X-Kyvern-Pack-Hash': pack_id, 'X-Kyvern-Pack-Freshness': record['freshness']['status']})


@router.post('/analyses/{analysis_id}/board-pack')
def board_preview(analysis_id: str, body: board_pack.PackRequest,
                  principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    return perform(lambda: board_pack.compose(principal, analysis_id, body))


@router.post('/analyses/{analysis_id}/board-pack/{format}')
def board_export(analysis_id: str, format: Literal['pdf', 'pptx'], body: board_pack.PackRequest,
                 principal: dict[str, Any] = require_role('operator', 'reviewer', 'executive')):
    pack = perform(lambda: board_pack.compose(principal, analysis_id, body))
    origin = urlsplit(os.environ.get('STRATEGYOS_PUBLIC_URL', ''))
    public_url = f'{origin.scheme}://{origin.netloc}' if origin.scheme in {'https', 'http'} and origin.netloc else ''
    content = perform(lambda: (board_pack.export_pdf if format == 'pdf' else board_pack.export_pptx)(pack, public_url))
    media = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    return Response(content=content, media_type=media, headers={
        'Content-Disposition': f'attachment; filename="kyvern-board-{pack["pack_hash"][:16]}.{format}"',
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store',
        'X-Kyvern-Pack-Hash': pack['pack_hash']})

"""Index approved source rows/pages with exact citations into the scoped collection."""
from pathlib import Path
from itertools import islice
import hashlib
import logging
logger = logging.getLogger(__name__)
from . import semantic_embeddings, vector_store
from .evidence import sha256_file

MAX_FILE_ROWS = 10000
MAX_CHUNKS = 50000
CACHE_POINT_TYPE = 'source_embedding_cache'
CACHE_BATCH_SIZE = 64
CACHE_BOOTSTRAP_SCROLL_SIZE = 32


def _embedding_text(relative, text):
    return Path(relative).stem + ': ' + text


def _embedding_cache_identity(tenant_slug, embedding_text):
    content_hash = hashlib.sha256(
        ('passage: ' + embedding_text).encode('utf-8')
    ).hexdigest()
    point_id = vector_store._point_id(
        tenant_slug,
        CACHE_POINT_TYPE,
        semantic_embeddings.MODEL_REVISION,
        content_hash,
    )
    return point_id, content_hash


def _valid_cache_point(point, *, tenant_slug, content_hash):
    payload = point.get('payload') or {}
    vector = point.get('vector')
    return (
        payload.get('tenant_slug') == tenant_slug
        and payload.get('point_type') == CACHE_POINT_TYPE
        and payload.get('model_revision') == semantic_embeddings.MODEL_REVISION
        and payload.get('content_hash') == content_hash
        and isinstance(vector, list)
        and len(vector) == semantic_embeddings.DIMENSIONS
    )


def _cache_point(*, point_id, tenant_slug, content_hash, vector):
    return {
        'id': point_id,
        'vector': vector,
        'payload': {
            'tenant_slug': tenant_slug,
            'point_type': CACHE_POINT_TYPE,
            'model_revision': semantic_embeddings.MODEL_REVISION,
            'content_hash': content_hash,
        },
    }


def _retrieve_cache_vectors(descriptors, *, tenant_slug):
    """Return only exact, tenant-local vectors for this pinned model revision."""
    if not descriptors:
        return {}
    result = {}
    by_id = {item['cache_id']: item for item in descriptors}
    all_ids = list(by_id)
    for offset in range(0, len(all_ids), CACHE_BATCH_SIZE):
        ids = all_ids[offset:offset + CACHE_BATCH_SIZE]
        response = vector_store._qdrant_request(
            'POST',
            f'/collections/{vector_store.COLLECTION_NAME}/points',
            {
                'ids': ids,
                'with_payload': ['tenant_slug', 'point_type', 'model_revision', 'content_hash'],
                'with_vector': True,
            },
        )
        for point in response.get('result', []):
            point_id = str(point.get('id') or '')
            descriptor = by_id.get(point_id)
            if descriptor and _valid_cache_point(
                point,
                tenant_slug=tenant_slug,
                content_hash=descriptor['content_hash'],
            ):
                result[point_id] = point['vector']
    return result


def _bootstrap_embedding_cache(*, tenant_slug, descriptors):
    """Adopt compatible historical vectors into the persistent cache once.

    Older releases stored the same pinned-model vector only on run-scoped
    source points. Scanning those points is bounded by Qdrant pagination and
    writes no source text to the cache; it prevents a release from needlessly
    recomputing tens of thousands of unchanged embeddings.
    """
    needed = {item['cache_id']: item for item in descriptors}
    if not needed:
        return 0
    already_cached = _retrieve_cache_vectors(list(needed.values()), tenant_slug=tenant_slug)
    for point_id in already_cached:
        needed.pop(point_id, None)
    if not needed:
        return 0

    seeded = 0
    pending = []
    page_offset = None
    while needed:
        payload = {
            'limit': CACHE_BOOTSTRAP_SCROLL_SIZE,
            'filter': {
                'must': [
                    {'key': 'tenant_slug', 'match': {'value': tenant_slug}},
                    {'key': 'point_type', 'match': {'value': 'source_chunk'}},
                ]
            },
            'with_payload': ['source_path', 'title', 'text'],
            'with_vector': True,
        }
        if page_offset is not None:
            payload['offset'] = page_offset
        response = vector_store._qdrant_request(
            'POST',
            f'/collections/{vector_store.COLLECTION_NAME}/points/scroll',
            payload,
        ).get('result', {})
        points = response.get('points') or []
        for point in points:
            source_payload = point.get('payload') or {}
            text = source_payload.get('text')
            source_path = source_payload.get('source_path')
            if not isinstance(text, str) or not isinstance(source_path, str):
                continue
            embedding_text = str(source_payload.get('title') or Path(source_path).stem) + ': ' + text
            cache_id, content_hash = _embedding_cache_identity(tenant_slug, embedding_text)
            descriptor = needed.get(cache_id)
            vector = point.get('vector')
            if (
                descriptor
                and descriptor['content_hash'] == content_hash
                and isinstance(vector, list)
                and len(vector) == semantic_embeddings.DIMENSIONS
            ):
                pending.append(_cache_point(
                    point_id=cache_id,
                    tenant_slug=tenant_slug,
                    content_hash=content_hash,
                    vector=vector,
                ))
                needed.pop(cache_id, None)
                seeded += 1
                if len(pending) >= CACHE_BATCH_SIZE:
                    vector_store._qdrant_request(
                        'PUT',
                        f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true',
                        {'points': pending},
                    )
                    pending = []
        page_offset = response.get('next_page_offset')
        if page_offset is None or not points:
            break
    if pending:
        vector_store._qdrant_request(
            'PUT',
            f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true',
            {'points': pending},
        )
    return seeded


def source_records(evidence):
    root = evidence.dataset_root.resolve()
    for relative, entry in sorted(evidence.manifest.items()):
        from .source_governance import initial_source_disposition, CONTROL_PLANE, EVALUATOR_ONLY
        if initial_source_disposition(relative) in {CONTROL_PLANE, EVALUATOR_ONLY}:
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != entry['sha256']:
            raise ValueError('Source changed after ingestion; semantic indexing was stopped.')
        if relative in evidence.pdf_text:
            for page, text in enumerate(evidence.pdf_text[relative], start=1):
                for chunk in vector_store._chunk_text(text):
                    yield relative, entry['sha256'], f'PDF page {page}', chunk
        elif path.suffix.lower() in {'.txt', '.md'}:
            text = path.read_text(encoding='utf-8-sig')
            if len(text) > 2_000_000:
                raise ValueError(f'{relative}: text exceeds reviewed indexing capacity.')
            for number, chunk in enumerate(vector_store._chunk_text(text), start=1):
                yield relative, entry['sha256'], f'Text chunk {number}', chunk
        elif path.suffix.lower() == '.docx':
            from zipfile import ZipFile
            from xml.etree import ElementTree
            with ZipFile(path) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > 2_000_000:
                    raise ValueError(f'{relative}: document exceeds reviewed indexing capacity.')
                document = ElementTree.fromstring(archive.read(info))
            namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for number, paragraph in enumerate(document.iter(namespace + 'p'), start=1):
                text = ''.join(node.text or '' for node in paragraph.iter(namespace + 't'))
                for chunk in vector_store._chunk_text(text):
                    yield relative, entry['sha256'], f'Document paragraph {number}', chunk
        elif path.suffix.lower() == '.xlsx':
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    if sheet.max_row is not None and sheet.max_row > MAX_FILE_ROWS:
                        raise ValueError(f'{relative}: worksheet exceeds the reviewed indexing capacity.')
                    rows = sheet.iter_rows(values_only=True)
                    headers = [str(x or '') for x in next(rows, ())]
                    header_keys = {header.strip().casefold() for header in headers}
                    if 'question' in header_keys and {'answer type', 'where strategyos finds the answer'} & header_keys:
                        continue
                    for number, values in enumerate(rows, start=2):
                        if number > MAX_FILE_ROWS:
                            raise ValueError(f"{relative}: worksheet exceeds the reviewed indexing capacity.")
                        text = '; '.join(f'{headers[i] if i < len(headers) else i}: {value}' for i, value in enumerate(values) if value is not None)
                        if text:
                            yield relative, entry['sha256'], f'{sheet.title}!Excel row {number}', text[:vector_store.MAX_INDEX_TEXT]
            finally:
                book.close()


def sync_sources(*, run_id, tenant_slug, evidence):
    if not semantic_embeddings.configured():
        return {'status': 'disabled', 'reason': 'No pinned local embedding model configured.'}
    if evidence is None:
        raise ValueError("Source evidence is unavailable; indexing cannot continue.")
    from .access_scope import source_index_allowed
    if not source_index_allowed(run_id, tenant_slug):
        return {'status': 'blocked', 'reason': 'Source policy does not permit source-text indexing.'}
    vector_store._run_filter(run_id)  # Reject unknown or inaccessible runs before reading source files.
    vector_store._ensure_collection()
    # Preflight the entire bounded manifest before writing any index records.
    records = list(islice(source_records(evidence), MAX_CHUNKS + 1))
    if len(records) > MAX_CHUNKS:
        raise ValueError('Source pack exceeds reviewed semantic indexing capacity.')
    descriptors = []
    for relative, digest, locator, text in records:
        embedding_text = _embedding_text(relative, text)
        cache_id, content_hash = _embedding_cache_identity(tenant_slug, embedding_text)
        descriptors.append({
            'relative': relative,
            'digest': digest,
            'locator': locator,
            'text': text,
            'embedding_text': embedding_text,
            'cache_id': cache_id,
            'content_hash': content_hash,
        })
    cache_seeded = _bootstrap_embedding_cache(
        tenant_slug=tenant_slug,
        descriptors=descriptors,
    )
    allowed_paths = sorted({record[0] for record in records})
    obsolete_filter = {'must': [{'key':key, 'match':{'value':value}} for key,value in
                       (('run_id',run_id),('tenant_slug',tenant_slug),('point_type','source_chunk'))]}
    if allowed_paths:
        obsolete_filter['must_not'] = [{'key':'source_path','match':{'any':allowed_paths}}]
    vector_store._qdrant_request('POST', f'/collections/{vector_store.COLLECTION_NAME}/points/delete?wait=true', {'filter':obsolete_filter})
    reused = 0
    cache_hits = 0
    embedded = 0
    for offset in range(0, len(descriptors), CACHE_BATCH_SIZE):
        batch = []
        descriptor_by_point = {}
        for descriptor in descriptors[offset:offset + CACHE_BATCH_SIZE]:
            relative = descriptor['relative']
            digest = descriptor['digest']
            locator = descriptor['locator']
            text = descriptor['text']
            point_id = vector_store._point_id(run_id, 'source_chunk', relative, locator, text)
            batch.append({'id': point_id,
                          'payload': {'run_id': run_id, 'tenant_slug': tenant_slug, 'point_type': 'source_chunk',
                                      'source_path': relative, 'source_hash': digest, 'locator': locator,
                                      'title': Path(relative).stem, 'text': text, 'excerpt': text[:700]}})
            descriptor_by_point[point_id] = descriptor
        stored = vector_store._qdrant_request('POST', f'/collections/{vector_store.COLLECTION_NAME}/points',
                    {'ids': [point['id'] for point in batch], 'with_payload': ['run_id', 'tenant_slug', 'source_hash'], 'with_vector': False})
        existing = {str(point['id']): point.get('payload', {}) for point in stored.get('result', [])}
        missing = [point for point in batch if not all(existing.get(point['id'], {}).get(key) == point['payload'][key]
                   for key in ('run_id', 'tenant_slug', 'source_hash'))]
        reused += len(batch) - len(missing)
        missing_descriptors = [descriptor_by_point[point['id']] for point in missing]
        cached_vectors = _retrieve_cache_vectors(missing_descriptors, tenant_slug=tenant_slug)
        uncached = []
        for point in missing:
            descriptor = descriptor_by_point[point['id']]
            vector = cached_vectors.get(descriptor['cache_id'])
            if vector is None:
                uncached.append((point, descriptor))
            else:
                point['vector'] = vector
                reused += 1
                cache_hits += 1
        if uncached:
            vectors = semantic_embeddings.embed_many([
                descriptor['embedding_text'] for _, descriptor in uncached
            ])
            cache_points = []
            for (point, descriptor), vector in zip(uncached, vectors):
                point['vector'] = vector
                cache_points.append(_cache_point(
                    point_id=descriptor['cache_id'],
                    tenant_slug=tenant_slug,
                    content_hash=descriptor['content_hash'],
                    vector=vector,
                ))
            embedded += len(cache_points)
            vector_store._qdrant_request(
                'PUT',
                f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true',
                {'points': cache_points},
            )
        if missing:
            vector_store._qdrant_request('PUT', f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true', {'points': missing})
        if offset % 1024 == 0:
            logger.info('Semantic source index: %s/%s records, %s reused', min(offset + 64, len(records)), len(records), reused)
    return {'status': 'ready', 'point_count': len(records), 'reused_points': reused,
            'embedding_cache_hits': cache_hits, 'embedding_cache_seeded': cache_seeded,
            'embedded_points': embedded,
            'collection': vector_store.COLLECTION_NAME, 'model_revision': semantic_embeddings.MODEL_REVISION}


def retrieve(run_id, question):
    if not semantic_embeddings.configured():
        return None
    result = vector_store.search_run_vectors(run_id, question, limit=12, point_type='source_chunk')
    if result.get('status') != 'ready':
        return {'status': 'unavailable', 'reason': result.get('reason')}
    return {'status': 'ready', 'records': [{key: row.get(key) for key in
            ('source_path', 'source_hash', 'locator', 'text', 'score')} for row in result.get('results', [])]}


def targeted_financial_records(evidence, question):
    """Complement semantic hits with bounded, explicitly named financial tables.

    A narrow topic contract prevents a near-neighbour search miss from being
    presented as absence of a connected payroll or peer-comparison workbook.
    """
    import re
    from types import SimpleNamespace
    text = str(question).casefold()
    patterns = []
    if re.search(r'\b(?:employee|employees|headcount|payroll|wage|wages)\b', text):
        patterns += ['headcount_payroll']
    if re.search(r'\bper employee\b', text):
        patterns += ['group_bu_pnl']
    if re.search(r'\b(?:peer|peers|competitor|competitors)\b', text):
        patterns += ['competitor_financials', 'group_bu_pnl']
    if re.search(r'\b(?:synergy|synergies|insourcing)\b', text):
        patterns += ['synergy_programme_charter', 'synergy_program_charter']
    customer_question = bool(re.search(r'\b(?:customer|customers|profitability|pricing|prices|terms)\b', text))
    revenue_question = bool(re.search(r'\b(?:revenue|growth|segment|segments)\b', text))
    if customer_question or revenue_question:
        patterns += ['revenue_analytics']
    if revenue_question:
        patterns += ['group_bu_pnl']
    manifest = {path: entry for path, entry in evidence.manifest.items()
                if path.lower().endswith(('.xlsx', '.docx')) and any(token in Path(path).stem.casefold() for token in patterns)}
    if not manifest:
        return {'status': 'not_applicable', 'records': []}
    records = []; characters = 0
    # Group bridges must not disappear behind a long division-level series.
    paths = sorted(manifest, key=lambda path: ('group_bu_pnl' not in Path(path).stem.casefold(), path))
    def selected_records():
        for path in paths:
            scoped = SimpleNamespace(dataset_root=evidence.dataset_root, manifest={path: manifest[path]}, pdf_text={})
            yield from source_records(scoped)
    try:
        for path, digest, locator, content in selected_records():
            if 'revenue_analytics' in Path(path).stem.casefold():
                customer_sheet = locator.startswith(('Customer_Profitability', 'Top_Customers'))
                if customer_sheet != customer_question:
                    continue
            if len(records) >= 96 or characters + len(content) > 30000:
                return {'status': 'bounded', 'coverage_complete': False, 'records': records}
            records.append({'source_path': path, 'source_hash': digest, 'locator': locator, 'text': content})
            characters += len(content)
    except (ValueError, OSError):
        return {'status': 'unavailable', 'reason': 'Required source bytes failed verification.', 'records': []}
    return {'status': 'ready', 'coverage_complete': True, 'records': records}

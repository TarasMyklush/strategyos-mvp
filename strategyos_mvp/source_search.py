"""Index approved source rows/pages with exact citations into the scoped collection."""
from pathlib import Path
from . import semantic_embeddings, vector_store
from .evidence import sha256_file

MAX_FILE_ROWS = 10000
MAX_CHUNKS = 50000


def source_records(evidence):
    root = evidence.dataset_root.resolve()
    for relative, entry in sorted(evidence.manifest.items()):
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != entry['sha256']:
            raise ValueError('Source changed after ingestion; semantic indexing was stopped.')
        if relative in evidence.pdf_text:
            for page, text in enumerate(evidence.pdf_text[relative], start=1):
                for chunk in vector_store._chunk_text(text):
                    yield relative, entry['sha256'], f'PDF page {page}', chunk
        elif path.suffix.lower() == '.xlsx':
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    if sheet.max_row > MAX_FILE_ROWS:
                        raise ValueError(f'{relative}: worksheet exceeds the reviewed indexing capacity.')
                    rows = sheet.iter_rows(values_only=True)
                    headers = [str(x or '') for x in next(rows, ())]
                    for number, values in enumerate(rows, start=2):
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
    vector_store._run_filter(run_id)  # Reject unknown or inaccessible runs before reading source files.
    vector_store._ensure_collection()
    count, batch = 0, []
    for relative, digest, locator, text in source_records(evidence):
        count += 1
        if count > MAX_CHUNKS:
            raise ValueError('Source pack exceeds reviewed semantic indexing capacity.')
        point = {'id': vector_store._point_id(run_id, 'source_chunk', relative, locator, text),
                 'vector': semantic_embeddings.embed(Path(relative).stem + ': ' + text),
                 'payload': {'run_id': run_id, 'tenant_slug': tenant_slug, 'point_type': 'source_chunk',
                             'source_path': relative, 'source_hash': digest, 'locator': locator,
                             'title': Path(relative).stem, 'text': text, 'excerpt': text[:700]}}
        batch.append(point)
        if len(batch) == 64:
            vector_store._qdrant_request('PUT', f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true', {'points': batch})
            batch.clear()
    if batch:
        vector_store._qdrant_request('PUT', f'/collections/{vector_store.COLLECTION_NAME}/points?wait=true', {'points': batch})
    return {'status': 'ready', 'point_count': count, 'collection': vector_store.COLLECTION_NAME,
            'model_revision': semantic_embeddings.MODEL_REVISION}


def retrieve(run_id, question):
    if not semantic_embeddings.configured():
        return None
    result = vector_store.search_run_vectors(run_id, question, limit=12, point_type='source_chunk')
    if result.get('status') != 'ready':
        return {'status': 'unavailable', 'reason': result.get('reason')}
    return {'status': 'ready', 'records': [{key: row.get(key) for key in
            ('source_path', 'source_hash', 'locator', 'text', 'score')} for row in result.get('results', [])]}

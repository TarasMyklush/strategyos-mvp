"""Resolve dimensional evidence only through an owned, registered source pack."""
from pathlib import Path, PurePosixPath
import json

from .config import CONFIG
from .dimensional_plan import fingerprint, verify_source
from .source_governance import CURRENT_EVIDENCE, HISTORIC_CONTEXT, initial_source_disposition, is_agent_evidence_path


class SourceUnavailable(ValueError):
    pass


def registered_sources(tenant: str, pack_id: str, references, *, verify_bytes: bool = True):
    """Recheck current eligibility on every access; never accept a caller's root.

    Historical context is eligible only as an explicit source reference here, not
    silently reclassified as current financial evidence. Restricted/evaluator/
    control/quarantined sources fail even for administrator identities.
    """
    if tenant != CONFIG.tenant_slug:
        raise PermissionError('Source pack not found in this deployment.')
    base = (CONFIG.output_root / 'source_packs').resolve()
    directory = (base / pack_id).resolve()
    if not pack_id or Path(pack_id).name != pack_id or directory.parent != base or (base / pack_id).is_symlink():
        raise SourceUnavailable('Invalid source pack identifier.')
    try:
        summary_path = directory / 'summary.json'
        if summary_path.is_symlink():
            raise SourceUnavailable('Source pack metadata must not be a symbolic link.')
        summary = json.loads(summary_path.read_text())
    except (OSError, ValueError) as exc:
        raise SourceUnavailable('Registered source pack metadata is unavailable.') from exc
    if (summary.get('tenant_context') or {}).get('tenant_id') != tenant:
        raise PermissionError('Source pack not found in this tenant.')
    if summary.get('source_pack_id') != pack_id:
        raise SourceUnavailable('Source pack identity mismatch.')
    raw = directory / 'raw'
    root = raw.resolve()
    if raw.is_symlink() or root != directory / 'raw' or not root.is_dir():
        raise SourceUnavailable('Registered evidence root is unavailable.')
    entries = {}
    for item in summary.get('manifest') or []:
        name = item.get('relative_path')
        if not isinstance(name, str) or name in entries:
            raise SourceUnavailable('Ambiguous source manifest.')
        entries[name] = item
    receipts, checked = [], set()
    for source in references:
        name = source.path
        if str(PurePosixPath(name)) != name or '..' in PurePosixPath(name).parts or '\\' in name:
            raise SourceUnavailable('Noncanonical source reference.')
        item = entries.get(name)
        allowed = {CURRENT_EVIDENCE, HISTORIC_CONTEXT}
        if (not item or item.get('supported') is not True or
            item.get('source_disposition') not in allowed or initial_source_disposition(name) not in allowed or
            not is_agent_evidence_path(name) or any(part in {'evaluator_only', 'control_plane'} for part in PurePosixPath(name).parts)):
            raise SourceUnavailable('A referenced source is not eligible for dimensional intent.')
        if item.get('sha256') != source.sha256:
            raise SourceUnavailable('Source reference differs from its registered hash.')
        if (root / name).resolve() != root / name:
            raise SourceUnavailable('Source references cannot traverse symbolic links.')
        key = (name, source.sha256)
        if verify_bytes and key not in checked:
            try:
                verify_source(root, source)
            except (ValueError, OSError) as exc:
                raise SourceUnavailable('Registered source bytes changed or are unavailable.') from exc
            checked.add(key)
        receipts.append({'path': name, 'sha256': source.sha256, 'locator': source.locator,
                         'disposition': item['source_disposition']})
    return root, {'source_pack_id': pack_id,
                  'references_hash': fingerprint(sorted(receipts, key=lambda x: (x['path'], x['locator'], x['sha256'])))}

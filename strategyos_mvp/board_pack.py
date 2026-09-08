"""Deterministic board packs over immutable Intent analyses; no model-authored numbers.

Templates are portable client pack artifacts. Exports are snapshots, not live decks.
Source export authorization and byte integrity are rechecked on every composition.
"""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
import re

from pydantic import Field, field_validator

from . import dimensional_intent_store as store
from .dimensional_plan import Contract, Plan, Actuals, fingerprint
from .dimensional_intent_sources import registered_sources


class Translation(Contract):
    en: str = Field(min_length=1, max_length=100)
    ar: str = Field(min_length=1, max_length=100)

    @field_validator('en', 'ar')
    @classmethod
    def printable(cls, value):
        if any(ord(c) < 32 or c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in value):
            raise ValueError('Template text must be a single line without direction overrides.')
        return value.strip()


class PackTemplate(Contract):
    schema_version: Literal[1] = 1
    template_id: str = Field(default='kyvern-board', pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    version: int = Field(default=1, ge=1, strict=True)
    title: Translation = Field(default_factory=lambda: Translation(en='Board performance review', ar='مراجعة الأداء لمجلس الإدارة'))
    client: Translation = Field(default_factory=lambda: Translation(en='Kyvern', ar='كايفرن'))
    accent: str = Field(default='#72533F', pattern=r'^#[0-9a-fA-F]{6}$')
    labels: dict[str, Translation] = Field(default_factory=dict, max_length=200)


class PackRequest(Contract):
    template: PackTemplate = Field(default_factory=PackTemplate)
    language: Literal['en', 'ar', 'bilingual'] = 'bilingual'


WORDS = {
    'summary': ('Performance summary', 'ملخص الأداء'), 'cells': ('Plan cells', 'بنود الخطة'),
    'evidence': ('Evidence references', 'مراجع الأدلة'), 'target': ('Target', 'المستهدف'),
    'actual': ('Actual', 'الفعلي'), 'variance': ('Variance', 'الانحراف'),
    'missing': ('Missing', 'غير متوفر'), 'on_plan': ('On plan', 'وفق الخطة'),
    'ahead': ('Ahead', 'متقدم'), 'behind': ('Behind', 'متأخر'), 'incomplete': ('Incomplete', 'غير مكتمل'),
    'owner': ('Owner', 'المسؤول'), 'status': ('Status', 'الحالة'),
    'offset': ('An aggregate result masks cells behind plan.', 'النتيجة الإجمالية تخفي بنوداً متأخرة عن الخطة.'),
    'coverage': ('Measured / planned cells', 'البنود المقاسة / المخططة'),
    'new_plan': ('A newer ratified plan exists for this period. Re-run the comparison to use it.', 'توجد خطة معتمدة أحدث لهذه الفترة. أعد المقارنة لاستخدامها.'),
    'new_actuals': ('Newer actual snapshots exist for this period. Review their scope before selecting a replacement.', 'توجد لقطات فعلية أحدث لهذه الفترة. راجع نطاقها قبل اختيار بديل.'),
    'snapshot': ('Fixed snapshot. Downloaded files do not refresh automatically.', 'لقطة ثابتة. الملفات المحملة لا تتحدث تلقائياً.'),
    'assurance': ('Evidence file integrity checked; source values are not independently certified.', 'تم التحقق من سلامة ملفات الأدلة؛ لم يتم التصديق على قيم المصادر بشكل مستقل.'),
    'unplanned': ('Unplanned actual tuples: ', 'بنود فعلية خارج الخطة: '),
}


def word(key, language):
    pair = WORDS[key]
    return pair[0] if language == 'en' else pair[1] if language == 'ar' else pair[0] + ' | ' + pair[1]


def translated(value, language):
    return value.en if language == 'en' else value.ar if language == 'ar' else value.en + ' | ' + value.ar


def compose(principal, analysis_id, request):
    tenant, _ = store._scope(principal)
    result = store.read_analysis(principal, analysis_id)
    # Bound work and export size. Never silently truncate a board report.
    if len(result['cells']) > 200 or len(result['rollups']) > 30:
        raise ValueError('This composer supports up to 200 cells and 30 metrics. Use a smaller reporting plan.')
    with store._connection() as conn:
        plan = store._plan(conn, tenant, result['plan_id'], result['plan_version'])
        actual = store._actuals(conn, tenant, result['actual_revision'])
        cursor = conn.execute('''SELECT p.* FROM strategyos_intent_plan_versions p
            JOIN strategyos_intent_ratifications r USING(tenant_key,plan_id,version)
            WHERE p.tenant_key=%s AND p.plan_id=%s AND p.version>%s
            AND p.payload->'period'=%s::jsonb ORDER BY p.version DESC''',
            (tenant, plan['plan_id'], plan['version'], store._encode(plan['payload']['period'])))
        newer_plans = [dict(zip([c.name for c in cursor.description], r)) for r in cursor.fetchall()]
        cursor = conn.execute('''SELECT * FROM strategyos_intent_actual_versions
            WHERE tenant_key=%s AND imported_at>%s AND payload->'period'=%s::jsonb ORDER BY imported_at DESC''',
            (tenant, actual['imported_at'], store._encode(actual['payload']['period'])))
        newer_actuals = [dict(zip([c.name for c in cursor.description], r)) for r in cursor.fetchall()]
    for row, model, field in [(plan, Plan, 'cells'), (actual, Actuals, 'observations')]:
        references = [item.source for item in getattr(model.model_validate(row['payload']), field)]
        registered_sources(tenant, row['source_pack_id'], references, principal=principal, purpose='export')
    # Do not disclose revisions from a source whose access has been revoked.
    from .dimensional_intent_sources import SourceUnavailable
    warnings, newer_records = [], {}
    for key, candidates, kind in [('new_plan', newer_plans, 'plan'), ('new_actuals', newer_actuals, 'actuals')]:
        for row in candidates:
            store._checked(row)
            try:
                store._sources(principal, row, kind=kind, verify_bytes=False)
            except (PermissionError, SourceUnavailable):
                continue
            warnings.append(key)
            newer_records[key] = ({'plan_id': row['plan_id'], 'version': row['version'], 'digest': row['digest']}
                                  if kind == 'plan' else {'revision': row['revision'], 'digest': row['digest']})
            break
    lang, template = request.language, request.template
    def label(value):
        return translated(template.labels[value], lang) if value in template.labels else value
    def amount(value):
        return word('missing', lang) if value is None else value
    pages = []
    def add(title, lines, links=None):
        # Explicit bounds prevent content disappearing off a page in either format.
        for line in lines:
            if len(line) > 420:
                raise ValueError('A report line exceeds 420 characters. Shorten template labels or plan identifiers.')
        pages.append({'title': title, 'lines': lines, 'links': links or {}})
    add(translated(template.title, lang), [translated(template.client, lang),
        f"{result['plan_id']} / v{result['plan_version']}",
        f"{result['period']['start']} — {result['period']['end']}",
        f"As of / كما في: {result['as_of']}",
        f"Actual revision / الإصدار الفعلي: {result['actual_revision']}",
        word('snapshot', lang), word('assurance', lang)])
    for key in warnings:
        add(word('summary', lang), [word(key, lang)])
    for rollup in result['rollups']:
        lines = [label(rollup['metric']) + ' (' + rollup['unit'] + ')',
            word('target', lang) + ': ' + amount(rollup['target']),
            word('actual', lang) + ': ' + amount(rollup['actual']),
            word('variance', lang) + ': ' + amount(rollup['variance']),
            word('status', lang) + ': ' + word(rollup['status'], lang),
            word('coverage', lang) + ': ' + str(rollup['measured_cells']) + ' / ' + str(rollup['planned_cells'])]
        if rollup['offset_detected']: lines.append(word('offset', lang))
        if rollup['unplanned_actuals']: lines.append(word('unplanned', lang) + str(len(rollup['unplanned_actuals'])))
        add(word('summary', lang), lines)
    evidence = []
    for c in result['cells']:
        refs = []
        for side, key in [('plan', 'plan_source'), ('actuals', 'actual_source')]:
            source = c[key]
            if source:
                number = len(evidence) + 1
                path = '/api/intent/dimensional/analyses/' + analysis_id + '/evidence?' + urlencode({'side': side, 'cell_id': c['cell_id']})
                evidence.append({'number': number, 'cell_id': c['cell_id'], 'side': side, 'source': source, 'path': path})
                refs.append('[' + str(number) + ']')
        add(word('cells', lang), [c['cell_id'] + ' · ' + label(c['metric']) + ' (' + c['unit'] + ')',
            ' · '.join(label(k) + ': ' + label(v) for k, v in sorted(c['dimensions'].items())),
            word('owner', lang) + ': ' + c['owner'],
            word('target', lang) + ': ' + amount(c['target']),
            word('actual', lang) + ': ' + amount(c['actual']),
            word('variance', lang) + ': ' + amount(c['variance']),
            word('status', lang) + ': ' + word(c['status'], lang), word('evidence', lang) + ': ' + ' '.join(refs)])
    for e in evidence:
        source = e['source']
        add(word('evidence', lang) + ' [' + str(e['number']) + ']',
            [e['cell_id'] + ' / ' + e['side'], source['path'], source['locator'], 'SHA-256: ' + source['sha256']],
            {'1': e['path']})
    binding = {'composer_version': 'board-pack.v2', 'analysis_hash': analysis_id, 'plan_digest': result['plan_import_digest'],
               'actual_digest': result['actual_import_digest'], 'template': template.model_dump(mode='json'),
               'language': lang, 'warnings': warnings, 'newer_records': newer_records}
    add('Snapshot references / مراجع اللقطة', [
        'Analysis: ' + analysis_id,
        'Plan SHA-256: ' + result['plan_import_digest'],
        'Actuals SHA-256: ' + result['actual_import_digest'],
        'Template SHA-256: ' + fingerprint(template.model_dump(mode='json')),
        'Pack SHA-256: ' + fingerprint(binding),
        'Composer: board-pack.v2', word('assurance', lang)])
    return {'schema_version': 1, 'pack_hash': fingerprint(binding), 'binding': binding,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'pages': pages, 'evidence': evidence,
            'untranslated_labels': sorted({v for c in result['cells'] for v in [c['metric'], *c['dimensions'].keys(), *c['dimensions'].values()] if v not in template.labels}) if lang != 'en' else []}


FONT_ROOT = Path(__file__).with_name('fonts')


def mark_ltr(text):
    return re.sub(r'[+-]?[A-Za-z0-9][A-Za-z0-9_.:/-]*', lambda m: '\u200e' + m.group() + '\u200e', text)


def visual(text):
    import arabic_reshaper
    from bidi.algorithm import get_display
    # Keep dates, signs and exact decimal strings in logical LTR order inside RTL prose.
    text = mark_ltr(text)
    return get_display(arabic_reshaper.reshape(text), base_dir='L').replace('\u200e', '')


def export_pdf(pack, public_url):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.colors import HexColor
    for name, file in [('BoardLatin', 'NotoSans-Regular.ttf'), ('BoardArabic', 'NotoSansArabic-Regular.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont(name, str(FONT_ROOT / file)))
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(960, 540))
    pdf.setTitle(pack['binding']['template']['title']['en'])
    def draw(text, x, y, size, width):
        # Arabic font covers Arabic and Latin; preserve numeric strings without conversion.
        text = visual(text)
        arabic = pdfmetrics.getFont('BoardArabic').face.charToGlyph
        runs = []
        for char in text:
            font = 'BoardArabic' if ord(char) in arabic and ord(char) > 255 else 'BoardLatin'
            if runs and runs[-1][0] == font: runs[-1][1] += char
            else: runs.append([font, char])
        def length(): return sum(pdfmetrics.stringWidth(value, font, size) for font, value in runs)
        while length() > width and size > 8: size -= .5
        if length() > width:
            raise ValueError('Report text is too long for export. Shorten the template or plan labels.')
        for font, value in runs:
            pdf.setFont(font, size)
            pdf.drawString(x, y, value)
            x += pdfmetrics.stringWidth(value, font, size)
    for i, page in enumerate(pack['pages']):
        pdf.setFillColor(HexColor('#FBF8F2')); pdf.rect(0, 0, 960, 540, fill=1, stroke=0)
        pdf.setFillColor(HexColor(pack['binding']['template']['accent']))
        draw(page['title'], 40, 478, 28, 880)
        pdf.setFillColor(HexColor('#192C35'))
        for n, line in enumerate(page['lines']):
            y = 426 - n * 43
            draw(line, 40, y, 17, 880)
            if str(n) in page['links'] and public_url:
                pdf.linkURL(public_url + page['links'][str(n)], (40, y-5, 920, y+22), relative=0)
        draw(f"Kyvern · {i+1}/{len(pack['pages'])} · {pack['binding']['analysis_hash']}", 40, 28, 8, 880)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def export_pptx(pack, public_url):
    # Runtime export lives in the Python API; editable text retains Unicode/RTL.
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_AUTO_SIZE
    from pptx.oxml.xmlchemy import OxmlElement
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    def text(slide, value, y, size, color, link=None):
        shape = slide.shapes.add_textbox(Inches(.55), Inches(y), Inches(12.2), Inches(.55))
        tf = shape.text_frame; tf.word_wrap = False; tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        p = tf.paragraphs[0]
        run = p.add_run(); run.text = mark_ltr(value)
        run.font.name = 'Noto Sans'
        run.font.size = Pt(size); run.font.color.rgb = RGBColor.from_string(color)
        if pack['binding']['language'] == 'ar': p._p.get_or_add_pPr().set('rtl', '1')
        if re.search(r'[\u0600-\u06ff]', value):
            cs = OxmlElement('a:cs'); cs.set('typeface', 'Noto Sans Arabic'); run._r.get_or_add_rPr().append(cs)
        if link and public_url: run.hyperlink.address = public_url + link
    for i, page in enumerate(pack['pages']):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = RGBColor.from_string('FBF8F2')
        text(slide, page['title'], .4, 28, pack['binding']['template']['accent'][1:])
        for n, line in enumerate(page['lines']):
            # Conservative sizing for bounded long bilingual references.
            size = min(17, max(8, 1000 / max(len(line), 1)))
            text(slide, line, 1.22 + n * .597, size, '192C35', page['links'].get(str(n)))
        text(slide, f"Kyvern · {i+1}/{len(pack['pages'])} · {pack['binding']['analysis_hash']}", 6.95, 8, '72533F')
        slide.notes_slide.notes_text_frame.text = store._encode({'pack_hash': pack['pack_hash'], 'binding': pack['binding'], 'checked_at': pack['checked_at']})
    output = BytesIO(); deck.save(output)
    return output.getvalue()

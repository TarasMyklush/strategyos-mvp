"""Shared, measured table pagination for browser, PDF and editable slides."""
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    root = Path(__file__).with_name('fonts')
    for name, file in [('BoardLatin', 'NotoSans-Regular.ttf'), ('BoardArabic', 'NotoSansArabic-Regular.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(root / file)))
    return pdfmetrics


@lru_cache(maxsize=32768)
def width(text, size):
    from .board_pack import visual
    metrics = fonts()
    arabic = metrics.getFont('BoardArabic').face.charToGlyph
    return sum(metrics.stringWidth(c, 'BoardArabic' if ord(c) > 255 and ord(c) in arabic else 'BoardLatin', size)
               for c in visual(text))


def wrap(text, available, size):
    """Wrap complete text without clipping, including long source tokens."""
    lines = []
    current = ''
    for paragraph in str(text).split('\n'):
        for token in paragraph.split():
            candidate = (current + ' ' + token).strip()
            if width(candidate, size) <= available:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ''
            for char in token:
                if current and width(current + char, size) > available:
                    lines.append(current)
                    current = ''
                current += char
        lines.append(current)
        current = ''
    return lines or ['']


def table_pages(title, headers, widths, rows, *, keys=None, links=None, size=11):
    if len(headers) != len(widths) or sum(widths) > 880:
        raise ValueError('Invalid board table columns.')
    header_lines = [wrap(value, w - 12, size) for value, w in zip(headers, widths)]
    header_height = max(map(len, header_lines)) * 15 + 12
    pages, current, current_keys, current_links, heights = [], [], [], [], []
    used = header_height

    def finish():
        if current:
            pages.append({'title': title, 'lines': [' | '.join(row) for row in current], 'links': {},
                          'table': {'headers': headers, 'widths': widths, 'rows': list(current),
                                    'keys': list(current_keys), 'links': list(current_links),
                                    'header_height': header_height, 'row_heights': list(heights), 'font_size': size}})

    for index, row in enumerate(rows):
        if len(row) != len(headers):
            raise ValueError('Invalid board table row.')
        height = max(len(wrap(value, w - 12, size)) for value, w in zip(row, widths)) * 15 + 12
        if height + header_height > 372:
            raise ValueError('A board table row is too large to read. Shorten the configured labels.')
        if current and used + height > 372:
            finish()
            current, current_keys, current_links, heights = [], [], [], []
            used = header_height
        current.append(row)
        current_keys.append(keys[index] if keys else str(index))
        current_links.append(links[index] if links else {})
        heights.append(height)
        used += height
    finish()
    return pages

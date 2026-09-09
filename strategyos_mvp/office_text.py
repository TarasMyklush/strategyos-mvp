"""Bounded, dependency-light text extraction for OOXML evidence files."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo


MAX_ARCHIVE_ENTRIES = 10_000
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024


def _safe_members(archive: ZipFile) -> list[ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("Office document exceeds the reviewed archive-entry capacity.")
    expanded = 0
    seen_names: set[str] = set()
    for member in members:
        name = PurePosixPath(member.filename)
        if name.is_absolute() or any(part in {"", ".", ".."} for part in name.parts):
            raise ValueError("Office document contains an unsafe archive path.")
        if member.file_size < 0 or member.compress_size < 0:
            raise ValueError("Office document contains invalid archive metadata.")
        if member.filename in seen_names:
            raise ValueError("Office document contains duplicate archive entries.")
        seen_names.add(member.filename)
        expanded += member.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise ValueError("Office document exceeds the reviewed expanded-size capacity.")
    return members


def _read_xml(archive: ZipFile, member: ZipInfo) -> ElementTree.Element:
    if member.file_size > MAX_XML_BYTES:
        raise ValueError("Office XML part exceeds the reviewed extraction capacity.")
    try:
        return ElementTree.fromstring(archive.read(member))
    except ElementTree.ParseError as exc:
        raise ValueError("Office document contains unreadable XML.") from exc


def _slide_number(name: str) -> int:
    match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
    return int(match.group(1)) if match else 0


def extract_office_text(path: Path) -> list[tuple[str, str]]:
    """Return stable text locators while rejecting unsafe or oversized OOXML."""

    suffix = path.suffix.lower()
    if suffix not in {".docx", ".pptx"}:
        raise ValueError("Only DOCX and PPTX files use Office text extraction.")
    try:
        with ZipFile(path) as archive:
            members = _safe_members(archive)
            by_name = {member.filename: member for member in members}
            if suffix == ".docx":
                member = by_name.get("word/document.xml")
                if member is None:
                    raise ValueError("Word document is missing word/document.xml.")
                root = _read_xml(archive, member)
                namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                records: list[tuple[str, str]] = []
                paragraph_number = 0
                for paragraph in root.iter(namespace + "p"):
                    paragraph_number += 1
                    text = "".join(node.text or "" for node in paragraph.iter(namespace + "t")).strip()
                    if text:
                        records.append((f"Document paragraph {paragraph_number}", text))
                return records

            slide_members = sorted(
                (
                    member
                    for member in members
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", member.filename)
                ),
                key=lambda member: _slide_number(member.filename),
            )
            if not slide_members:
                raise ValueError("Presentation is missing slide XML parts.")
            namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
            records = []
            for member in slide_members:
                root = _read_xml(archive, member)
                text = " ".join(
                    value.strip()
                    for value in (node.text or "" for node in root.iter(namespace + "t"))
                    if value.strip()
                )
                if text:
                    records.append((f"Presentation slide {_slide_number(member.filename)}", text))
            return records
    except BadZipFile as exc:
        raise ValueError("Office document is not a readable OOXML archive.") from exc

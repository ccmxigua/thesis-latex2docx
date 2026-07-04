#!/usr/bin/env python3
"""Extract structured data from a DOCX file for red-team comparison.

Usage:
    python3 extract_docx.py <input.docx> --out <output_dir>
    python3 extract_docx.py <input.docx>              # prints JSON to stdout

Output files in <output_dir>:
    styles.json     - all styles with font, size, spacing, indent
    document.json   - paragraph list with text and style
    numbering.json  - numbering definitions
    page.json       - page dimensions and margins
"""

import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# ── XML namespaces ──────────────────────────────────────────────────────
NS = {
    "w":  "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r":  "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "w14":"http://schemas.microsoft.com/office/word/2010/wordml",
    "w15":"http://schemas.microsoft.com/office/word/2012/wordml",
}

# ── Helpers ─────────────────────────────────────────────────────────────

def _tag(t):
    """Expand short tag name to fully qualified."""
    if ":" in t:
        return "{%s}%s" % (NS[t.split(":")[0]], t.split(":")[1])
    return t

def _el_text(el, child_tag, default=None):
    c = el.find(_tag(child_tag)) if el is not None else None
    if c is None:
        return default
    return (c.text or "").strip() or default

def _el_val(el, child_tag, default=None):
    c = el.find(_tag(child_tag)) if el is not None else None
    return (c.get(_tag("w:val")) if c is not None else None) or default

def _parse_spacing(style_el):
    """Extract spacing info from <w:pPr> or <w:rPr> parent."""
    spacing = {}
    sp = style_el.find(_tag("w:spacing")) if style_el is not None else None
    if sp is not None:
        for attr in ["before", "after", "line", "lineRule"]:
            val = sp.get(_tag("w:" + attr))
            if val is not None:
                spacing[attr] = int(val) if val.lstrip("-").isdigit() else val
    return spacing

def _parse_ind(style_el):
    """Extract paragraph indentation."""
    ind = {}
    ind_el = style_el.find(_tag("w:ind")) if style_el is not None else None
    if ind_el is not None:
        for attr in ["left", "right", "firstLine", "hanging"]:
            val = ind_el.get(_tag("w:" + attr))
            if val is not None:
                ind[attr] = int(val) if val.lstrip("-").isdigit() else val
    return ind

def _parse_justify(style_el):
    """Extract justification."""
    jc = style_el.find(_tag("w:jc"))
    return _el_val(jc, "w:val") if jc is not None else None

def _parse_fonts(rpr_el):
    """Extract font info from <w:rPr>."""
    fonts = {}
    rFonts = rpr_el.find(_tag("w:rFonts")) if rpr_el is not None else None
    if rFonts is not None:
        for attr in ["ascii", "hAnsi", "eastAsia", "cs"]:
            v = rFonts.get(_tag("w:" + attr))
            if v:
                fonts[attr] = v
    return fonts

def _parse_sz(rpr_el):
    """Extract font size in half-points."""
    sz = rpr_el.find(_tag("w:sz"))
    if sz is not None:
        return int(sz.get(_tag("w:val"), 0))
    return None

def _parse_bold(rpr_el):
    b = rpr_el.find(_tag("w:b"))
    return b is not None and b.get(_tag("w:val"), "1") != "0"

def _parse_italic(rpr_el):
    i = rpr_el.find(_tag("w:i"))
    return i is not None and i.get(_tag("w:val"), "1") != "0"


# ── Extract styles.xml ──────────────────────────────────────────────────

def extract_styles(style_xml):
    """Return dict of style_id -> {name, type, fonts, size, bold, italic, spacing, indent, jc, basedOn}."""
    styles = {}
    root = ET.fromstring(style_xml)
    for st in root.findall(_tag("w:style")):
        sid = st.get(_tag("w:styleId"))
        if not sid:
            continue
        name = _el_val(st, "w:name")
        based = _el_val(st, "w:basedOn")

        ppr = st.find(_tag("w:pPr"))
        rpr = st.find(_tag("w:rPr"))

        styles[sid] = {
            "name": name,
            "type": st.get(_tag("w:type"), ""),
            "basedOn": based,
            "fonts": _parse_fonts(rpr) if rpr is not None else {},
            "size_halfpt": _parse_sz(rpr) if rpr is not None else None,
            "bold": _parse_bold(rpr) if rpr is not None else False,
            "italic": _parse_italic(rpr) if rpr is not None else False,
            "spacing": _parse_spacing(ppr) if ppr is not None else {},
            "indent": _parse_ind(ppr) if ppr is not None else {},
            "justify": _parse_justify(ppr) if ppr is not None else None,
        }

        # Also grab default paragraph properties
        dp = st.find(_tag("w:rPrDefault"))
        if dp is not None and rpr is None:
            rpr_d = dp.find(_tag("w:rPr"))
            if rpr_d is not None:
                styles[sid]["fonts"] = _parse_fonts(rpr_d)
                styles[sid]["size_halfpt"] = _parse_sz(rpr_d)

    return styles


# ── Extract document.xml ────────────────────────────────────────────────

def extract_paragraphs(doc_xml, max_text=120):
    """Return list of {text, style, bold, italic, size_halfpt, fonts, spacing, indent}."""
    paragraphs = []
    root = ET.fromstring(doc_xml)
    body = root.find(_tag("w:body"))
    if body is None:
        return paragraphs

    for p in body.findall(_tag("w:p")):
        ppr = p.find(_tag("w:pPr"))
        pstyle = _el_val(ppr, "w:pStyle") if ppr is not None else None
        p_spacing = _parse_spacing(ppr) if ppr is not None else {}
        p_indent = _parse_ind(ppr) if ppr is not None else {}
        p_jc = _parse_justify(ppr) if ppr is not None else None

        # Collect run-level props (only first run for style info)
        first_rpr = None
        run_texts = []
        first_run_fonts = {}
        first_run_sz = None
        first_run_bold = False
        first_run_italic = False

        runs = p.findall(_tag("w:r"))
        for i, r in enumerate(runs):
            rpr = r.find(_tag("w:rPr"))
            if i == 0 and rpr is not None:
                first_rpr = rpr
                first_run_fonts = _parse_fonts(rpr)
                first_run_sz = _parse_sz(rpr)
                first_run_bold = _parse_bold(rpr)
                first_run_italic = _parse_italic(rpr)

            t_els = r.findall(_tag("w:t"))
            for t in t_els:
                if t.text:
                    run_texts.append(t.text)

        text = "".join(run_texts).strip()
        if not text:
            # Check for images
            for r in runs:
                drawings = r.findall(_tag("w:drawing"))
                if drawings:
                    text = "[IMAGE]"
                    break

        paragraphs.append({
            "text": text[:max_text],
            "full_length": len(text),
            "style": pstyle,
            "fonts": first_run_fonts,
            "size_halfpt": first_run_sz,
            "bold": first_run_bold,
            "italic": first_run_italic,
            "spacing": p_spacing,
            "indent": p_indent,
            "justify": p_jc,
        })

    return paragraphs


# ── Extract numbering.xml ───────────────────────────────────────────────

def extract_numbering(num_xml):
    """Return dict of numId -> {abstractNumVal, level_count, level_formats}."""
    numbering = {}
    if not num_xml:
        return numbering
    root = ET.fromstring(num_xml)
    for num in root.findall(_tag("w:num")):
        num_id = num.get(_tag("w:numId"))
        abstract_id = _el_val(num.find(_tag("w:abstractNumId")), "w:val")
        numbering[num_id] = {"abstractNumId": abstract_id, "levels": {}}

    for anum in root.findall(_tag("w:abstractNum")):
        aid = anum.get(_tag("w:abstractNumId"))
        for lvl in anum.findall(_tag("w:lvl")):
            ilvl = lvl.get(_tag("w:ilvl"))
            numFmt = _el_val(lvl, "w:numFmt")
            lvlText = _el_val(lvl, "w:lvlText")
            start = _el_val(lvl, "w:start")
            # Find the num using this abstractNum
            for nid, ndata in numbering.items():
                if ndata["abstractNumId"] == aid:
                    numbering[nid]["levels"][ilvl] = {
                        "format": numFmt,
                        "text": lvlText,
                        "start": start,
                    }

    return numbering


# ── Extract page settings ───────────────────────────────────────────────

def extract_page_settings(doc_xml):
    """Return page dimensions and margins from the first sectPr."""
    root = ET.fromstring(doc_xml)
    body = root.find(_tag("w:body"))
    if body is None:
        return {}
    sect = body.find(_tag("w:sectPr"))
    if sect is None:
        return {}

    pgSz = sect.find(_tag("w:pgSz"))
    pgMar = sect.find(_tag("w:pgMar"))

    page = {}
    if pgSz is not None:
        page["width"] = int(pgSz.get(_tag("w:w"), 0))
        page["height"] = int(pgSz.get(_tag("w:h"), 0))
        orient = pgSz.get(_tag("w:orient"))
        if orient:
            page["orient"] = orient

    if pgMar is not None:
        page["margins"] = {}
        for key in ("top", "bottom", "left", "right", "header", "footer"):
            v = pgMar.get(_tag("w:" + key))
            if v is not None:
                page["margins"][key] = int(v)

    return page


# ── Main ────────────────────────────────────────────────────────────────

def extract_docx(docx_path):
    """Extract all structured data from a DOCX file."""
    data = {"styles": {}, "paragraphs": [], "numbering": {}, "page": {}}

    with zipfile.ZipFile(docx_path, "r") as z:
        # styles.xml
        if "word/styles.xml" in z.namelist():
            data["styles"] = extract_styles(z.read("word/styles.xml"))

        # document.xml
        if "word/document.xml" in z.namelist():
            doc_xml = z.read("word/document.xml")
            data["paragraphs"] = extract_paragraphs(doc_xml)
            data["page"] = extract_page_settings(doc_xml)

        # numbering.xml
        if "word/numbering.xml" in z.namelist():
            data["numbering"] = extract_numbering(z.read("word/numbering.xml"))

    return data


def main(argv):
    if len(argv) < 1:
        print("usage: extract_docx.py <input.docx> [--out <output_dir>]", file=sys.stderr)
        return 2

    docx_path = argv[0]
    out_dir = None

    i = 1
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out_dir = argv[i + 1]
            i += 2
        else:
            i += 1

    data = extract_docx(docx_path)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for key, val in data.items():
            out_path = os.path.join(out_dir, f"{key}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(val, f, ensure_ascii=False, indent=2)
            print(f"  wrote {out_path} ({len(json.dumps(val, ensure_ascii=False))} bytes)")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

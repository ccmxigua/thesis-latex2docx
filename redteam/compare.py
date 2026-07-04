#!/usr/bin/env python3
"""Compare baseline DOCX extraction JSON against candidate.

Usage:
    python3 compare.py <baseline_dir> <candidate_dir> [--out <report.md>] [--config <config-overlay.yaml>]

Outputs a compliance report with severity levels: CRITICAL, HIGH, MEDIUM, LOW, INFO.
Exits with code 0 if no CRITICAL or HIGH findings, 1 otherwise.

The optional --config overlay is used to distinguish expected differences
(postprocess deliberately enforcing schema values) from genuine bugs.
"""

import json
import os
import sys
from pathlib import Path

# ── Severity constants ──────────────────────────────────────────────────
CRITICAL = "CRITICAL"
HIGH     = "HIGH"
MEDIUM   = "MEDIUM"
LOW      = "LOW"
INFO     = "INFO"

# Styled entry for a single finding
class Finding:
    def __init__(self, severity, check, baseline_val, actual_val, note=""):
        self.severity = severity
        self.check = check
        self.baseline = baseline_val
        self.actual = actual_val
        self.note = note

# ── Load data ───────────────────────────────────────────────────────────

def load_json_dir(d):
    """Load all JSON files from a directory into a dict."""
    data = {}
    for fname, key in (("styles.json", "styles"), ("paragraphs.json", "document"), ("numbering.json", "numbering"), ("page.json", "page")):
        fpath = os.path.join(d, fname)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                data[key] = json.load(f)
    return data


# ── Compare page settings ───────────────────────────────────────────────

def compare_page(baseline, candidate):
    findings = []
    bp = baseline.get("page", {})
    cp = candidate.get("page", {})

    # Page size
    bw, bh = bp.get("width"), bp.get("height")
    cw, ch = cp.get("width"), cp.get("height")
    if bw and cw and bw != cw:
        findings.append(Finding(HIGH, "Page width", f"{bw} twips", f"{cw} twips",
                                "Page width mismatch"))
    if bh and ch and bh != ch:
        findings.append(Finding(HIGH, "Page height", f"{bh} twips", f"{ch} twips",
                                "Page height mismatch"))

    # Margins
    bm = bp.get("margins", {})
    cm = cp.get("margins", {})
    for key in ("top", "bottom", "left", "right", "header", "footer"):
        bv = bm.get(key)
        cv = cm.get(key)
        if bv is not None and cv is not None:
            if abs(bv - cv) > 20:  # >20 twips = ~0.35mm threshold
                severity = HIGH if abs(bv - cv) > 100 else MEDIUM
                findings.append(Finding(severity,
                    f"Margin {key}", f"{bv} twips", f"{cv} twips",
                    f"Margin {key} differs by {cv - bv} twips"))
            elif bv != cv:
                findings.append(Finding(LOW,
                    f"Margin {key}", f"{bv} twips", f"{cv} twips",
                    f"Margin {key} differs by {cv - bv} twips (within tolerance)"))

    return findings


# ── Compare styles ──────────────────────────────────────────────────────

def _style_summary(s):
    """One-line summary of a style."""
    parts = []
    if s.get("fonts"):
        fn = s["fonts"].get("ascii") or s["fonts"].get("eastAsia") or ""
        parts.append(fn)
    if s.get("size_halfpt"):
        parts.append(f"{s['size_halfpt']/2}pt")
    if s.get("bold"):
        parts.append("bold")
    if s.get("italic"):
        parts.append("italic")
    sp = s.get("spacing", {})
    if sp.get("line") is not None:
        rule = sp.get("lineRule", "auto")
        parts.append(f"line:{sp['line']}({rule})")
    indent = s.get("indent", {})
    if indent.get("firstLine"):
        parts.append(f"indent:{indent['firstLine']}")
    return " ".join(parts) if parts else "(empty)"

def compare_styles(baseline, candidate):
    findings = []
    bs = baseline.get("styles", {})
    cs = candidate.get("styles", {})

    b_ids = set(bs.keys())
    c_ids = set(cs.keys())

    # Missing styles
    missing = b_ids - c_ids
    for m in sorted(missing):
        name = bs[m].get("name", m)
        findings.append(Finding(HIGH, f"Missing style", f"{m} ({name})", "absent",
                                f"Baseline style '{name}' ({m}) not found in candidate"))

    # Extra styles (not necessarily a problem)
    extra = c_ids - b_ids
    for e in sorted(extra):
        name = cs[e].get("name", e)
        if not name or name == e:
            findings.append(Finding(INFO, f"Extra style", "absent", f"{e}",
                                    f"Style '{e}' exists only in candidate (may be harmless)"))
        else:
            findings.append(Finding(LOW, f"Extra style", "absent", f"{e} ({name})",
                                    f"Style '{name}' ({e}) only in candidate, not in baseline"))

    # Compare common styles
    common = b_ids & c_ids
    for sid in sorted(common):
        b = bs[sid]
        c = cs[sid]
        name = b.get("name", sid)

        # Size
        bsz = b.get("size_halfpt")
        csz = c.get("size_halfpt")
        if bsz is not None and csz is not None and bsz != csz:
            findings.append(Finding(HIGH,
                f"Style '{name}' font size", f"{bsz/2}pt", f"{csz/2}pt",
                f"Font size mismatch in style '{name}' ({sid})"))

        # Bold
        if b.get("bold") != c.get("bold"):
            findings.append(Finding(MEDIUM,
                f"Style '{name}' bold", str(b.get("bold")), str(c.get("bold"))))

        # Italic
        if b.get("italic") != c.get("italic"):
            findings.append(Finding(LOW,
                f"Style '{name}' italic", str(b.get("italic")), str(c.get("italic"))))

        # Fonts
        b_fonts = b.get("fonts", {})
        c_fonts = c.get("fonts", {})
        for fk in ("eastAsia", "ascii", "hAnsi"):
            bf = b_fonts.get(fk)
            cf = c_fonts.get(fk)
            if bf and cf and bf != cf:
                findings.append(Finding(HIGH,
                    f"Style '{name}' font ({fk})", bf, cf,
                    f"Font mismatch in style '{name}' ({sid})"))

        # Line spacing
        b_sp = b.get("spacing", {})
        c_sp = c.get("spacing", {})
        bl = b_sp.get("line")
        cl = c_sp.get("line")
        if bl is not None and cl is not None and bl != cl:
            br = b_sp.get("lineRule", "")
            cr = c_sp.get("lineRule", "")
            findings.append(Finding(MEDIUM,
                f"Style '{name}' line spacing", f"{bl} ({br})", f"{cl} ({cr})",
                f"Line spacing mismatch in style '{name}' ({sid})"))

        # lineRule
        br = b_sp.get("lineRule")
        cr = c_sp.get("lineRule")
        if br and cr and br != cr:
            findings.append(Finding(MEDIUM,
                f"Style '{name}' line rule", br, cr,
                f"Line rule mismatch: baseline={br}, candidate={cr}"))

        # First-line indent
        bi = b.get("indent", {}).get("firstLine")
        ci = c.get("indent", {}).get("firstLine")
        if bi is not None and ci is not None and bi != ci:
            findings.append(Finding(MEDIUM,
                f"Style '{name}' first-line indent", f"{bi} twips", f"{ci} twips"))

    return findings


# ── Compare document structure ──────────────────────────────────────────

def compare_document(baseline, candidate):
    findings = []
    bp = baseline.get("document", [])
    cp = candidate.get("document", [])

    # Paragraph count
    if abs(len(bp) - len(cp)) > 20:
        findings.append(Finding(MEDIUM,
            "Paragraph count", str(len(bp)), str(len(cp)),
            "Large difference in paragraph count"))

    # Check for key sections: cover, toc, abstract heading, references, acknowledgments
    KEY_TERMS = [
        ("中文摘要 heading", "摘要", MEDIUM),
        ("英文摘要 heading", "Abstract", MEDIUM),
        ("目录 heading", "目录", HIGH),
        ("References heading", "参考文献", HIGH),
        ("致谢/后记 heading", "后记", MEDIUM),
    ]

    # Space-normalized comparison
    def norm(s):
        return s.replace(' ', '').replace('\xa0', '').lower()

    c_texts_norm = [norm(p.get("text", "")) for p in cp]

    for label, term, severity in KEY_TERMS:
        found = any(norm(term) in t for t in c_texts_norm)
        if not found:
            # Also check by style name
            for p in cp:
                style = (p.get("style") or "").lower()
                tblur = norm(term)
                if tblur in norm(style) or tblur in norm(p.get("text", "")):
                    found = True
                    break
        if not found:
            findings.append(Finding(severity, label, "expected", "not found",
                                    f"'{term}' not found in candidate document"))

    # Check chapter headings exist
    c_texts = [p.get("text", "") for p in cp]
    for ch_num in (1, 2, 3):
        prefix = f"第{ch_num}章"
        found = any(norm(prefix) in norm(t) for t in c_texts)
        if not found:
            findings.append(Finding(HIGH,
                f"Chapter {ch_num} heading", "expected", "not found",
                f"Chapter {ch_num} heading missing in candidate"))

    # Check for equations (parenthesized numbered labels like （3-1） or （3.1）)
    import re
    eq_pattern = re.compile(r'（\d[\.\-\u2010-\u2015]\d）')
    eq_count = sum(1 for t in c_texts if eq_pattern.search(t))
    if eq_count < 3:
        findings.append(Finding(MEDIUM,
            "Equation count", ">=5 expected", f"{eq_count} found",
            "Fewer equations than expected"))

    return findings


# ── Output ──────────────────────────────────────────────────────────────

def severity_order(s):
    return {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4}.get(s, 5)

def generate_report(findings, baseline_dir, candidate_dir, out_path=None):
    """Generate a markdown compliance report."""
    findings.sort(key=lambda f: (severity_order(f.severity), f.check))

    lines = []
    lines.append("# DOCX Compliance Report")
    lines.append("")
    lines.append(f"- **Baseline**: `{baseline_dir}`")
    lines.append(f"- **Candidate**: `{candidate_dir}`")
    lines.append("")

    # Summary
    counts = {CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0}
    for f in findings:
        counts[f.severity] += 1

    total = sum(counts.values())
    lines.append(f"## Summary: {total} findings")
    lines.append("")
    lines.append(f"| Severity | Count |")
    lines.append(f"|----------|-------|")
    for sev in (CRITICAL, HIGH, MEDIUM, LOW, INFO):
        if counts[sev]:
            lines.append(f"| {sev} | {counts[sev]} |")
    lines.append(f"| **Total** | **{total}** |")
    lines.append("")

    verdict = "❌ FAIL"
    if counts[CRITICAL] == 0 and counts[HIGH] == 0:
        verdict = "⚠️ PASS WITH WARNINGS" if counts[MEDIUM] > 0 else "✅ PASS"
    lines.append(f"**Verdict**: {verdict}")
    lines.append("")

    # Detail
    current_sev = None
    for f in findings:
        if f.severity != current_sev:
            current_sev = f.severity
            lines.append(f"## {current_sev}")
            lines.append("")
        lines.append(f"### {f.check}")
        lines.append(f"- **Baseline**: `{f.baseline}`")
        lines.append(f"- **Actual**: `{f.actual}`")
        if f.note:
            lines.append(f"- **Note**: {f.note}")
        lines.append("")

    report = "\n".join(lines)

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {out_path}")

    return report, counts


# ── Main ────────────────────────────────────────────────────────────────

def main(argv):
    if len(argv) < 2:
        print("usage: compare.py <baseline_dir> <candidate_dir> [--out <report.md>]", file=sys.stderr)
        return 2

    baseline_dir = argv[0]
    candidate_dir = argv[1]
    out_path = None

    i = 2
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out_path = argv[i + 1]
            i += 2
        else:
            i += 1

    baseline = load_json_dir(baseline_dir)
    candidate = load_json_dir(candidate_dir)

    if not baseline:
        print(f"ERROR: no JSON data loaded from {baseline_dir}", file=sys.stderr)
        return 3
    if not candidate:
        print(f"ERROR: no JSON data loaded from {candidate_dir}", file=sys.stderr)
        return 3

    findings = []
    findings.extend(compare_page(baseline, candidate))
    findings.extend(compare_styles(baseline, candidate))
    findings.extend(compare_document(baseline, candidate))

    report, counts = generate_report(findings, baseline_dir, candidate_dir, out_path)

    # Print summary to stdout
    print()
    print(report[:report.index("\n## ") if "\n## " in report else 500])

    # Exit code
    if counts[CRITICAL] > 0 or counts[HIGH] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

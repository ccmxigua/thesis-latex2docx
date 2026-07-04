#!/bin/bash
# validate.sh — Red-team compliance validation for thesis-latex2docx
# Usage: ./validate.sh config-<school>-overlay.yaml
#
# Runs the full pipeline on the fixed sample thesis,
# then compares the output DOCX against the reference baseline.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REDTEAM_DIR="$SCRIPT_DIR/redteam"
TESTS_DIR="$SCRIPT_DIR/tests"
BASELINE_DIR="$REDTEAM_DIR/baseline"
CANDIDATE_DIR="$REDTEAM_DIR/candidate"
REPORT_PATH="$REDTEAM_DIR/report.md"

# ── Args ────────────────────────────────────────────────────────────────
OVERLAY="${1:-}"
if [ -z "$OVERLAY" ]; then
  echo "usage: ./validate.sh <config-overlay.yaml>"
  exit 2
fi

if [ ! -f "$OVERLAY" ]; then
  echo "ERROR: overlay not found: $OVERLAY"
  exit 2
fi

SAMPLE_TEX="$TESTS_DIR/sample-thesis.tex"
if [ ! -f "$SAMPLE_TEX" ]; then
  echo "ERROR: sample thesis not found: $SAMPLE_TEX"
  exit 2
fi

REF_DOCX="$SCRIPT_DIR/reference.docx"
if [ ! -f "$REF_DOCX" ]; then
  echo "ERROR: reference.docx not found: $REF_DOCX"
  exit 2
fi

echo "============================================"
echo " thesis-latex2docx Red-Team Validation"
echo "============================================"
echo ""

# ── Step 0: Ensure baseline exists ──────────────────────────────────────
if [ ! -f "$BASELINE_DIR/styles.json" ]; then
  echo "[0/3] Extracting baseline from reference.docx..."
  mkdir -p "$BASELINE_DIR"
  python3 "$REDTEAM_DIR/extract_docx.py" "$REF_DOCX" --out "$BASELINE_DIR"
  echo "  baseline ready"
else
  echo "[0/3] Baseline exists, using cached."
fi
echo ""

# ── Step 1: Generate DOCX from sample thesis ────────────────────────────
echo "[1/3] Running convert.sh on sample-thesis.tex..."
TMP_DOCX="$(mktemp /tmp/v2-validate-XXXXXXXXXX)".docx

"$SCRIPT_DIR/convert.sh" "$SAMPLE_TEX" "$TMP_DOCX" "$OVERLAY"
echo "  generated: $TMP_DOCX ($(wc -c < "$TMP_DOCX" | tr -d ' ') bytes)"
echo ""

# ── Step 2: Extract candidate ───────────────────────────────────────────
echo "[2/3] Extracting candidate DOCX..."
rm -rf "$CANDIDATE_DIR"
mkdir -p "$CANDIDATE_DIR"
python3 "$REDTEAM_DIR/extract_docx.py" "$TMP_DOCX" --out "$CANDIDATE_DIR"
echo ""

# ── Step 3: Compare ─────────────────────────────────────────────────────
echo "[3/3] Comparing baseline vs candidate..."
python3 "$REDTEAM_DIR/compare.py" "$BASELINE_DIR" "$CANDIDATE_DIR" --out "$REPORT_PATH"
EXIT_CODE=$?
echo ""

# ── Cleanup ─────────────────────────────────────────────────────────────
rm -f "$TMP_DOCX"

# ── Result ──────────────────────────────────────────────────────────────
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Validation PASSED — no CRITICAL or HIGH findings."
else
  echo "❌ Validation FAILED — CRITICAL or HIGH findings detected."
  echo "   See report: $REPORT_PATH"
fi

exit $EXIT_CODE

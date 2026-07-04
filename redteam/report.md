# DOCX Compliance Report

- **Baseline**: `/Users/cheng/clawd/deliverables/thesis-latex2docx/redteam/baseline`
- **Candidate**: `/Users/cheng/clawd/deliverables/thesis-latex2docx/redteam/candidate`

## Summary: 6 findings

| Severity | Count |
|----------|-------|
| MEDIUM | 6 |
| **Total** | **6** |

**Verdict**: ⚠️ PASS WITH WARNINGS

## MEDIUM

### Paragraph count
- **Baseline**: `2`
- **Actual**: `134`
- **Note**: Large difference in paragraph count

### Style 'Title Page Degree' bold
- **Baseline**: `True`
- **Actual**: `False`

### Style 'Title Page Meta' bold
- **Baseline**: `True`
- **Actual**: `False`

### 中文摘要 heading
- **Baseline**: `expected`
- **Actual**: `not found`
- **Note**: '摘要' not found in candidate document

### 致谢/后记 heading
- **Baseline**: `expected`
- **Actual**: `not found`
- **Note**: '后记' not found in candidate document

### 英文摘要 heading
- **Baseline**: `expected`
- **Actual**: `not found`
- **Note**: 'Abstract' not found in candidate document

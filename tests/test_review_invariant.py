from __future__ import annotations

from pathlib import Path

from quality_gates.models import Finding
from quality_gates.review.invariant import (
    check_cross_file_invariants,
    extract_signatures_from_text,
    invariant_violations_to_findings,
    validate_grounded_citations,
)


def test_extract_signatures() -> None:
    py_code = """
def calculate_tax(amount: float, rate: float) -> float:
    return amount * rate

class InvoiceService:
    def process(self):
        pass
"""
    sigs = extract_signatures_from_text("service.py", py_code)
    assert "calculate_tax" in sigs
    assert sigs["calculate_tax"].params == ["amount", "rate"]
    assert "InvoiceService" in sigs


def test_cross_file_invariant_detection(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True)

    provider = src / "calc.py"
    provider.write_text(
        "def compute_total(base_price, tax_rate):\n    return base_price * (1 + tax_rate)\n",
        encoding="utf-8",
    )

    consumer = src / "checkout.py"
    consumer.write_text(
        "from src.calc import compute_total\n\ndef run():\n    return compute_total(100)\n",
        encoding="utf-8",
    )

    diff = """
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,2 +1,2 @@
-def compute_total(base_price):
+def compute_total(base_price, tax_rate):
     return base_price * (1 + tax_rate)
"""

    violations = check_cross_file_invariants(
        tmp_path,
        changed_files=["src/calc.py"],
        diff_text=diff,
    )

    assert len(violations) == 1
    v = violations[0]
    assert v.symbol_name == "compute_total"
    assert v.consumer_file == "src/checkout.py"
    assert "requires 2 params" in v.reason

    findings = invariant_violations_to_findings(violations)
    assert len(findings) == 1
    assert findings[0].rule == "cross-file/unupdated-consumer"


def test_grounded_citations_filtering(tmp_path: Path) -> None:
    (tmp_path / "valid.py").write_text("def real_func(): pass\n", encoding="utf-8")

    valid_finding = Finding(
        gate="review",
        path="valid.py",
        line=1,
        message="Valid issue",
    )
    hallucinated_finding = Finding(
        gate="review",
        path="nonexistent/ghost_file.py",
        line=10,
        message="Fake issue hallucinated by model",
    )

    grounded, ungrounded = validate_grounded_citations(
        [valid_finding, hallucinated_finding],
        root=tmp_path,
    )

    assert len(grounded) == 1
    assert grounded[0].path == "valid.py"
    assert len(ungrounded) == 1
    assert ungrounded[0].path == "nonexistent/ghost_file.py"

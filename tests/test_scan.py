from __future__ import annotations

from pathlib import Path

from quality_gates.review.ast_prune import (
    prune_generic_code,
    prune_python_ast,
    token_reduction_stats,
)
from quality_gates.scan import run_scan


def test_ast_python_pruning() -> None:
    code = """
import os

def touched_function(x: int) -> int:
    # This function is touched in the diff
    val = x * 2
    return val + 1

def untouched_large_function(a, b, c):
    '''Untouched docstring preserved.'''
    part1 = a + b
    part2 = b + c
    part3 = part1 * part2
    return part3

class Worker:
    def touched_method(self):
        return True

    def untouched_method(self, data):
        for item in data:
            if item.valid:
                item.process()
        return None
"""

    # We retain lines inside touched_function (lines 4-7) and touched_method (lines 17-18)
    pruned = prune_python_ast(code, retain_lines={5, 18})

    assert "def touched_function(x: int) -> int:" in pruned
    assert "val = x * 2" in pruned
    assert "def untouched_large_function(a, b, c):" in pruned
    assert "Untouched docstring preserved." in pruned
    # Internal body of untouched_large_function should be replaced with ellipsis
    assert "part1 = a + b" not in pruned
    assert "..." in pruned

    assert "def touched_method(self):" in pruned
    assert "return True" in pruned
    assert "def untouched_method(self, data):" in pruned
    assert "item.process()" not in pruned

    stats = token_reduction_stats(code, pruned)
    assert stats["token_ratio"] < 0.70
    assert stats["token_savings_pct"] > 30.0


def test_ast_generic_code_pruning() -> None:
    js_code = """
function touchedHandler(req, res) {
    const user = req.user;
    res.json({ ok: true, user });
}

function untouchedHeavyUtility(data, config) {
    const intermediate = data.map(x => x * 2);
    const filtered = intermediate.filter(x => x > 10);
    return filtered.reduce((a, b) => a + b, 0);
}
"""
    pruned = prune_generic_code(js_code, retain_lines={3})
    assert "function touchedHandler(req, res)" in pruned
    assert "res.json({ ok: true, user });" in pruned
    assert "function untouchedHeavyUtility(data, config)" in pruned
    assert "intermediate.filter" not in pruned
    assert "pruned: signature preserved" in pruned


def test_scan_targets_and_duplicate_detection(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True)

    file_a = src / "module.py"
    file_a.write_text(
        "def helper():\n    return 1\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )

    result = run_scan(root=tmp_path, targets=["src/module.py"])
    assert result.scanned_files_count == 1
    dup_findings = [f for f in result.findings if f.rule == "scan/duplicate-function"]
    assert len(dup_findings) == 1
    assert "Duplicate function definition 'helper'" in dup_findings[0].message

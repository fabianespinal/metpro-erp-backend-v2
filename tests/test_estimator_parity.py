"""Parity of the estimator core against the workbook (LibreOffice recalculation 2026-10-22,
workbook md5 b2f8d5b68f52bd6b9542f63406b6fef1). Fixture: tests/fixtures/estimator_golden.json.
Tolerance: abs 1e-6 on quantities, rel 1e-9 on totals."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from estimator import EstimatorInputError, ProfileChoice, calculate  # noqa: E402
from estimator.catalog import LINES  # noqa: E402
from estimator.inputs import EstimateInputs, default_inputs  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "estimator_golden.json")) as fh:
    GOLDEN = json.load(fh)
CASES = sorted(GOLDEN)


def _inputs(case):
    i = GOLDEN[case]["inputs"]
    return EstimateInputs(
        ancho=i["E9"], largo=i["E11"], altura_laterales=i["E13"],
        altura_techado_lateral=i["E15"], distancia_ejes=i["E17"], columnas_frontales=i["E38"],
        perfil_columnas=ProfileChoice("c", i["F41"]), perfil_frontales=ProfileChoice("f", i["F45"]),
        perfil_tijerillas=ProfileChoice("t", i["F50"]), perfil_frenado=ProfileChoice("b", i["F54"]),
    )


@pytest.mark.parametrize("case", CASES)
def test_calc_cells(case):
    r = calculate(_inputs(case))
    for cell, expected in GOLDEN[case]["calc"].items():
        assert r.quantities[cell] == pytest.approx(expected, abs=1e-6), cell


@pytest.mark.parametrize("case", CASES)
def test_line_quantities_and_totals(case):
    r = calculate(_inputs(case))
    cells = GOLDEN[case]["cells"]
    for ln in r.lines:
        if ln.quantity is not None:
            assert ln.quantity == pytest.approx(cells[f"C{ln.row}"], abs=1e-6), ln.row
        assert ln.total == pytest.approx(cells[f"F{ln.row}"], rel=1e-9), ln.row


@pytest.mark.parametrize("case", CASES)
def test_subtotal_and_indirect_block(case):
    r = calculate(_inputs(case))
    cells = GOLDEN[case]["cells"]
    assert r.subtotal == pytest.approx(cells["F122"], rel=1e-9)
    for k, v in r.workbook_indirects.items():
        assert v == pytest.approx(cells[k], rel=1e-9), k
    assert r.workbook_indirects["C131"] == pytest.approx(r.subtotal + 1)  # range quirk


def test_thirty_lines_and_ppa_line():
    r = calculate(default_inputs())
    assert len(r.lines) == len(LINES) == 30
    ppa = [ln for ln in r.lines if ln.row == 120][0]
    assert ppa.quantity is None and ppa.total == 150000


def test_e60_omits_bracing_defect_carried():
    r = calculate(default_inputs())
    q = r.quantities
    assert q["E60"] == pytest.approx(q["E58"] + q["E51"] + q["E47"] + q["E42"])
    assert any(w["defect"] == "D4" for w in r.warnings)


def test_fractional_frames_flagged_and_refusable():
    r = calculate(_inputs("case5"))
    assert any(w["code"] == "FRAMES_FRACTIONAL" for w in r.warnings)
    with pytest.raises(EstimatorInputError) as e:
        calculate(_inputs("case5"), refuse_fractional_frames=True)
    assert e.value.code == "FRAMES_NOT_WHOLE"


@pytest.mark.parametrize("field,value", [
    ("distancia_ejes", 0), ("ancho", 0), ("largo", -1), ("altura_laterales", 0),
    ("altura_techado_lateral", -2), ("columnas_frontales", -1),
])
def test_guards_refuse(field, value):
    with pytest.raises(EstimatorInputError):
        calculate(default_inputs(**{field: value}))


def test_guard_non_number_and_profile_weight():
    with pytest.raises(EstimatorInputError):
        calculate(default_inputs(ancho="abc"))
    with pytest.raises(EstimatorInputError):
        calculate(default_inputs(perfil_columnas=ProfileChoice("x", 0)))


def test_price_override_changes_only_that_line():
    base = calculate(default_inputs())
    r = calculate(default_inputs(), prices={78: 100})
    assert r.subtotal - base.subtotal == pytest.approx(base.quantities["E42"] * 15)

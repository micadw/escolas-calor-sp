"""Testes das fórmulas de conforto térmico (src/indices.py)."""
import sys, pathlib
import numpy as np
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from indices import heat_index, thom_di, graus_hora, norm_robusta, classe_hi, classe_thom


def test_heat_index_valor_tabela_noaa():
    # Tabela NOAA: 90 °F e 50% UR → ~95 °F (35,0 °C)
    assert heat_index(32.22, 50) == pytest.approx(35.0, abs=0.6)


def test_heat_index_ar_ameno_proximo_da_temperatura():
    # abaixo de ~27 °C a sensação fica perto da temperatura do ar
    assert abs(heat_index(22.0, 50) - 22.0) < 1.5


def test_heat_index_cresce_com_umidade():
    assert heat_index(33, 80) > heat_index(33, 40)


def test_thom_di_formula():
    # DI = T − 0,55·(1 − 0,01·UR)·(T − 14,5)
    assert thom_di(30, 60) == pytest.approx(30 - 0.55 * 0.4 * 15.5)
    assert thom_di(25, 100) == pytest.approx(25.0)


def test_graus_hora():
    assert graus_hora([24, 26, 28, 30], limiar=26) == pytest.approx(6.0)
    assert graus_hora([20, 21], limiar=26) == 0.0


def test_norm_robusta_intervalo_e_inversao():
    s = np.arange(100, dtype=float)
    n = norm_robusta(s)
    assert n.min() == 0 and n.max() == 1
    assert (norm_robusta(s, inverter=True) == 1 - n).all()


def test_classes():
    assert str(classe_hi([30])[0]) == "cautela"
    assert str(classe_thom([25])[0]) == ">50% desconfortáveis"

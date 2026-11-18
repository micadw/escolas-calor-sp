"""Índices de conforto térmico e utilitários de normalização.

Uso no Colab:
    import sys; sys.path.append(f"{ROOT}/src")
    from indices import heat_index, thom_di, graus_hora
"""
import numpy as np
import pandas as pd


def heat_index(t_c, ur):
    """Heat Index (NOAA / Rothfusz) em °C.

    t_c: temperatura do ar (°C); ur: umidade relativa (%).
    Para T < 27 °C ou UR < 40% a regressão não é válida: usa a fórmula simples de Steadman.
    """
    t_c = np.asarray(t_c, dtype=float)
    ur = np.asarray(ur, dtype=float)
    t = t_c * 9 / 5 + 32  # NOAA trabalha em °F
    simples = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + ur * 0.094)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * ur - 0.22475541 * t * ur
          - 6.83783e-3 * t ** 2 - 5.481717e-2 * ur ** 2 + 1.22874e-3 * t ** 2 * ur
          + 8.5282e-4 * t * ur ** 2 - 1.99e-6 * t ** 2 * ur ** 2)
    # ajustes NOAA
    aj1 = ((13 - ur) / 4) * np.sqrt(np.clip((17 - np.abs(t - 95)) / 17, 0, None))
    hi = np.where((ur < 13) & (t >= 80) & (t <= 112), hi - aj1, hi)
    aj2 = ((ur - 85) / 10) * ((87 - t) / 5)
    hi = np.where((ur > 85) & (t >= 80) & (t <= 87), hi + aj2, hi)
    hi = np.where(simples < 80, simples, hi)
    return (hi - 32) * 5 / 9


def thom_di(t_c, ur):
    """Índice de Desconforto de Thom (°C)."""
    t_c = np.asarray(t_c, dtype=float)
    ur = np.asarray(ur, dtype=float)
    return t_c - 0.55 * (1 - 0.01 * ur) * (t_c - 14.5)


def classe_thom(di):
    bins = [-np.inf, 21, 24, 27, 29, np.inf]
    labels = ["sem desconforto", "<50% desconfortáveis", ">50% desconfortáveis",
              "maioria desconfortável", "estresse térmico"]
    return pd.cut(di, bins=bins, labels=labels, right=False)


def classe_hi(hi):
    bins = [-np.inf, 27, 32, 41, 54, np.inf]
    labels = ["normal", "cautela", "cautela extrema", "perigo", "perigo extremo"]
    return pd.cut(hi, bins=bins, labels=labels, right=False)


def graus_hora(t_series, limiar=26.0):
    """Soma de max(0, T - limiar) — exposição acumulada acima do limiar."""
    return float(np.clip(np.asarray(t_series, dtype=float) - limiar, 0, None).sum())


def norm_robusta(s, inverter=False, p_lo=5, p_hi=95):
    """Min-max truncado nos percentis p_lo–p_hi → 0..1."""
    s = pd.Series(s, dtype=float)
    lo, hi = np.nanpercentile(s, p_lo), np.nanpercentile(s, p_hi)
    out = ((s.clip(lo, hi) - lo) / (hi - lo)) if hi > lo else s * 0
    return 1 - out if inverter else out

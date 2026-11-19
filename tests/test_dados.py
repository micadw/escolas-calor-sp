"""Validação da base publicada (outputs/) e da coerência com o README."""
import pathlib, re
import pandas as pd
import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CSV = RAIZ / "outputs" / "escolas_calor_sp_v2.csv"
CSV_SITE = RAIZ / "outputs" / "escolas_temperatura.csv"


@pytest.fixture(scope="module")
def d():
    return pd.read_csv(CSV, sep=";", decimal=",", encoding="utf-8-sig")


def test_tamanho_e_chave_unica(d):
    assert len(d) == 3772
    assert d["Código EOL"].is_unique
    assert d["Código EOL"].notna().all()


def test_sem_vazios_em_colunas_chave(d):
    chave = ["Escola", "Tipo", "Etapa", "Rede", "DRE", "Classe de calor", "Ilha de calor média (°C)",
             "Temp. superfície – dias quentes p90 (°C)", "Prioridade (P1 = maior)", "Latitude", "Longitude"]
    faltas = d[chave].isna().sum()
    assert (faltas == 0).all(), faltas[faltas > 0].to_dict()


def test_coordenadas_dentro_do_municipio(d):
    assert d["Latitude"].between(-24.01, -23.35).all()
    assert d["Longitude"].between(-46.83, -46.36).all()


def test_coordenadas_sem_duplicatas_suspeitas(d):
    # até algumas escolas no mesmo endereço (CEU, anexos) é normal; muitas indicaria erro de geocodificação
    dup = d.duplicated(["Latitude", "Longitude"], keep=False).sum()
    assert dup < 0.05 * len(d), f"{dup} escolas com coordenada repetida"


def test_faixas_fisicamente_plausiveis(d):
    assert d["Temp. superfície média (°C)"].between(15, 60).all()
    assert d["Ilha de calor média (°C)"].between(-15, 20).all()
    assert d["Vegetação no entorno (NDVI 0–1)"].between(-1, 1).all()
    assert d["Temp. do ar média em aula (°C, est.)"].between(15, 35).all()
    assert (d["Temp. superfície máxima (°C)"] >= d["Temp. superfície média (°C)"]).all()


def test_classe_coerente_com_ilha_de_calor(d):
    lim = {"1": (-99, 2), "2": (2, 4), "3": (4, 6), "4": (6, 8), "5": (8, 99)}
    for _, r in d.iterrows():
        lo, hi = lim[str(r["Classe de calor"])[0]]
        assert lo <= r["Ilha de calor média (°C)"] < hi + 0.01, r["Escola"]


def test_prioridade_valida_e_dentro_de_cada_etapa(d):
    assert set(d["Prioridade (P1 = maior)"]) == {"P1", "P2", "P3", "P4"}
    for _, g in d.groupby("Etapa"):
        assert set(g["Prioridade (P1 = maior)"]) == {"P1", "P2", "P3", "P4"}
        assert g["Posição na prioridade (dentro da etapa)"].is_unique


def test_bases_publicadas_consistentes(d):
    s = pd.read_csv(CSV_SITE)
    m = d.merge(s, left_on="Código EOL", right_on="cod_esc")
    assert len(m) == len(d) == len(s)
    assert (m["Ilha de calor média (°C)"].round(1) == m["ilha_calor_c"].round(1)).all()
    assert (m["Prioridade (P1 = maior)"] == m["prioridade_v2"]).all()


def test_numeros_do_readme_batem_com_a_base(d):
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    cont = d["Classe de calor"].str[0].value_counts()
    for classe, n in cont.items():
        assert f"{n:,}".replace(",", ".") in readme, f"classe {classe}: {n} não aparece no README"
    p1 = d.groupby("Etapa")["Prioridade (P1 = maior)"].apply(lambda s: (s == "P1").sum())
    assert f"{p1['Infantil']} P1" in readme and f"{p1['Fundamental']} P1" in readme
    dre = d.groupby("DRE")["Ilha de calor média (°C)"].mean().sort_values()
    assert re.search(dre.index[-1], readme) and re.search(dre.index[0], readme)

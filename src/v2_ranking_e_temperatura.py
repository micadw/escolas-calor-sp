# v2 — correções do ranking + produto só de temperatura
# Roda no Colab com %run -i (usa ROOT, RAW, INT, PRO, OUT, CRS já definidos)
import glob, numpy as np, pandas as pd, geopandas as gpd, mapclassify, rasterio
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

LOG = []
def log(*a):
    s = ' '.join(str(x) for x in a); LOG.append(s); print(s)

def cod(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.extract(r'(\d+)')[0], errors='coerce').astype('Int64')

# ------------------------------------------------------------------ dados base
esc = gpd.read_file(f'{INT}/escolas.gpkg', layer='escolas'); esc['cod'] = cod(esc['cod_esc']).values
temp = pd.read_parquet(f'{PRO}/temperatura_escolas.parquet'); temp['cod'] = cod(temp['cod_esc']).values
ind = pd.read_parquet(f'{PRO}/indices_escolas.parquet'); ind['cod'] = cod(ind['cod_esc']).values
temp = temp.drop(columns='cod_esc'); ind = ind.drop(columns='cod_esc')

# ------------------------------------------------------------------ 3) matrículas reais (Perfil das turmas, jun/2026)
f = sorted(glob.glob(f'{RAW}/sme/perfil-das-turmas*.csv'))[-1]
tu = None
for enc in ['utf-8', 'latin-1']:
    try:
        tu = pd.read_csv(f, sep=';', encoding=enc, dtype=str, low_memory=False); break
    except Exception:
        pass
log('turmas:', f.split('/')[-1], tu.shape)
num = ['MATRICULADOS', '0a3anos', '4a5anos', '6a10anos', '11a15anos']
for c in num:
    tu[c] = pd.to_numeric(tu[c].str.replace(',', '.'), errors='coerce').fillna(0)
reg = tu[tu['MODALIDADE'].notna()].copy()                 # tira PAEE/atividades complementares (sem modalidade)
reg['integral'] = reg['DESCTURNO'].fillna('').str.upper().str.contains('INTEGRAL')
reg['cod'] = cod(reg['CD_UNIDADE_EDUCACAO']).values
g = reg.groupby('cod')
mat = pd.DataFrame({
    'matriculas': g['MATRICULADOS'].sum(),
    'alunos_0a3': g['0a3anos'].sum(), 'alunos_4a5': g['4a5anos'].sum(),
    'alunos_6a10': g['6a10anos'].sum(), 'alunos_11a15': g['11a15anos'].sum(),
    'matric_integral': reg[reg['integral']].groupby('cod')['MATRICULADOS'].sum(),
}).fillna(0)
mat['pct_0a5'] = (mat['alunos_0a3'] + mat['alunos_4a5']) / mat['matriculas'].replace(0, np.nan)
mat['pct_integral'] = mat['matric_integral'] / mat['matriculas'].replace(0, np.nan)
# índice etário de vulnerabilidade ao calor: 0–3 = 1,0 | 4–5 = 0,8 | 6–10 = 0,6 | 11–15 = 0,5
mat['idx_idade'] = ((mat['alunos_0a3'] * 1.0 + mat['alunos_4a5'] * 0.8 + mat['alunos_6a10'] * 0.6 + mat['alunos_11a15'] * 0.5)
                    / (mat['alunos_0a3'] + mat['alunos_4a5'] + mat['alunos_6a10'] + mat['alunos_11a15']).replace(0, np.nan))

df = esc.drop(columns='geometry').merge(temp, on='cod', how='left').merge(ind, on='cod', how='left').merge(mat, left_on='cod', right_index=True, how='left')
cob = df['matriculas'].notna()
log('escolas com matrícula encontrada:', int(cob.sum()), 'de', len(df), f'({cob.mean():.1%})')
log(df.groupby(['etapa', 'rede_tipo'])['matriculas'].apply(lambda s: f'{s.notna().mean():.0%} cobertas | {s.sum():,.0f} alunos'))
# faltantes: idade/integral pelo tipo de escola (regra antiga), matrícula = mediana do tipo
t = df['tipoesc'].str.upper().fillna('')
idade_tipo = np.select([t.str.contains(r'CEI|CR\.?P|CRECHE|CCI|CIPS'), t.str.contains('CEMEI'), t.str.contains('EMEI'),
                        t.str.contains('EMEBS')], [1.0, 0.9, 0.8, 0.7], 0.55)
integ_tipo = np.where(t.str.contains(r'CEI|CR\.?P|CRECHE|CCI|CIPS|CEMEI'), 1.0, 0.0)
df['idx_idade'] = df['idx_idade'].fillna(pd.Series(idade_tipo, index=df.index))
df['pct_integral'] = df['pct_integral'].fillna(pd.Series(integ_tipo, index=df.index))
df['matriculas_imputada'] = df['matriculas'].isna()
df['matriculas'] = df['matriculas'].fillna(df.groupby('tipoesc')['matriculas'].transform('median'))

# ------------------------------------------------------------------ 2) normalização por posição percentil (sem empates no topo)
def pct(s, inverter=False):
    r = pd.Series(s, dtype=float).rank(pct=True, method='average')
    return (1 - r) if inverter else r

PESOS = {'E': 0.60, 'S': 0.15, 'C': 0.25}      # 1) peso da sensibilidade reduzido de 0,30 → 0,15
INDIC = {'GH26_ano': 'E', 'h_HI_ge32_ano': 'E', 'LST_p90': 'E', 'ANOM_mean': 'E',
         'matriculas': 'S', 'idx_idade': 'S', 'pct_integral': 'S',
         'NDVI_median': 'C'}
for k in INDIC:
    df[f'n_{k}'] = pct(df[k]).fillna(0.5)
for gname in 'ESC':
    df[gname] = df[[f'n_{k}' for k, v in INDIC.items() if v == gname]].mean(axis=1)
df['score'] = PESOS['E'] * df['E'] + PESOS['S'] * df['S'] + PESOS['C'] * (1 - df['C'])

# ------------------------------------------------------------------ 1) ranking separado por etapa + Monte Carlo
LIM = {}
df['categoria'] = ''; df['rank_etapa'] = 0; df['estab_P1_pct'] = 0.0
rng = np.random.default_rng(42)
for etapa, sub in df.groupby('etapa'):
    nb_ = mapclassify.NaturalBreaks(sub['score'], k=4); lim = list(nb_.bins[:-1]); LIM[etapa] = lim
    cat = pd.cut(sub['score'], [-np.inf] + lim + [np.inf], labels=['P4', 'P3', 'P2', 'P1']).astype(str)
    df.loc[sub.index, 'categoria'] = cat
    df.loc[sub.index, 'rank_etapa'] = sub['score'].rank(ascending=False, method='first').astype(int)
    w = rng.dirichlet(np.array(list(PESOS.values())) * 50, 1000)
    M = np.c_[sub['E'], sub['S'], 1 - sub['C']]; sc = M @ w.T
    frac = (cat == 'P1').mean(); corte = np.quantile(sc, 1 - frac, axis=0)
    df.loc[sub.index, 'estab_P1_pct'] = ((sc >= corte).mean(axis=1) * 100).round(1)
    log(f'\n{etapa}: limiares Jenks {np.round(lim, 3)}'); log(cat.value_counts().sort_index().to_string())
log('\nP1 por rede (dentro de cada etapa):'); log(pd.crosstab([df['etapa'], df['rede_tipo']], df['categoria']).to_string())
log('\nEmpates no score:', int(df['score'].duplicated().sum()))
df.drop(columns=['geometry'], errors='ignore').to_parquet(f'{PRO}/ranking_v2.parquet')

# ------------------------------------------------------------------ produto só de temperatura
# classes de calor pela anomalia média de superfície (°C acima da média da área no mesmo dia de satélite)
BINS = [-np.inf, 2, 4, 6, 8, np.inf]
ROT = ['1 · menos quente (<2 °C)', '2 · moderada (2–4 °C)', '3 · quente (4–6 °C)', '4 · muito quente (6–8 °C)', '5 · extrema (≥8 °C)']
df['classe_calor'] = pd.cut(df['ANOM_mean'], BINS, labels=ROT, right=False).astype(str)
df['rank_calor'] = df['ANOM_mean'].rank(ascending=False, method='first').astype('Int64')
log('\nClasses de calor:'); log(df['classe_calor'].value_counts().sort_index().to_string())

TCOLS = {'rank_calor': 'Posição (1 = mais quente)', 'classe_calor': 'Classe de calor',
         'ANOM_mean': 'Ilha de calor de superfície média (°C)', 'ANOM_p90': 'Ilha de calor nos dias mais quentes – p90 (°C)',
         'LST_mean': 'Temp. superfície média (°C)', 'LST_p90': 'Temp. superfície p90 (°C)', 'LST_max': 'Temp. superfície máx. (°C)',
         'LST_t_amplitude': 'Amplitude entre datas (°C)', 'n_cenas': 'Nº de imagens',
         'Tar_media_aula': 'Temp. do ar média em aula (°C, estimada)', 'Tar_p95_aula': 'Temp. do ar p95 em aula (°C, estimada)',
         'HI_max_aula': 'Sensação térmica máx. em aula (°C)', 'h_HI_ge32_ano': 'Horas/ano em aula com sensação ≥32 °C',
         'GH26_ano': 'Graus-hora/ano acima de 26 °C', 'NDVI_median': 'Vegetação no entorno (NDVI)'}
base = ['cod_esc', 'cod_inep', 'nome', 'tipoesc', 'etapa', 'rede_tipo', 'dre', 'distrito', 'lat', 'lon']

HF = PatternFill('solid', fgColor='1F4E78'); H = Font(bold=True, color='FFFFFF')
def aba(wb, nome, d, larg=None):
    ws = wb.create_sheet(nome); ws.append(list(d.columns))
    for row in d.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in row])
    for c in ws[1]: c.font, c.fill = H, HF
    ws.freeze_panes = 'B2'; ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(d.columns, 1):
        ws.column_dimensions[get_column_letter(i)].width = larg or min(max(len(str(col)) + 2, 10), 34)
    return ws

CORES_CALOR = ['2C7BB6', 'ABD9E9', 'FEE090', 'FDAE61', 'D7191C']
wb = Workbook(); ws = wb.active; ws.title = 'leia-me'
for l in ['Temperatura nas escolas municipais de São Paulo (Educação Infantil e Fundamental, direta + conveniada)',
          f'{len(df)} escolas | Landsat 8/9 Collection 2 (Planetary Computer), meses letivos quentes 2019–2025 | raio de 100 m em volta de cada escola',
          'Ilha de calor de superfície = temperatura da superfície no entorno da escola − média da área no mesmo dia de imagem.',
          'Temperatura do ar e sensação térmica são estimadas: série horária INMET (Mirante e Interlagos) + diferença local do satélite.',
          'Classes: 1 (<2 °C), 2 (2–4), 3 (4–6), 4 (6–8), 5 (≥8 °C) de anomalia média. Sem pesos de idade, matrícula ou vegetação.']:
    ws.append([l])
ws.column_dimensions['A'].width = 130
tt = df.sort_values('rank_calor')[['rank_calor', 'classe_calor'] + base + [c for c in TCOLS if c not in ('rank_calor', 'classe_calor')]].copy()
for c in tt.select_dtypes('float').columns: tt[c] = tt[c].round(2)
tt = tt.rename(columns=TCOLS)
w2 = aba(wb, 'temperatura_escolas', tt)
ci = list(tt.columns).index('Classe de calor') + 1
for r in range(2, len(tt) + 2):
    v = str(w2.cell(r, ci).value or '')
    if v[:1].isdigit(): w2.cell(r, ci).fill = PatternFill('solid', fgColor=CORES_CALOR[int(v[0]) - 1])
res = (df.groupby('dre').agg(escolas=('cod_esc', 'size'), ilha_calor_media=('ANOM_mean', 'mean'),
                             temp_sup_p90=('LST_p90', 'mean'), horas_sensacao_32=('h_HI_ge32_ano', 'mean'),
                             pct_classes_4_5=('classe_calor', lambda s: s.str[:1].isin(['4', '5']).mean() * 100))
       .round(2).sort_values('ilha_calor_media', ascending=False).reset_index())
aba(wb, 'resumo_por_DRE', res)
res2 = (df.groupby(['etapa', 'rede_tipo']).agg(escolas=('cod_esc', 'size'), ilha_calor_media=('ANOM_mean', 'mean'),
        pct_classes_4_5=('classe_calor', lambda s: s.str[:1].isin(['4', '5']).mean() * 100)).round(2).reset_index())
aba(wb, 'resumo_etapa_rede', res2)
wb.save(f'{OUT}/temperatura_escolas.xlsx'); log('salvo outputs/temperatura_escolas.xlsx')

# ------------------------------------------------------------------ mapa só de temperatura (raster + escolas)
g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['lon'], df['lat']), crs=4326).to_crs(CRS)
with rasterio.open(f'{RAW}/lst/lst_composto.tif') as r:
    i = list(r.descriptions).index('ANOM_mean') + 1
    fat = 4
    arr = r.read(i, out_shape=(r.height // fat, r.width // fat)); b = r.bounds
cm = ListedColormap(['#' + c for c in CORES_CALOR]); nm = BoundaryNorm([-50, 2, 4, 6, 8, 50], 5)
fig, ax = plt.subplots(1, 2, figsize=(16, 10))
im = ax[0].imshow(arr, extent=(b.left, b.right, b.bottom, b.top), cmap='RdYlBu_r', vmin=-6, vmax=10)
ax[0].set_title('Ilha de calor de superfície (°C acima da média) — Landsat 2019–2025', fontsize=11)
plt.colorbar(im, ax=ax[0], shrink=0.6, label='°C')
ax[1].imshow(arr, extent=(b.left, b.right, b.bottom, b.top), cmap='Greys', vmin=-6, vmax=14, alpha=0.35)
for k, rot in enumerate(ROT):
    s = g[g['classe_calor'] == rot]
    ax[1].scatter(s.geometry.x, s.geometry.y, s=5, color='#' + CORES_CALOR[k], label=f'{rot} — {len(s)}')
ax[1].legend(title='Classe de calor (escolas)', loc='lower left', fontsize=8, markerscale=3)
ax[1].set_title(f'Escolas municipais por classe de calor (n = {len(g)})', fontsize=11)
for a in ax: a.set_axis_off(); a.set_xlim(b.left, b.right); a.set_ylim(b.bottom, b.top)
plt.tight_layout(); plt.savefig(f'{OUT}/mapa_temperatura_escolas.png', dpi=170, bbox_inches='tight'); plt.close()
log('salvo outputs/mapa_temperatura_escolas.png')

# ------------------------------------------------------------------ Excel do ranking v2
wb = Workbook(); ws = wb.active; ws.title = 'leia-me'
for l in ['Priorização de climatização v2 — escolas municipais de SP (direta + conveniada)',
          'Mudanças em relação à v1: (1) ranking separado por etapa (Infantil / Fundamental) e peso da sensibilidade 0,15;',
          '(2) normalização por posição percentil (sem empates no topo); (3) matrículas, faixa etária e período integral reais',
          '    do "Perfil das turmas" (SME, jun/2026), com imputação pelo tipo de escola onde faltou.',
          'Score = wE·E + wS·S + wC·(1−C); pesos e limiares na aba parametros. Categorias P1–P4 por quebras naturais dentro de cada etapa.']:
    ws.append([l])
ws.column_dimensions['A'].width = 130
par = wb.create_sheet('parametros'); par.append(['parametro', 'valor', 'descricao'])
par.append(['peso_E', PESOS['E'], 'exposição: graus-hora, horas com sensação ≥32 °C, temp. superfície p90, ilha de calor'])
par.append(['peso_S', PESOS['S'], 'sensibilidade: matrículas, idade dos alunos, % em período integral'])
par.append(['peso_C', PESOS['C'], 'capacidade adaptativa: vegetação no entorno (entra como 1−C)'])
for etapa in ['Infantil', 'Fundamental']:
    for nm_, v in zip(['P3', 'P2', 'P1'], LIM[etapa]):
        par.append([f'lim_{nm_}_{etapa}', float(v), f'{etapa}: score ≥ → {nm_}'])
for c in par[1]: c.font, c.fill = H, HF
par.column_dimensions['A'].width = 22; par.column_dimensions['C'].width = 80
FILL = {'P1': 'B2182B', 'P2': 'EF8A62', 'P3': 'FDDBC7', 'P4': 'D1E5F0'}
cols_rk = ['rank_etapa', 'categoria', 'estab_P1_pct', 'score', 'E', 'S', 'C'] + base + \
          ['matriculas', 'matriculas_imputada', 'idx_idade', 'pct_integral', 'ANOM_mean', 'LST_p90', 'Tar_media_aula',
           'h_HI_ge32_ano', 'GH26_ano', 'NDVI_median']
for etapa in ['Infantil', 'Fundamental']:
    d = df[df['etapa'] == etapa].sort_values('rank_etapa')[cols_rk].copy()
    for c in d.select_dtypes('float').columns: d[c] = d[c].round(3)
    wsx = aba(wb, f'ranking_{etapa.lower()}', d)
    ci = list(d.columns).index('categoria') + 1
    for r in range(2, len(d) + 2):
        v = wsx.cell(r, ci).value
        if v in FILL: wsx.cell(r, ci).fill = PatternFill('solid', fgColor=FILL[v])
# aba com fórmulas: score recalcula com os pesos da aba parametros
sc = df[['cod_esc', 'nome', 'etapa'] + [f'n_{k}' for k in INDIC] + ['E', 'S', 'C']].round(4)
ws = aba(wb, 'score_formulas', sc)
L = lambda x: get_column_letter(sc.columns.get_loc(x) + 1)
ks, kc = sc.shape[1] + 1, sc.shape[1] + 2
ws.cell(1, ks, 'score').font = H; ws.cell(1, ks).fill = HF; ws.cell(1, kc, 'categoria').font = H; ws.cell(1, kc).fill = HF
S_ = get_column_letter(ks); Et = L('etapa')
for r in range(2, len(sc) + 2):
    ws.cell(r, ks, f"=parametros!$B$2*{L('E')}{r}+parametros!$B$3*{L('S')}{r}+parametros!$B$4*(1-{L('C')}{r})").number_format = '0.000'
    ws.cell(r, kc, f'=IF({Et}{r}="Infantil",IF({S_}{r}>=parametros!$B$7,"P1",IF({S_}{r}>=parametros!$B$6,"P2",IF({S_}{r}>=parametros!$B$5,"P3","P4"))),'
                   f'IF({S_}{r}>=parametros!$B$10,"P1",IF({S_}{r}>=parametros!$B$9,"P2",IF({S_}{r}>=parametros!$B$8,"P3","P4"))))')
DIC = {'rank_etapa': 'posição dentro da etapa (1 = maior prioridade)', 'categoria': 'P1 (crítica) … P4, quebras naturais dentro da etapa',
       'estab_P1_pct': '% de 1.000 simulações de pesos em que a escola fica em P1', 'score': 'wE·E + wS·S + wC·(1−C)',
       'E, S, C': 'sub-índices 0–1 (média das posições percentis dos indicadores)', 'matriculas': 'matriculados em turmas regulares (jun/2026)',
       'matriculas_imputada': 'True = escola não encontrada no Perfil das turmas; usada a mediana do tipo de escola',
       'idx_idade': 'média ponderada por aluno: 0–3 anos = 1,0; 4–5 = 0,8; 6–10 = 0,6; 11–15 = 0,5',
       'pct_integral': 'fração dos alunos em turmas de período integral', 'ANOM_mean': 'ilha de calor de superfície média (°C)',
       'LST_p90': 'temp. de superfície p90 (°C)', 'Tar_media_aula': 'temp. do ar média em aula (°C, estimada)',
       'h_HI_ge32_ano': 'horas letivas/ano com sensação térmica ≥ 32 °C', 'GH26_ano': 'graus-hora/ano acima de 26 °C em aula',
       'NDVI_median': 'vegetação no entorno (NDVI mediano)'}
aba(wb, 'dicionario', pd.DataFrame(DIC.items(), columns=['campo', 'descricao']))
wb.save(f'{OUT}/ranking_escolas_v2.xlsx'); log('salvo outputs/ranking_escolas_v2.xlsx')

# ------------------------------------------------------------------ mapa do ranking v2 (um painel por etapa)
cores = {'P1': '#b2182b', 'P2': '#ef8a62', 'P3': '#fddbc7', 'P4': '#92c5de'}
fig, ax = plt.subplots(1, 2, figsize=(16, 10))
for a, etapa in zip(ax, ['Infantil', 'Fundamental']):
    s = g[g['etapa'] == etapa]
    for k in ['P4', 'P3', 'P2', 'P1']:
        q = s[s['categoria'] == k]; a.scatter(q.geometry.x, q.geometry.y, s=6, color=cores[k], label=f'{k} — {len(q)}')
    a.set_title(f'{etapa} (n = {len(s)})'); a.legend(title='Prioridade', loc='lower left', markerscale=3); a.set_axis_off()
    a.set_xlim(b.left, b.right); a.set_ylim(b.bottom, b.top)
plt.suptitle('Prioridade de climatização v2 — ranking por etapa', fontsize=13)
plt.tight_layout(); plt.savefig(f'{OUT}/mapa_prioridade_v2.png', dpi=170, bbox_inches='tight'); plt.close()
log('salvo outputs/mapa_prioridade_v2.png')
open(f'{INT}/_log_v2.txt', 'w').write('\n'.join(LOG))

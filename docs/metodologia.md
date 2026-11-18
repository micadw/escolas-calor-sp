# Metodologia — Exposição térmica das escolas municipais de São Paulo

## 1. Unidade de análise e universo
- Unidade: escola (código EOL/INEP). Universo: rede municipal **direta** de Educação Infantil (CEI direto, EMEI, CEMEI)
  e Ensino Fundamental (EMEF, EMEFM, EMEBS, CEU-EMEF/EMEI).
- Decisão: inclui a rede parceira/conveniada (CEIs indiretos e creches conveniadas). São prédios não públicos — a execução
  de obras nelas depende de termo com a entidade.
- Fontes: GeoSampa › Equipamentos › Educação (camadas "Educação Infantil", "Ensino Fundamental e Médio", "CEU"),
  cruzadas com o cadastro de escolas da SME em Dados Abertos (tipo, DRE, matrículas, turnos).

## 2. Temperatura de superfície (LST)
- O mapa do UrbVerde ("Ilhas de calor urbano de superfície") é derivado de Landsat 8/9 (banda termal, 30 m reamostrado;
  resolução física da banda termal ~100 m). O portal só exporta PNG ⇒ **não serve para análise**.
- Obter o raster original: Google Earth Engine, coleção `LANDSAT/LC0[89]/C02/T1_L2`, banda `ST_B10`
  (×0.00341802 + 149.0 − 273.15 = °C), máscara de nuvem via `QA_PIXEL`, cenas de verão (dez–mar) e de
  primavera/outono letivos (fev–abr, set–nov), 2019–2025. Alternativa: pedir o GeoTIFF à equipe UrbVerde (IAU-USP).
- Por pixel, compor: LST mín, média, mediana, p90, máx e desvio-padrão ao longo das cenas;
  anomalia = LST_pixel − média municipal da mesma cena (é o que o UrbVerde chama de ilha de calor).

## 3. Cruzamento ponto × raster (o "join" com granularidade de pixel)
- Escola é ponto; LST é grade de 30 m. Amostrar só o pixel do ponto é frágil (ponto pode cair na rua, georreferência imprecisa).
- Usar **estatística zonal ponderada por fração de cobertura** (`exactextract`): cada pixel entra com peso = área de
  interseção com o polígono / área do pixel. Polígono de referência, em ordem de preferência:
  1. lote fiscal da escola (GeoSampa › Cadastro › Lotes) — join espacial ponto-em-polígono;
  2. buffer circular de 100 m (≈ 1 pixel termal nativo); testar 50/150/250 m na análise de sensibilidade.
- Tudo em SIRGAS 2000 / UTM 23S (EPSG:31983) antes do cálculo. Saída: 1 linha por escola × estatística × período.

## 4. Do solo para o ar: temperatura do ar, umidade e sensação térmica
- LST ≠ temperatura do ar e é um retrato das ~10h (passagem do Landsat). Sensação térmica exige T_ar + UR horárias.
- Estações: INMET (A701 Mirante de Santana, A771 Interlagos, A755 Barueri) e rede CGE/PMSP (~30 estações).
- Modelo: regressão (ou regression-kriging) T_ar_h = f(LST anomalia, NDVI, altitude, distância a corpos d'água, hora) calibrada
  nas estações; validar por leave-one-station-out (RMSE). Gera T_ar e UR horárias estimadas por escola.

## 5. Índices de conforto (por hora letiva, 7h–19h, dias letivos)
- **Heat Index / sensação térmica** (NOAA, Rothfusz) — válido p/ T ≥ 27 °C:
  HI = −8.784695 + 1.61139411·T + 2.338549·UR − 0.14611605·T·UR − 0.012308094·T² − 0.016424828·UR²
       + 0.002211732·T²·UR + 0.00072546·T·UR² − 0.000003582·T²·UR²   (T em °C, UR em %)
- **Índice de Desconforto de Thom**: DI = T − 0.55·(1 − 0.01·UR)·(T − 14.5);
  faixas: <21 sem desconforto; 21–24 <50% desconfortáveis; 24–27 >50%; 27–29 maioria; ≥29 estresse.
- (Opcional) **UTCI** via `pythermalcomfort` se houver vento/radiação.
- Referência normativa de conforto para trabalho intelectual: NR-17 (faixa de 18 a 25 °C) — conferir texto vigente.
- Indicadores por escola:
  - T_mín, T_méd, T_máx, amplitude (máx−mín) e desvio-padrão;
  - **graus-hora** acima de 26 °C no horário de aula: GH = Σ max(0, T_h − 26);
  - nº de horas letivas com DI ≥ 24 e com HI ≥ 32 (“cautela extrema”).

## 6. Vulnerabilidade (quem sofre o calor)
- Matrículas totais; peso extra para 0–5 anos (CEI/EMEI); turno integral; alunos com deficiência (se disponível).
- Contexto: renda/IPVS do setor censitário, cobertura arbórea no buffer (UrbVerde/NDVI).
- Edificação: AC já existente (inventário SME), tipo de cobertura (telha metálica/fibrocimento), padrão construtivo — se obtido.

## 7. Score e categorias de priorização
1. Normalizar cada indicador 0–1 (min-max robusto: p5–p95 truncado), invertendo os “quanto maior, melhor”.
2. Sub-índices: Exposição E (GH, HI_horas, LST_p90, anomalia); Sensibilidade S (idade, integral, matrículas);
   Capacidade adaptativa C (sombra/árvores, AC existente).
3. Score = w_E·E + w_S·S + w_C·(1 − C). Pesos iniciais 0,5/0,3/0,2; alternativa AHP com SME.
4. Classes: quebras naturais (Jenks, `mapclassify`) ou quantis → **P1 (crítica) / P2 / P3 / P4**.
   Conferir com k-means (k = 4) sobre E e S para checar robustez.
5. Sensibilidade: Monte Carlo nos pesos (±20%) e nos buffers; reportar % de vezes que cada escola fica em P1.
6. (Opcional) Hotspots LISA / Getis-Ord Gi* sobre o score para priorizar por DRE.

## 8. Saída — `outputs/ranking_escolas.xlsx`
| aba | conteúdo |
|---|---|
| leia-me | objetivo, fontes, datas, decisões |
| escolas | id EOL/INEP, nome, tipo, DRE, distrito, coordenadas, matrículas |
| temperatura | LST mín/méd/máx/p90/dp, anomalia, T_ar estimada |
| indices | HI, DI, graus-hora, horas críticas |
| vulnerabilidade | indicadores S e C |
| score | indicadores normalizados, sub-índices, score, categoria |
| ranking | ordenado, com P1–P4 e estabilidade (Monte Carlo) |
| parametros | pesos, limiares, buffers (editáveis; score recalcula por fórmula) |
| dicionario | descrição e unidade de cada coluna |

## 9. Limitações
- LST capta superfícies (telhados, asfalto), não o interior das salas; serve como proxy de exposição externa.
- Landsat a cada 8–16 dias, só ~10h, sem nuvens: subamostra os dias mais quentes/nublados.
- Interior da sala depende de orientação, ventilação, cobertura — idealmente validar com sensores (data loggers) em amostra de escolas.

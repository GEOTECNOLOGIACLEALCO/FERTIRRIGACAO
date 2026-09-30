import os
import json
from datetime import datetime
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon
import shapely
import warnings

warnings.filterwarnings("ignore")

# ==========================================
# 1. DEFINIÇÃO DOS CAMINHOS DE ENTRADA E SAÍDA
# ==========================================
SHP_LINHAS = r"M:\04-Fertirrigação\2_Projetos de Aplicação\2026\2-SOLINFTEC\LINHAS_CLEALCO_SOLINFTEC.shp"
SHP_TALHOES = r"W:\11-SHAPES TEMATICOS\01-SOLINFTEC\2026\Shape Clealco - Safra 2026 - Atualização em 06-08-2026.shp"
SHP_TUBULACAO = r"M:\04-Fertirrigação\2_Projetos de Aplicação\2026\7-VETORES\TUBULACAO.shp"
EXCEL_BASE = r"M:\04-Fertirrigação\2_Projetos de Aplicação\2026\BASE AGRONOMICO.xlsx"
OUTPUT_DIR = r"M:\04-Fertirrigação\2_Projetos de Aplicação\2026\6-GITHUB APP"

os.makedirs(OUTPUT_DIR, exist_ok=True)
DATA_ATUALIZACAO = datetime.now().strftime("%d/%m/%Y %H:%M")

print("⏳ Iniciando o processamento do Motor WebGL MapLibre. Por favor, aguarde...")

# ==========================================
# 2. PROCESSAMENTO DAS LINHAS E GERAÇÃO DE LABELS.JSON
# ==========================================
gdf_linhas = gpd.read_file(SHP_LINHAS)
gdf_linhas = gdf_linhas.fillna('')
gdf_linhas.columns = [col.lower() for col in gdf_linhas.columns]

if gdf_linhas.crs is None:
    gdf_linhas = gdf_linhas.set_crs(epsg=4326)

gdf_linhas_metric = gdf_linhas.to_crs(epsg=32722)

# Cálculo da Dimensão da Linha em metros reais UTM
gdf_linhas_metric['Metragem_m'] = gdf_linhas_metric.geometry.length.round(1)

gdf_linhas_metric['geometry'] = gdf_linhas_metric.geometry.simplify(1.0, preserve_topology=True)
gdf_linhas = gdf_linhas_metric.to_crs(epsg=4326)

if 'layer' in gdf_linhas.columns:
    gdf_linhas['layer_num'] = gdf_linhas['layer'].astype(str).str.extract(r'(\d+)').astype(float)
    gdf_linhas = gdf_linhas.sort_values(by='layer_num', na_position='last').drop(columns=['layer_num'])

features_linhas = []
for idx, row in gdf_linhas.iterrows():
    geom = row.geometry
    if geom is None or geom == '': continue
    
    lines = [geom] if isinstance(geom, LineString) else list(geom.geoms) if isinstance(geom, MultiLineString) else []
        
    for line in lines:
        coords = list(line.coords)
        if len(coords) < 2: continue
            
        start_pt, end_pt = coords[0], coords[-1]
        
        props = row.drop('geometry').to_dict()
        props = {k: (v if not hasattr(v, 'item') else v.item()) for k, v in props.items()}
        props['start_point'] = [start_pt[1], start_pt[0]]  
        props['end_point'] = [end_pt[1], end_pt[0]] 

        feature = {
            "type": "Feature",
            "geometry": json.loads(gpd.GeoSeries([line]).to_json())['features'][0]['geometry'],
            "properties": props
        }
        features_linhas.append(feature)

with open(os.path.join(OUTPUT_DIR, "data.geojson"), "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": features_linhas}, f, ensure_ascii=False)

with open(os.path.join(OUTPUT_DIR, "labels.json"), "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": features_linhas}, f, ensure_ascii=False)

print("✅ Camada de Linhas e labels.json geradas.")

# ==========================================
# 3. UNIÃO DE TALHÕES COM BASE AGRONÔMICO (EXCEL)
# ==========================================
print("⏳ Lendo base de dados Excel e mesclando com o Shapefile...")
df_excel = pd.read_excel(EXCEL_BASE)
df_excel.columns = [col.strip().upper() for col in df_excel.columns]

gdf_talhoes = gpd.read_file(SHP_TALHOES)
gdf_talhoes.columns = [col.strip().upper() if col.lower() != 'geometry' else 'geometry' for col in gdf_talhoes.columns]

if gdf_talhoes.crs is None:
    gdf_talhoes = gdf_talhoes.set_crs(epsg=4326)

gdf_talhoes['CHAVE'] = gdf_talhoes['CHAVE'].astype(str).str.strip()
df_excel['CHAVE'] = df_excel['CHAVE'].astype(str).str.strip()

col_area = None
for col in ['ÁREA', 'AREA', 'AREA_HA', 'HECTARES']:
    if col in df_excel.columns:
        col_area = col
        break
    elif col in gdf_talhoes.columns:
        col_area = col
        break

cols_excel = ['CHAVE', 'UNIDADE', 'STATUS PROJETO']
if col_area and col_area in df_excel.columns and col_area not in cols_excel:
    cols_excel.append(col_area)

gdf_talhoes_merged = gdf_talhoes.merge(
    df_excel[cols_excel], 
    on='CHAVE', 
    how='left'
)

gdf_talhoes_merged = gdf_talhoes_merged.fillna('NÃO INFORMADO')

if col_area and col_area in gdf_talhoes_merged.columns:
    gdf_talhoes_merged['AREA_CALC'] = (
        gdf_talhoes_merged[col_area]
        .astype(str)
        .str.replace(',', '.')
        .str.extract(r'([\d\.]+)')[0]
        .astype(float)
        .fillna(0.0)
    )
else:
    gdf_geo_area = gdf_talhoes_merged.to_crs(epsg=32722)
    gdf_talhoes_merged['AREA_CALC'] = (gdf_geo_area.geometry.area / 10000.0).round(2)

cols_para_string = [c for c in gdf_talhoes_merged.columns if c not in ['geometry', 'AREA_CALC']]
for col in cols_para_string:
    gdf_talhoes_merged[col] = gdf_talhoes_merged[col].astype(str)

gdf_talhoes_merged['geometry'] = shapely.make_valid(gdf_talhoes_merged.geometry)
gdf_talhoes_metric = gdf_talhoes_merged.to_crs(epsg=32722)

# ==========================================
# 4. GERAÇÃO DO PERÍMETRO ROBUSTA POR FAZENDA
# ==========================================
print("⏳ Gerando Perímetro da Fazenda...")

def remover_buracos(geometry):
    if geometry is None or geometry.is_empty:
        return geometry
    geometry = shapely.make_valid(geometry)
    if isinstance(geometry, Polygon):
        return Polygon(geometry.exterior)
    elif isinstance(geometry, MultiPolygon):
        polys = [Polygon(p.exterior) for p in geometry.geoms if not p.is_empty]
        return MultiPolygon(polys)
    return geometry

campo_fazenda = 'FAZENDA' if 'FAZENDA' in gdf_talhoes_metric.columns else gdf_talhoes_metric.columns[0]

perim_rows = []
for name, group in gdf_talhoes_metric.groupby(campo_fazenda):
    cleaned_geoms = []
    for g in group.geometry:
        if g and not g.is_empty:
            valid_g = shapely.make_valid(g).buffer(0)
            if not valid_g.is_empty:
                buf_g = valid_g.buffer(10)
                if not buf_g.is_empty:
                    cleaned_geoms.append(buf_g)
    
    if not cleaned_geoms:
        continue
        
    try:
        merged = shapely.union_all(cleaned_geoms, grid_size=0.1)
    except Exception:
        try:
            merged = shapely.union_all(cleaned_geoms, grid_size=1.0)
        except Exception:
            merged = cleaned_geoms[0]
            for cg in cleaned_geoms[1:]:
                try:
                    merged = merged.union(cg)
                except Exception:
                    merged = shapely.make_valid(merged).union(shapely.make_valid(cg))

    merged = shapely.make_valid(merged).buffer(-10)
    merged = remover_buracos(merged)
    merged = merged.simplify(5.0, preserve_topology=True)
    
    perim_rows.append({campo_fazenda: name, 'geometry': merged})

gdf_perim_dissolved = gpd.GeoDataFrame(perim_rows, crs=gdf_talhoes_metric.crs)
gdf_perimetro_final = gdf_perim_dissolved.to_crs(epsg=4326)

if 'GEOMETRY' in gdf_perimetro_final.columns and gdf_perimetro_final.geometry.name == 'geometry':
    gdf_perimetro_final = gdf_perimetro_final.drop(columns=['GEOMETRY'])

gdf_perimetro_final.to_file(os.path.join(OUTPUT_DIR, "perimetro.geojson"), driver="GeoJSON")

gdf_talhoes_metric['geometry'] = gdf_talhoes_metric.geometry.simplify(3.0, preserve_topology=True)
gdf_talhoes_final = gdf_talhoes_metric.to_crs(epsg=4326)

if 'GEOMETRY' in gdf_talhoes_final.columns and gdf_talhoes_final.geometry.name == 'geometry':
    gdf_talhoes_final = gdf_talhoes_final.drop(columns=['GEOMETRY'])

gdf_talhoes_final.to_file(os.path.join(OUTPUT_DIR, "talhoes.geojson"), driver="GeoJSON")

print("✅ Talhões e Perímetro gerados com sucesso.")

# ==========================================
# 5. PROCESSAMENTO DA TUBULAÇÃO COM HERANÇA ESPACIAL
# ==========================================
print("⏳ Processando Tubulação...")
if os.path.exists(SHP_TUBULACAO):
    gdf_tub = gpd.read_file(SHP_TUBULACAO)
    gdf_tub = gdf_tub.fillna('')
    gdf_tub.columns = [col.lower() if col.lower() != 'geometry' else 'geometry' for col in gdf_tub.columns]
    
    if gdf_tub.crs is None:
        gdf_tub = gdf_tub.set_crs(epsg=4326)
    gdf_tub = gdf_tub.to_crs(epsg=4326)
    
    if 'layer' not in gdf_tub.columns:
        gdf_perim_join = gdf_perimetro_final[[campo_fazenda, 'geometry']].copy()
        gdf_perim_join = gdf_perim_join.rename(columns={campo_fazenda: 'layer'})
        
        gdf_tub = gpd.sjoin(gdf_tub, gdf_perim_join, how='left', predicate='intersects')
        gdf_tub = gdf_tub[~gdf_tub.index.duplicated(keep='first')]  
        gdf_tub = gdf_tub.drop(columns=['index_right'], errors='ignore')

    gdf_tub.to_file(os.path.join(OUTPUT_DIR, "tubulacao.geojson"), driver="GeoJSON")
    print("✅ Camada de Tubulação processada com sucesso.")
else:
    with open(os.path.join(OUTPUT_DIR, "tubulacao.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": []}, f)
    print("⚠️ Arquivo de Tubulação não encontrado. GeoJSON vazio gerado.")

# ==========================================
# 6. ESTATÍSTICAS BASEADAS NA SOMA DA ÁREA (HA)
# ==========================================
def extrair_estatisticas_area(df, coluna):
    valid_df = df[df[coluna].str.upper() != 'NÃO INFORMADO']
    if coluna == 'UNIDADE':
        valid_df = valid_df[valid_df[coluna].str.upper().isin(['CLEMENTINA', 'QUEIROZ'])]
        
    grouped = valid_df.groupby(coluna)['AREA_CALC'].sum().to_dict()
    return [{"label": str(k), "area_ha": round(float(v), 2)} for k, v in grouped.items()]

def extrair_projeto_por_unidade(df, unidade):
    sub_df = df[df['UNIDADE'].str.upper() == unidade]
    valid_df = sub_df[sub_df['STATUS PROJETO'].str.upper() != 'NÃO INFORMADO']
    grouped = valid_df.groupby('STATUS PROJETO')['AREA_CALC'].sum().to_dict()
    res = [{"label": str(k), "area_ha": round(float(v), 2)} for k, v in grouped.items()]
    total_area = round(float(valid_df['AREA_CALC'].sum()), 2)
    if total_area > 0:
        res.append({"label": f"TOTAL {unidade}", "area_ha": total_area})
    return res

df_valido_total = gdf_talhoes_merged[
    (gdf_talhoes_merged['UNIDADE'].str.upper() != 'NÃO INFORMADO') & 
    (gdf_talhoes_merged['UNIDADE'].str.upper().isin(['CLEMENTINA', 'QUEIROZ']))
]

estatisticas_json = {
    "unidades": extrair_estatisticas_area(gdf_talhoes_merged, 'UNIDADE'),
    "projeto_clementina": extrair_projeto_por_unidade(gdf_talhoes_merged, 'CLEMENTINA'),
    "projeto_queiroz": extrair_projeto_por_unidade(gdf_talhoes_merged, 'QUEIROZ'),
    "area_total_ha": round(float(df_valido_total['AREA_CALC'].sum()), 2)
}

with open(os.path.join(OUTPUT_DIR, "indicadores.json"), "w", encoding="utf-8") as f:
    json.dump(estatisticas_json, f, ensure_ascii=False, indent=2)

# ==========================================
# 7. SERVICE WORKER (v46)
# ==========================================
sw_code = """
const CACHE_NAME = 'ferti-clealco-v46'; 
const TILE_CACHE = 'ferti-tiles-v1';

const ASSETS = [
  './', './index.html', './data.geojson', './talhoes.geojson', './perimetro.geojson', './tubulacao.geojson', './indicadores.json', './labels.json', './manifest.json',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(ASSETS)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.map((k) => { if (k !== CACHE_NAME && k !== TILE_CACHE) return caches.delete(k); })
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.hostname.includes('arcgisonline.com') || url.hostname.includes('maplibre.org')) {
    e.respondWith(
      caches.match(e.request).then((res) => res || fetch(e.request).catch(() => new Response('')))
    );
  } else {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
  }
});
"""

with open(os.path.join(OUTPUT_DIR, "sw.js"), "w", encoding="utf-8") as f:
    f.write(sw_code.strip())

# ==========================================
# 8. MANIFESTO DO APP
# ==========================================
manifest_code = {
  "name": "FERTIRRIGAÇÃO | CLEALCO",
  "short_name": "Ferti Clealco",
  "start_url": "./index.html",
  "display": "standalone",
  "background_color": "#0f172a",
  "theme_color": "#0f172a",
  "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/854/854878.png", "sizes": "512x512", "type": "image/png"}]
}

with open(os.path.join(OUTPUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest_code, f, indent=2)

# ==========================================
# 9. INTERFACE HTML COM FILTRO BLINDADO
# ==========================================
html_content = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>FERTIRRIGAÇÃO | CLEALCO</title>
  <link rel="manifest" href="manifest.json">
  <meta name="theme-color" content="#0f172a">
  
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" />
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Plus Jakarta Sans', sans-serif; -webkit-tap-highlight-color: transparent; }
    body, html { width: 100%; height: 100%; overflow: hidden; background: #0f172a; color: #f8fafc; }
    
    .view-section { width: 100%; height: calc(100% - 60px); position: absolute; top: 0; left: 0; }
    #map-view { display: block; }
    #dash-view { display: none; overflow-y: auto; padding: 20px; background: #0f172a; z-index: 500; }

    #map { width: 100%; height: 100%; z-index: 1; }

    .glass {
      background: rgba(15, 23, 42, 0.88); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.12); box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }

    .top-panel { position: absolute; top: 16px; left: 16px; right: 16px; z-index: 1000; display: flex; flex-direction: column; gap: 10px; }
    .header-bar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-radius: 16px; }
    .title { font-size: 15px; font-weight: 800; letter-spacing: 0.5px; background: linear-gradient(135deg, #ffffff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .updated-at { font-size: 10px; color: #38bdf8; font-weight: 600; margin-top: 2px; }
    .btn-toggle { background: rgba(255,255,255,0.1); border: none; color: #fff; padding: 8px 12px; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px; }

    .search-body { padding: 16px; border-radius: 18px; display: flex; flex-direction: column; gap: 12px; transition: all 0.3s ease; transform-origin: top; }
    .search-body.collapsed { opacity: 0; transform: scaleY(0); pointer-events: none; position: absolute; visibility: hidden; }

    label { font-size: 11px; text-transform: uppercase; font-weight: 700; color: #94a3b8; }
    select { width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 12px; color: #fff; font-size: 14px; outline: none; font-weight: 500; }
    select option { background: #0f172a; color: #fff; }

    .action-btn { width: 100%; padding: 10px; border-radius: 10px; font-size: 12px; font-weight: 700; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; }
    .btn-download { background: linear-gradient(135deg, #22c55e, #16a34a); color: white; }
    .btn-update { background: linear-gradient(135deg, #ef4444, #dc2626); color: white; }

    .bottom-nav {
      position: absolute; bottom: 0; left: 0; right: 0; height: 60px;
      z-index: 2000; display: flex; justify-content: space-around; align-items: center;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
    }
    .nav-item {
      display: flex; flex-direction: column; align-items: center; gap: 4px;
      background: none; border: none; color: #94a3b8; font-size: 11px; font-weight: 700; cursor: pointer; flex: 1; height: 100%; justify-content: center;
    }
    .nav-item.active { color: #38bdf8; }
    .nav-icon { font-size: 18px; }

    .fab-group { position: absolute; bottom: 80px; right: 16px; z-index: 1000; display: flex; flex-direction: column; gap: 12px; align-items: flex-end; }
    .fab { width: 45px; height: 45px; border-radius: 50%; border: none; color: white; font-size: 20px; display: flex; align-items: center; justify-content: center; cursor: pointer; box-shadow: 0 5px 15px rgba(0,0,0,0.5); }
    .fab-compass { background: linear-gradient(135deg, #8b5cf6, #6d28d9); font-size: 20px;} 
    .fab-gps { background: linear-gradient(135deg, #0284c7, #2563eb); }
    .fab-reset { background: linear-gradient(135deg, #475569, #334155); }

    .gps-status-bar { align-self: flex-start; padding: 6px 12px; border-radius: 10px; font-size: 11px; font-weight: 700; color: #94a3b8; display: flex; align-items: center; gap: 6px; }

    #map-legend { position: absolute; bottom: 80px; left: 16px; z-index: 1000; padding: 12px; border-radius: 12px; display: none; flex-direction: column; gap: 6px; max-width: 250px; }
    .legend-title { font-size: 11px; color: #38bdf8; font-weight: 800; text-transform: uppercase; margin-bottom: 4px; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 700; color: #f8fafc; }
    .legend-color { width: 14px; height: 14px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); }

    #loader { position: fixed; inset: 0; background: #0f172a; z-index: 9999; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 15px; transition: opacity 0.4s ease; }
    .loader-text { font-size: 15px; font-weight: 700; color: #38bdf8; animation: pulse 1.5s infinite; text-transform: uppercase; letter-spacing: 1px; text-align: center;}
    
    #btn-skip-loader {
        margin-top: 20px;
        padding: 10px 20px;
        background: rgba(255, 255, 255, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 20px;
        color: #fff;
        font-weight: 600;
        cursor: pointer;
        font-size: 12px;
        transition: background 0.3s;
    }
    #btn-skip-loader:hover { background: rgba(255, 255, 255, 0.2); }
    
    .hidrorrol-loader { display: flex; justify-content: center; align-items: center; margin-bottom: 10px; position: relative; width: 140px; height: 100px; }
    
    @keyframes moveCart { 0% { transform: translateX(80px); } 100% { transform: translateX(0px); } }
    @keyframes retractHose { 0% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: 80; } }
    @keyframes sprayFlow { from { stroke-dashoffset: 15; } to { stroke-dashoffset: 0; } }
    @keyframes pulse { 0% { opacity: 0.7; } 50% { opacity: 1; } 100% { opacity: 0.7; } }

    .cart-group { animation: moveCart 8s linear infinite; }
    .hose-line { stroke-dasharray: 80; animation: retractHose 8s linear infinite; }
    .spray-stream { animation: sprayFlow 0.5s linear infinite; opacity: 0.9; }
    .spray-stream-2 { animation: sprayFlow 0.4s linear infinite; opacity: 0.7; }
    .spray-stream-3 { animation: sprayFlow 0.6s linear infinite; opacity: 0.8; }

    #progress-container { position: absolute; bottom: 80px; left: 16px; right: 80px; z-index: 1000; background: rgba(15, 23, 42, 0.95); padding: 12px; border-radius: 12px; display: none; border: 1px solid rgba(255,255,255,0.2); }
    .progress-bar { width: 100%; height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 6px; }
    .progress-fill { width: 0%; height: 100%; background: #22c55e; transition: width 0.2s; }
    .progress-text { font-size: 11px; font-weight: 600; color: #fff; }

    .checkbox-container { display: flex; align-items: center; gap: 8px; color: #e2e8f0; font-size: 12px; font-weight: 600; cursor: pointer; }

    .dash-header { margin-bottom: 20px; font-size: 18px; font-weight: 800; color: #fff; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; display: flex; justify-content: space-between; align-items: flex-end; }
    .total-area-badge { font-size: 13px; color: #38bdf8; font-weight: 700; }
    .section-title { font-size: 14px; font-weight: 700; color: #38bdf8; margin: 15px 0 10px 0; }
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .card { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); padding: 14px; border-radius: 14px; display: flex; flex-direction: column; gap: 6px; }
    .card-val { font-size: 20px; font-weight: 800; color: #fff; }
    .card-lbl { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; }

    .maplibregl-popup-content { background: #0f172a; color: #fff; border: 1px solid rgba(255,255,255,0.2); border-radius: 12px; padding: 15px; }
    .maplibregl-popup-close-button { color: #fff; font-size: 16px; top: 5px; right: 5px; }
    .maplibregl-popup-tip { border-top-color: #0f172a; }
  </style>
</head>
<body>

  <div id="loader">
    <div class="hidrorrol-loader">
        <svg viewBox="0 0 140 100" width="140" height="100">
            <line x1="5" y1="85" x2="135" y2="85" stroke="#334155" stroke-width="3" stroke-linecap="round" />
            <line class="hose-line" x1="15" y1="83" x2="95" y2="83" stroke="#1e293b" stroke-width="4" stroke-linecap="round" />
            <rect x="5" y="70" width="10" height="15" fill="#475569" />
            <circle cx="10" cy="65" r="12" fill="#0f172a" stroke="#cbd5e1" stroke-width="2" />
            <circle cx="10" cy="65" r="4" fill="#cbd5e1" />
            <g class="cart-group">
                <path d="M 0 85 L 20 45 L 30 85 Z" fill="none" stroke="#94a3b8" stroke-width="3" stroke-linejoin="round" />
                <circle cx="10" cy="75" r="10" fill="#0f172a" stroke="#cbd5e1" stroke-width="3" />
                <circle cx="10" cy="75" r="3" fill="#cbd5e1" />
                <circle cx="30" cy="80" r="5" fill="#0f172a" stroke="#cbd5e1" stroke-width="2" />
                <line x1="18" y1="48" x2="40" y2="28" stroke="#cbd5e1" stroke-width="5" stroke-linecap="round" />
                <line x1="35" y1="33" x2="45" y2="23" stroke="#38bdf8" stroke-width="3" stroke-linecap="round" />
                <path class="spray-stream" d="M 45 23 Q 70 5 95 50" fill="none" stroke="#38bdf8" stroke-width="4" stroke-linecap="round" stroke-dasharray="2 8" />
                <path class="spray-stream-2" d="M 45 23 Q 65 -5 100 45" fill="none" stroke="#7dd3fc" stroke-width="2" stroke-linecap="round" stroke-dasharray="1 10" />
                <path class="spray-stream-3" d="M 45 23 Q 80 15 90 60" fill="none" stroke="#0ea5e9" stroke-width="3" stroke-linecap="round" stroke-dasharray="3 7" />
            </g>
        </svg>
    </div>
    <div class="loader-text">Carregando o mapa...</div>
    <button id="btn-skip-loader" onclick="forceSkipLoader()">Pular e Abrir Mapa (Offline)</button>
  </div>

  <div id="map-view" class="view-section">
    <div class="top-panel">
      <div class="header-bar glass">
        <div>
          <div class="title">FERTIRRIGAÇÃO | CLEALCO</div>
          <div class="updated-at">Atualizado em: {{DATA_ATUALIZACAO}}</div>
        </div>
        <button class="btn-toggle" onclick="toggleMenu()"><span>👁️</span> Menu</button>
      </div>
      
      <div class="gps-status-bar glass">
        <span>🎯</span>
        <span id="gps-accuracy-text">GPS: Conectando aos satélites...</span>
      </div>

      <div class="search-body glass collapsed" id="search-box">
        <div>
          <label>Pesquisar Fazenda (Linhas)</label>
          <select id="layerSelect" onchange="filterMap()">
            <option value="">-- Todas as Fazendas --</option>
          </select>
        </div>
        
        <div>
          <label>Tematização dos Talhões</label>
          <select id="themeSelect" onchange="applyTheme()">
            <option value="default">Padrão (Cinza)</option>
            <option value="STATUS PROJETO">Status do Projeto</option>
            <option value="UNIDADE">Unidade</option>
          </select>
        </div>

        <hr style="border: 0; height: 1px; background: rgba(255,255,255,0.1); margin: 2px 0;">
        
        <div style="display: flex; flex-direction: column; gap: 8px;">
            <label class="checkbox-container">
              <input type="checkbox" id="toggleTalhoes" onchange="updateLayersVisibility()" checked> Exibir Talhões
            </label>
            <label class="checkbox-container">
              <input type="checkbox" id="togglePerimetro" onchange="updateLayersVisibility()" checked> Exibir Perímetro
            </label>
            <label class="checkbox-container">
              <input type="checkbox" id="toggleLinhas" onchange="updateLayersVisibility()" checked> Exibir Linhas
            </label>
            <label class="checkbox-container">
              <input type="checkbox" id="toggleRotulos" onchange="updateLayersVisibility()" checked> Exibir Rótulos (Metragem)
            </label>
            <label class="checkbox-container">
              <input type="checkbox" id="toggleTubulacao" onchange="updateLayersVisibility()" checked> Exibir Tubulação
            </label>
        </div>

        <hr style="border: 0; height: 1px; background: rgba(255,255,255,0.1); margin: 2px 0;">
        
        <button class="action-btn btn-download" onclick="downloadOfflineMap()">⬇️ Baixar Mapa Offline</button>
        <button class="action-btn btn-update" onclick="clearAndRefresh()">🔄 Atualizar Aplicativo</button>
      </div>
    </div>

    <div id="map-legend" class="glass"></div>

    <div class="fab-group">
      <button class="fab fab-compass" onclick="resetRotation()" title="Alinhar ao Norte (Voltar Reto)">🧭</button>
      <button class="fab fab-gps" onclick="locateUser()" title="Ir para minha posição">🎯</button>
      <button class="fab fab-reset" onclick="resetView()" title="Visão Geral">🔄</button>
    </div>

    <div id="progress-container">
      <div class="progress-text" id="progress-text">Calculando área...</div>
      <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
    </div>

    <div id="map"></div>
  </div>

  <div id="dash-view" class="view-section">
    <div class="dash-header">
      <span>INDICADORES | FERTIRRIGAÇÃO</span>
      <span class="total-area-badge" id="total-area-badge">Total: 0 ha</span>
    </div>

    <div style="display: flex; justify-content: center; align-items: center; margin: 10px 0 20px 0;">
        <div class="hidrorrol-loader" style="margin-bottom: 0;">
            <svg viewBox="0 0 140 100" width="120" height="85">
                <line x1="5" y1="85" x2="135" y2="85" stroke="#334155" stroke-width="3" stroke-linecap="round" />
                <line class="hose-line" x1="15" y1="83" x2="95" y2="83" stroke="#1e293b" stroke-width="4" stroke-linecap="round" />
                <rect x="5" y="70" width="10" height="15" fill="#475569" />
                <circle cx="10" cy="65" r="12" fill="#0f172a" stroke="#cbd5e1" stroke-width="2" />
                <circle cx="10" cy="65" r="4" fill="#cbd5e1" />
                <g class="cart-group">
                    <path d="M 0 85 L 20 45 L 30 85 Z" fill="none" stroke="#94a3b8" stroke-width="3" stroke-linejoin="round" />
                    <circle cx="10" cy="75" r="10" fill="#0f172a" stroke="#cbd5e1" stroke-width="3" />
                    <circle cx="10" cy="75" r="3" fill="#cbd5e1" />
                    <circle cx="30" cy="80" r="5" fill="#0f172a" stroke="#cbd5e1" stroke-width="2" />
                    <line x1="18" y1="48" x2="40" y2="28" stroke="#cbd5e1" stroke-width="5" stroke-linecap="round" />
                    <line x1="35" y1="33" x2="45" y2="23" stroke="#38bdf8" stroke-width="3" stroke-linecap="round" />
                    <path class="spray-stream" d="M 45 23 Q 70 5 95 50" fill="none" stroke="#38bdf8" stroke-width="4" stroke-linecap="round" stroke-dasharray="2 8" />
                    <path class="spray-stream-2" d="M 45 23 Q 65 -5 100 45" fill="none" stroke="#7dd3fc" stroke-width="2" stroke-linecap="round" stroke-dasharray="1 10" />
                    <path class="spray-stream-3" d="M 45 23 Q 80 15 90 60" fill="none" stroke="#0ea5e9" stroke-width="3" stroke-linecap="round" stroke-dasharray="3 7" />
                </g>
            </svg>
        </div>
    </div>
    
    <div class="section-title">Totalização por Unidades (ha)</div>
    <div class="cards-grid" id="grid-unidades"></div>

    <div class="section-title">Status do Projeto - CLEMENTINA (ha)</div>
    <div class="cards-grid" id="grid-proj-cle"></div>

    <div class="section-title">Status do Projeto - QUEIROZ (ha)</div>
    <div class="cards-grid" id="grid-proj-que"></div>
  </div>

  <div class="bottom-nav glass">
    <button class="nav-item active" id="btn-nav-map" onclick="switchView('map')">
      <span class="nav-icon">🗺️</span> Mapa
    </button>
    <button class="nav-item" id="btn-nav-dash" onclick="switchView('dash')">
      <span class="nav-icon">📊</span> Indicadores
    </button>
  </div>

  <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
  
  <script>
    window.appAbortController = new AbortController();
    let currentPos = null;

    function startContinuousGPS() {
        if (!navigator.geolocation) {
            const txt = document.getElementById('gps-accuracy-text');
            if(txt) txt.innerText = "GPS Indisponível no dispositivo";
            return;
        }

        navigator.geolocation.watchPosition(
            (pos) => {
                const lat = pos.coords.latitude;
                const lng = pos.coords.longitude;
                const acc = Math.round(pos.coords.accuracy);
                currentPos = [lng, lat];

                let qual = "Baixa";
                let color = "#ef4444"; 
                if (acc <= 10) { qual = "Excelente"; color = "#22c55e"; } 
                else if (acc <= 25) { qual = "Boa"; color = "#eab308"; } 

                const statusEl = document.getElementById('gps-accuracy-text');
                if (statusEl) {
                    statusEl.innerHTML = `GPS: <span style="color:${color}; font-weight:800">${acc}m (${qual})</span>`;
                }

                if (window.mapLoaded) {
                    if (!window.userMarker) {
                        const el = document.createElement('div');
                        el.style.width = '16px'; el.style.height = '16px';
                        el.style.backgroundColor = '#3b82f6'; el.style.borderRadius = '50%';
                        el.style.border = '3px solid #ffffff'; el.style.boxShadow = '0 0 12px rgba(59, 130, 246, 0.8)';
                        
                        window.userMarker = new maplibregl.Marker({element: el})
                            .setLngLat([lng, lat])
                            .addTo(map);
                    } else {
                        window.userMarker.setLngLat([lng, lat]);
                    }
                }
            },
            (err) => {
                const statusEl = document.getElementById('gps-accuracy-text');
                if (statusEl) statusEl.innerHTML = `<span style="color:#ef4444">GPS: Sem sinal de satélite</span>`;
            },
            { 
                enableHighAccuracy: true, 
                maximumAge: 2000, 
                timeout: 15000 
            }
        );
    }

    function locateUser() {
        if (currentPos) {
            map.flyTo({ center: currentPos, zoom: 17 });
        } else {
            alert("Aguardando os satélites localizarem seu dispositivo...");
        }
    }

    function forceSkipLoader() {
        window.appAbortController.abort();
        const txt = document.querySelector('.loader-text');
        if(txt) txt.innerText = "Iniciando modo offline...";
        
        setTimeout(() => {
            const loaderEl = document.getElementById('loader');
            if(loaderEl) {
                loaderEl.style.opacity = '0'; 
                setTimeout(() => loaderEl.style.display = 'none', 400); 
            }
        }, 500);
    }

    async function fetchSafeData(url) {
        return new Promise(async (resolve) => {
            let finished = false;
            const controller = new AbortController();
            
            const timer = setTimeout(() => {
                if (!finished) controller.abort();
            }, 5000);

            window.appAbortController.signal.addEventListener('abort', () => {
                if (!finished) controller.abort();
            });

            try {
                const res = await fetch(url, { signal: controller.signal });
                clearTimeout(timer);
                finished = true;
                resolve(await res.json());
            } catch (e) {
                try {
                    const cached = await caches.match(url);
                    if (cached) {
                        finished = true;
                        resolve(await cached.json());
                    } else {
                        resolve({ type: "FeatureCollection", features: [] });
                    }
                } catch (errCache) {
                    resolve({ type: "FeatureCollection", features: [] });
                }
            }
        });
    }

    const map = new maplibregl.Map({
        maxZoom: 24, 
        container: 'map',
        style: {
            version: 8,
            glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
            sources: {
                'esri-satellite': {
                    type: 'raster',
                    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
                    tileSize: 256,
                    maxzoom: 17 
                }
            },
            layers: [{
                id: 'satellite',
                type: 'raster',
                source: 'esri-satellite',
                minzoom: 0,
                maxzoom: 24 
            }]
        },
        center: [-50.3, -21.2],
        zoom: 6,
        pitchWithRotate: false, 
        dragRotate: true,       
        touchZoomRotate: true   
    });

    let rawData = null;

    const PALETTE = {
      "STATUS PROJETO": { "A VALIDAR": "#eab308", "PROJETO FEITO": "#166534", "SEM PROJETO OU OPORTUNIDADE": "#ef4444", "TOTAL CLEMENTINA": "#f97316", "TOTAL QUEIROZ": "#3b82f6" },
      "UNIDADE": { "CLEMENTINA": "#f97316", "QUEIROZ": "#3b82f6" }
    };

    function toggleMenu() { document.getElementById('search-box').classList.toggle('collapsed'); }

    function switchView(view) {
      if(view === 'map') {
        document.getElementById('map-view').style.display = 'block';
        document.getElementById('dash-view').style.display = 'none';
        document.getElementById('btn-nav-map').classList.add('active');
        document.getElementById('btn-nav-dash').classList.remove('active');
        map.resize();
      } else {
        document.getElementById('map-view').style.display = 'none';
        document.getElementById('dash-view').style.display = 'block';
        document.getElementById('btn-nav-dash').classList.add('active');
        document.getElementById('btn-nav-map').classList.remove('active');
      }
    }

    function formatNumber(num) {
      return num.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    function resetRotation() {
        map.resetNorthPitch();
    }

    function getBounds(features) {
        const bounds = new maplibregl.LngLatBounds();
        features.forEach(f => {
            if (!f.geometry || !f.geometry.coordinates) return;
            if (f.geometry.type === 'LineString' || f.geometry.type === 'Polygon') {
                f.geometry.coordinates.forEach(c => {
                    if (typeof c[0] === 'number') bounds.extend(c);
                    else c.forEach(p => bounds.extend(p));
                });
            } else if (f.geometry.type === 'MultiLineString' || f.geometry.type === 'MultiPolygon') {
                f.geometry.coordinates.forEach(poly => poly.forEach(c => {
                    if (typeof c[0] === 'number') bounds.extend(c);
                    else c.forEach(p => bounds.extend(p));
                }));
            }
        });
        return bounds;
    }

    startContinuousGPS();

    Promise.all([
      fetchSafeData('./data.geojson'),
      fetchSafeData('./talhoes.geojson'),
      fetchSafeData('./perimetro.geojson'),
      fetchSafeData('./indicadores.json'),
      fetchSafeData('./labels.json'),
      fetchSafeData('./tubulacao.geojson')
    ]).then(([linhasData, talhoesData, perimetroData, indicData, labelsData, tubulacaoData]) => {
        
        rawData = linhasData;
        populateDropdown(rawData);
        buildDashboard(indicData);

        const markersFeatures = [];
        if(linhasData.features) {
            linhasData.features.forEach(f => {
                const lyr = String(f.properties.layer || '');
                if(f.properties.start_point) {
                    markersFeatures.push({
                        type: 'Feature',
                        geometry: { type: 'Point', coordinates: [f.properties.start_point[1], f.properties.start_point[0]] },
                        // PROPRIEDADE BLINDADA COMO POINT_TYPE
                        properties: { point_type: 'start', layer: lyr }
                    });
                }
                if(f.properties.end_point) {
                    markersFeatures.push({
                        type: 'Feature',
                        geometry: { type: 'Point', coordinates: [f.properties.end_point[1], f.properties.end_point[0]] },
                        properties: { point_type: 'end', layer: lyr }
                    });
                }
            });
        }

        let layersInit = false;
        const initMapLayers = () => {
            if (layersInit) return; 
            layersInit = true;
            window.mapLoaded = true;
            
            map.addSource('talhoes', { type: 'geojson', data: talhoesData });
            map.addSource('perimetro', { type: 'geojson', data: perimetroData });
            map.addSource('linhas', { type: 'geojson', data: linhasData });
            map.addSource('labels', { type: 'geojson', data: labelsData });
            map.addSource('tubulacao', { type: 'geojson', data: tubulacaoData });
            map.addSource('markers', { type: 'geojson', data: { type: 'FeatureCollection', features: markersFeatures } });
            
            map.addLayer({
                id: 'talhoes-fill',
                type: 'fill',
                source: 'talhoes',
                paint: { 'fill-color': '#d3d3d3', 'fill-opacity': 0.6 }
            });

            map.addLayer({
                id: 'perimetro-line',
                type: 'line',
                source: 'perimetro',
                paint: { 'line-color': '#000000', 'line-width': 3 }
            });

            map.addLayer({
                id: 'tubulacao-line',
                type: 'line',
                source: 'tubulacao',
                paint: { 'line-color': '#ef4444', 'line-width': 6 }
            });

            map.addLayer({
                id: 'linhas-line',
                type: 'line',
                source: 'linhas',
                paint: { 'line-color': '#000000', 'line-width': 4 }
            });

            map.addLayer({
                id: 'linhas-labels',
                type: 'symbol',
                source: 'labels',
                minzoom: 10,
                layout: {
                    'symbol-placement': 'line',
                    'symbol-spacing': 100,
                    'text-field': ['concat', ['to-string', ['get', 'Metragem_m']], ' m'],
                    'text-size': 13,
                    'text-offset': [0, -0.7],
                    'text-anchor': 'bottom',
                    'text-keep-upright': true,
                    'text-allow-overlap': true,
                    'text-ignore-placement': true
                },
                paint: {
                    'text-color': '#000000',
                    'text-halo-color': '#ffffff',
                    'text-halo-width': 2.5
                }
            });

            // FILTROS BLINDADOS COM A NOVA PROPRIEDADE POINT_TYPE
            map.addLayer({
                id: 'markers-start', type: 'circle', source: 'markers', filter: ['==', ['get', 'point_type'], 'start'],
                paint: { 'circle-radius': 5, 'circle-color': '#22c55e', 'circle-stroke-width': 1.5, 'circle-stroke-color': '#ffffff' },
                minzoom: 14
            });
            map.addLayer({
                id: 'markers-end', type: 'circle', source: 'markers', filter: ['==', ['get', 'point_type'], 'end'],
                paint: { 'circle-radius': 5, 'circle-color': '#ef4444', 'circle-stroke-width': 1.5, 'circle-stroke-color': '#ffffff' },
                minzoom: 14
            });

            applyTheme(); 

            const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: '300px' });

            function bindPopup(layerId, hiddenProps = []) {
                map.on('click', layerId, (e) => {
                    const props = e.features[0].properties;
                    let html = '<div style="font-size:12px; max-height:200px; overflow-y:auto;">';
                    for (let k in props) {
                        if (!hiddenProps.some(hp => hp.toUpperCase() === k.toUpperCase())) {
                            html += `<b style="color:#38bdf8">${k}:</b> ${props[k]}<br/>`;
                        }
                    }
                    html += '</div>';
                    popup.setLngLat(e.lngLat).setHTML(html).addTo(map);
                });
                map.on('mouseenter', layerId, () => map.getCanvas().style.cursor = 'pointer');
                map.on('mouseleave', layerId, () => map.getCanvas().style.cursor = '');
            }

            bindPopup('talhoes-fill', ['CHAVE', 'AREA_CALC', 'ÁREA', 'AREA', 'AREA_HA', 'HECTARES']);
            bindPopup('linhas-line', ['start_point', 'end_point']);

            if (rawData && rawData.features) {
                const initialBounds = getBounds(rawData.features);
                if (!initialBounds.isEmpty()) map.fitBounds(initialBounds, { padding: 40 });
            }

            const loaderEl = document.getElementById('loader');
            if(loaderEl) {
                loaderEl.style.opacity = '0'; 
                setTimeout(() => loaderEl.style.display = 'none', 500); 
            }
        };

        if (map.loaded() || map.isStyleLoaded()) {
            initMapLayers();
        } else {
            map.once('load', initMapLayers);
            setTimeout(initMapLayers, 3500); 
        }

    }).catch(err => { 
        const txt = document.querySelector('.loader-text');
        if (txt) txt.innerText = "Erro ao carregar dados do app offline."; 
        console.error(err);
    });

    function updateLegend(theme) {
      const legendBox = document.getElementById('map-legend');
      if (theme === 'default') {
        legendBox.style.display = 'none';
        return;
      }
      
      legendBox.style.display = 'flex';
      let html = `<div class="legend-title">Legenda: ${theme}</div>`;
      
      const colors = PALETTE[theme];
      for (let key in colors) {
        if (!key.startsWith("TOTAL")) {
            html += `<div class="legend-item"><div class="legend-color" style="background: ${colors[key]}"></div>${key}</div>`;
        }
      }
      legendBox.innerHTML = html;
    }

    function applyTheme() {
      const attrTheme = document.getElementById('themeSelect').value;
      if (attrTheme === 'default') {
          map.setPaintProperty('talhoes-fill', 'fill-color', '#d3d3d3');
          map.setPaintProperty('talhoes-fill', 'fill-opacity', 0.6);
          updateLegend('default');
          return;
      }

      const colors = PALETTE[attrTheme];
      const matchExprColor = ['match', ['upcase', ['to-string', ['get', attrTheme]]]];
      const matchExprOpacity = ['match', ['upcase', ['to-string', ['get', attrTheme]]]];

      for (let key in colors) {
          if (!key.startsWith("TOTAL")) {
              matchExprColor.push(key, colors[key]);
              matchExprOpacity.push(key, 0.7);
          }
      }
      matchExprColor.push('#cbd5e1'); 
      matchExprOpacity.push(0.1);     

      map.setPaintProperty('talhoes-fill', 'fill-color', matchExprColor);
      map.setPaintProperty('talhoes-fill', 'fill-opacity', matchExprOpacity);
      updateLegend(attrTheme);
    }

    function buildDashboard(data) {
      if (!data) return;
      document.getElementById('total-area-badge').innerText = `Total: ${formatNumber(data.area_total_ha)} ha`;

      const createCards = (arr, elementId, colorPalette) => {
        const grid = document.getElementById(elementId);
        grid.innerHTML = '';
        arr.forEach(item => {
          const card = document.createElement('div');
          card.className = 'card';
          const valUpper = item.label.toUpperCase();
          const themeColor = colorPalette[valUpper] || '#38bdf8';
          card.style.borderLeft = `4px solid ${themeColor}`;
          card.innerHTML = `<div class="card-val">${formatNumber(item.area_ha)} ha</div><div class="card-lbl">${item.label}</div>`;
          grid.appendChild(card);
        });
      };

      createCards(data.unidades, 'grid-unidades', PALETTE["UNIDADE"]);
      createCards(data.projeto_clementina, 'grid-proj-cle', PALETTE["STATUS PROJETO"]);
      createCards(data.projeto_queiroz, 'grid-proj-que', PALETTE["STATUS PROJETO"]);
    }

    function updateLayersVisibility() {
        const showTalhoes = document.getElementById('toggleTalhoes').checked ? 'visible' : 'none';
        const showPerimetro = document.getElementById('togglePerimetro').checked ? 'visible' : 'none';
        const showLinhas = document.getElementById('toggleLinhas').checked ? 'visible' : 'none';
        const showRotulos = document.getElementById('toggleRotulos').checked ? 'visible' : 'none';
        const showTubulacao = document.getElementById('toggleTubulacao').checked ? 'visible' : 'none';
        
        if (map.getLayer('talhoes-fill')) map.setLayoutProperty('talhoes-fill', 'visibility', showTalhoes);
        if (map.getLayer('perimetro-line')) map.setLayoutProperty('perimetro-line', 'visibility', showPerimetro);
        
        if (map.getLayer('linhas-line')) map.setLayoutProperty('linhas-line', 'visibility', showLinhas);
        if (map.getLayer('linhas-labels')) map.setLayoutProperty('linhas-labels', 'visibility', showRotulos);
        if (map.getLayer('markers-start')) map.setLayoutProperty('markers-start', 'visibility', showLinhas);
        if (map.getLayer('markers-end')) map.setLayoutProperty('markers-end', 'visibility', showLinhas);
        
        if (map.getLayer('tubulacao-line')) map.setLayoutProperty('tubulacao-line', 'visibility', showTubulacao);
    }

    function populateDropdown(data) {
      if (!data || !data.features) return;
      const select = document.getElementById('layerSelect');
      const layerMap = new Map();
      
      data.features.forEach(f => { 
          if (f.properties && f.properties.layer) {
              let lbl = String(f.properties.layer);
              if (f.properties.fazenda) {
                  lbl += " - " + String(f.properties.fazenda).toUpperCase();
              }
              if (!layerMap.has(f.properties.layer)) {
                  layerMap.set(f.properties.layer, lbl);
              }
          } 
      });
      
      Array.from(layerMap.keys()).sort((a,b) => String(a).localeCompare(String(b), undefined, {numeric: true})).forEach(lyr => {
        const opt = document.createElement('option'); 
        opt.value = lyr; 
        opt.textContent = layerMap.get(lyr); 
        select.appendChild(opt);
      });
    }

    function filterMap() {
      const val = document.getElementById('layerSelect').value;
      if (!val) {
          map.setFilter('linhas-line', null);
          map.setFilter('linhas-labels', null);
          map.setFilter('markers-start', ['==', ['get', 'point_type'], 'start']);
          map.setFilter('markers-end', ['==', ['get', 'point_type'], 'end']);
          map.setFilter('talhoes-fill', null);
          map.setFilter('perimetro-line', null);
          if (map.getLayer('tubulacao-line')) map.setFilter('tubulacao-line', null);
          resetView();
          return;
      }
      
      const filterVal = ['==', ['to-string', ['get', 'layer']], String(val)];
      
      map.setFilter('linhas-line', filterVal);
      map.setFilter('linhas-labels', filterVal);
      map.setFilter('markers-start', ['all', ['==', ['get', 'point_type'], 'start'], filterVal]);
      map.setFilter('markers-end', ['all', ['==', ['get', 'point_type'], 'end'], filterVal]);

      const fazendaCode = val.substring(0, 6);
      const filterFazenda = ['==', ['slice', ['to-string', ['get', 'FAZENDA']], 0, fazendaCode.length], fazendaCode];
      const filterTubLayer = ['==', ['slice', ['to-string', ['get', 'layer']], 0, fazendaCode.length], fazendaCode];
      
      map.setFilter('talhoes-fill', filterFazenda);
      map.setFilter('perimetro-line', filterFazenda);
      
      if (map.getLayer('tubulacao-line')) {
          map.setFilter('tubulacao-line', filterTubLayer);
      }

      const filteredFeatures = rawData.features.filter(f => String(f.properties.layer) === String(val));
      const bounds = getBounds(filteredFeatures);
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 40, maxZoom: 17 });
    }

    function resetView() {
      document.getElementById('layerSelect').value = '';
      if(rawData && rawData.features){
          const bounds = getBounds(rawData.features);
          if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 30 });
      }
    }

    function locateUser() {
      if (!navigator.geolocation) return alert("Sua localização GPS não está disponível.");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude, lng = pos.coords.longitude;
          
          if (window.userMarker) window.userMarker.remove();
          
          const el = document.createElement('div');
          el.style.width = '16px'; el.style.height = '16px';
          el.style.backgroundColor = '#3b82f6'; el.style.borderRadius = '50%';
          el.style.border = '3px solid #ffffff'; el.style.boxShadow = '0 0 10px rgba(0,0,0,0.5)';
          
          window.userMarker = new maplibregl.Marker({element: el})
              .setLngLat([lng, lat])
              .setPopup(new maplibregl.Popup({offset: 15}).setHTML("<b style='color:#0f172a'>Você está aqui</b>"))
              .addTo(map);
              
          map.flyTo({ center: [lng, lat], zoom: 17 });
        },
        (err) => alert("Erro de GPS: " + err.message),
        { enableHighAccuracy: true }
      );
    }

    function latLngToTile(lat, lng, z) {
        const x = Math.floor((lng + 180) / 360 * Math.pow(2, z));
        const y = Math.floor((1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * Math.pow(2, z));
        return {x, y};
    }

    async function downloadOfflineMap() {
      if (!rawData || !rawData.features) return alert("Aguarde o carregamento inicial dos dados.");
      
      const val = document.getElementById('layerSelect').value;
      const featuresToDownload = val 
            ? rawData.features.filter(f => String(f.properties.layer) === String(val)) 
            : rawData.features;

      const minZ = 12, maxZ = 16, tilesSet = new Set();
      document.getElementById('progress-container').style.display = 'block';
      const progText = document.getElementById('progress-text');
      progText.innerText = "Mapeando regiões para salvamento offline...";
      
      await new Promise(r => setTimeout(r, 50)); 

      featuresToDownload.forEach(feature => {
        const coordsList = feature.geometry.type === 'MultiLineString' ? feature.geometry.coordinates : [feature.geometry.coordinates];
        coordsList.forEach(line => {
          line.forEach(coord => {
            const lat = coord[1]; 
            const lng = coord[0];
            for (let z = minZ; z <= maxZ; z++) {
              const p = latLngToTile(lat, lng, z);
              for(let dx = -1; dx <= 1; dx++) {
                for(let dy = -1; dy <= 1; dy++) {
                  tilesSet.add(`${z}/${p.y + dy}/${p.x + dx}`);
                }
              }
            }
          });
        });
      });

      const urls = Array.from(tilesSet).map(t => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${t}`);
      const totalTiles = urls.length;
      const estimatedMB = ((totalTiles * 25) / 1024).toFixed(2);

      if(!confirm(`Confirmação de Download Offline:\nTotal de Blocos: ${totalTiles}\nTamanho Estimado: ${estimatedMB} MB.\n\nDeseja iniciar?`)) {
          document.getElementById('progress-container').style.display = 'none';
          return;
      }

      toggleMenu(); 
      const progFill = document.getElementById('progress-fill');

      try {
        const cache = await caches.open('ferti-tiles-v1');
        let downloaded = 0, chunk = 20; 
        for (let i = 0; i < urls.length; i += chunk) {
          const lote = urls.slice(i, i + chunk);
          await Promise.all(lote.map(async (url) => {
            try {
              const existe = await caches.match(url);
              if (!existe) {
                const req = await fetch(url, { mode: 'cors' });
                if (req.ok) await cache.put(url, req);
              }
            } catch(e) {}
            downloaded++;
          }));
          const p = Math.round((downloaded / totalTiles) * 100);
          const currentMB = ((downloaded * 25) / 1024).toFixed(2);
          progFill.style.width = p + '%';
          progText.innerText = `Baixando: ${currentMB} MB de ${estimatedMB} MB (${p}%)`;
        }
        alert("Mapa salvo offline com sucesso!");
      } catch (err) {
        alert("Ocorreu uma falha durante o salvamento: " + err.message);
      }
      setTimeout(() => { document.getElementById('progress-container').style.display = 'none'; }, 2000);
    }

    async function clearAndRefresh() {
      if(!confirm("Deseja apagar os dados offline e atualizar o aplicativo?")) return;
      try {
        const keys = await caches.keys();
        await Promise.all(keys.map(k => caches.delete(k)));
        if (navigator.serviceWorker) {
          const regs = await navigator.serviceWorker.getRegistrations();
          for (let r of regs) await r.unregister();
        }
        alert("Aplicativo atualizado com sucesso.");
        window.location.reload(true);
      } catch(e) { alert("Erro ao atualizar: " + e.message); }
    }

    if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js');
  </script>
</body>
</html>
"""

html_content = html_content.replace("{{DATA_ATUALIZACAO}}", DATA_ATUALIZACAO)

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html_content.strip())

print("✅ Todos os arquivos salvos. Filtro blindado aplicado com sucesso!")
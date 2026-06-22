import requests
import pdfplumber
import re
import io
import json
import time
from bs4 import BeautifulSoup
try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False

BASE = 'https://snifa.sma.gob.cl'

san_cases = [
    {'san_id': 4064, 'expediente': 'D-065-2025', 'uf_id': '22692', 'nombre': 'Aridos Fe Blanca San Carlos', 'lat_orig': -36.5179, 'lon_orig': -71.9283},
    {'san_id': 2784, 'expediente': 'D-009-2022', 'uf_id': '17274', 'nombre': 'ARIDOS VICAT', 'lat_orig': -40.3387, 'lon_orig': -72.9531},
    {'san_id': 2722, 'expediente': 'D-222-2021', 'uf_id': '6823',  'nombre': 'EXTRACCION ARIDOS SECTOR PUENTE MARAMBIO', 'lat_orig': -33.7113, 'lon_orig': -71.2033},
    {'san_id': 2632, 'expediente': 'D-141-2021', 'uf_id': '6808',  'nombre': 'EXTRACCION ARIDOS SOPRAMAT', 'lat_orig': -36.8822, 'lon_orig': -72.1985},
    {'san_id': 2292, 'expediente': 'D-106-2020', 'uf_id': '14805', 'nombre': 'ARIDOS PUTUE BAJO', 'lat_orig': -39.2820, 'lon_orig': -72.2308},
    {'san_id': 2012, 'expediente': 'D-129-2019', 'uf_id': '6837',  'nombre': 'EXTRACCION ARIDOS RIO CAUTIN', 'lat_orig': -38.5824, 'lon_orig': -72.4401},
    {'san_id': 2008, 'expediente': 'D-125-2019', 'uf_id': '6801',  'nombre': 'EXTRACCION ARIDOS ABRATEC', 'lat_orig': -36.8199, 'lon_orig': -72.4062},
    {'san_id': 1765, 'expediente': 'D-074-2018', 'uf_id': '14057', 'nombre': 'PLANTA DE ARIDOS EL MAITEN', 'lat_orig': -36.8221, 'lon_orig': -72.4131},
    {'san_id': 1714, 'expediente': 'D-036-2018', 'uf_id': '13128', 'nombre': 'PLANTA DE ARIDOS SAN PEDRO', 'lat_orig': -22.6640, 'lon_orig': -68.4833},
]

def utm_to_wgs84(este, norte, huso, hemisphere='S'):
    if not HAS_PYPROJ:
        return None, None
    try:
        epsg = 32700 + huso if hemisphere.upper() == 'S' else 32600 + huso
        transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(este, norte)
        return round(lat, 6), round(lon, 6)
    except Exception as e:
        return None, None

def extract_utm(text):
    results = []
    # Format: NUMBER m E NUMBER m N
    p1 = r'(\d{5,7})\s*m?\s*E[,;\s]+(\d{7,8})\s*m?\s*N'
    # Format: E=NUMBER N=NUMBER
    p2 = r'E\s*[:=]\s*(\d{5,7})[,;\s]+N\s*[:=]\s*(\d{7,8})'
    # Format: Este: NUMBER Norte: NUMBER
    p3 = r'[Ee]ste[:\s]+(\d{5,7})[,;\s]+[Nn]orte[:\s]+(\d{7,8})'
    # Format: Norte: NUMBER Este: NUMBER
    p4 = r'[Nn]orte[:\s]+(\d{7,8})[,;\s]+[Ee]ste[:\s]+(\d{5,7})'
    # Format: coordenadas NUMBER E NUMBER N
    p5 = r'coordenadas?\s+(\d{5,7})\s+m?\s*E\s+(\d{7,8})\s+m?\s*N'
    # Format: Este NUMBER Norte NUMBER (no colon)
    p6 = r'[Ee]ste\s+(\d{5,7})[,;\s]+[Nn]orte\s+(\d{7,8})'

    all_patterns = [(p1,'mE mN'), (p2,'E=/N='), (p3,'Este:/Norte:'), (p4,'Norte:/Este:'), (p5,'coordenadas mE mN'), (p6,'Este Norte')]

    seen = set()
    for pat, desc in all_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            g = m.groups()
            n1, n2 = int(g[0]), int(g[1])
            este, norte = None, None
            # Identify which is Este (5-7 digits, 150000-900000) and Norte (7-8 digits, 5000000-9800000)
            if 150000 <= n1 <= 900000 and 5000000 <= n2 <= 9800000:
                este, norte = n1, n2
            elif 150000 <= n2 <= 900000 and 5000000 <= n1 <= 9800000:
                este, norte = n2, n1
            if este and norte:
                key = (este, norte)
                if key in seen:
                    continue
                seen.add(key)
                ctx_start = max(0, m.start()-150)
                ctx = text[ctx_start:m.end()+300]
                # Extract huso/zone
                huso = None
                huso_m = re.search(r'[Hh]uso\s*(\d{1,2})|WGS\s*(\d{2})[HS]?|[Zz]ona\s*(\d{1,2})|(\d{2})\s*[HS]\b', ctx)
                if huso_m:
                    huso_val = next((x for x in huso_m.groups() if x and x.isdigit()), None)
                    if huso_val:
                        huso = int(huso_val)
                results.append({'este': este, 'norte': norte, 'huso': huso, 'desc': desc, 'context': ctx.strip()})
    return results

def download_pdf(session, url, referer):
    try:
        session.headers['Referer'] = referer
        r = session.get(url, timeout=60, allow_redirects=True)
        ct = r.headers.get('Content-Type', '')
        if r.status_code != 200 or len(r.content) < 500:
            return '', []
        if 'pdf' not in ct.lower() and not r.content[:4] == b'%PDF':
            return '', []
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = '\n'.join((p.extract_text() or '') for p in pdf.pages[:50])
        return text, extract_utm(text)
    except Exception as e:
        return '', []

def get_docs(session, san_id):
    url = f'{BASE}/Sancionatorio/Ficha/{san_id}'
    r = session.get(url, timeout=30)
    soup = BeautifulSoup(r.content, 'html.parser')
    docs = []
    for row in soup.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) >= 4:
            a = cells[-1].find('a', href=True)
            if a and '/General/Descargar/' in a['href']:
                docs.append({
                    'nombre': cells[1].get_text(strip=True),
                    'tipo': cells[2].get_text(strip=True),
                    'url': BASE + a['href'],
                    'referer': url
                })
    return docs

def priority(d):
    t = (d['tipo'] + d['nombre']).lower()
    if 'formulaci' in t or 'cargo' in t: return 0
    if 'resoluc' in t and 'sancion' in t: return 1
    if 'antecedente' in t: return 2
    if 'dictamen' in t: return 3
    if 'resoluc' in t: return 4
    return 9

results_all = {}

for case in san_cases:
    sid = case['san_id']
    print(f"\n{'='*60}")
    print(f"{case['expediente']}: {case['nombre']} (san={sid})")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'es-CL,es;q=0.9',
    })
    session.get(BASE, timeout=20)

    docs = get_docs(session, sid)
    print(f"  {len(docs)} docs found")

    docs_sorted = sorted(docs, key=priority)
    found_coords = []

    for d in docs_sorted[:8]:
        time.sleep(0.5)
        text, coords = download_pdf(session, d['url'], d['referer'])
        kw = any(k in text.lower() for k in ['coordenada', 'utm', 'huso', 'wgs']) if text else False
        est_norte = any(k in text.lower() for k in ['este', 'norte']) if text else False
        print(f"  [{d['tipo'][:20]}] {d['nombre'][:35]}: {len(text)}c kw={'Y' if kw else 'n'} en={'Y' if est_norte else 'n'} coords={len(coords)}")
        if coords:
            for c in coords:
                print(f"    UTM: E={c['este']} N={c['norte']} huso={c['huso']}")
                print(f"    ctx: {c['context'][:200]}")
            found_coords.extend(coords)
        if found_coords:
            break

    # Convert UTM coords to WGS84
    converted = []
    for c in found_coords:
        huso = c.get('huso') or 19  # Default huso 19 for south-central Chile
        lat, lon = utm_to_wgs84(c['este'], c['norte'], huso, 'S')
        converted.append({**c, 'lat_utm': lat, 'lon_utm': lon, 'huso_used': huso})

    results_all[sid] = {
        'case': case,
        'coords_from_pdf': converted,
        'coords_used': converted[0] if converted else None
    }

# Save
with open('aridos_pdf_coords_v2.json', 'w', encoding='utf-8') as f:
    json.dump(results_all, f, ensure_ascii=False, indent=2, default=str)

print("\n\n" + "="*60)
print("SUMMARY — UTM coordinates from PDFs:")
for sid, res in results_all.items():
    c = res['coords_used']
    if c:
        print(f"  {res['case']['expediente']}: E={c['este']} N={c['norte']} huso={c['huso_used']} -> lat={c.get('lat_utm')} lon={c.get('lon_utm')}")
    else:
        lat0, lon0 = res['case']['lat_orig'], res['case']['lon_orig']
        print(f"  {res['case']['expediente']}: NO UTM in PDF (using original UF coords: {lat0},{lon0})")

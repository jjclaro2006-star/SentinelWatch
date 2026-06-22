import requests
import pdfplumber
import re
import io
import json
from bs4 import BeautifulSoup

BASE = 'https://snifa.sma.gob.cl'
HDRS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

san_cases = [
    {'san_id': 4064, 'expediente': 'D-065-2025', 'nombre': 'Aridos Fe Blanca San Carlos'},
    {'san_id': 2784, 'expediente': 'D-009-2022', 'nombre': 'ARIDOS VICAT'},
    {'san_id': 2722, 'expediente': 'D-222-2021', 'nombre': 'EXTRACCION ARIDOS SECTOR PUENTE MARAMBIO'},
    {'san_id': 2632, 'expediente': 'D-141-2021', 'nombre': 'EXTRACCION ARIDOS SOPRAMAT'},
    {'san_id': 2292, 'expediente': 'D-106-2020', 'nombre': 'ARIDOS PUTUE BAJO'},
    {'san_id': 2012, 'expediente': 'D-129-2019', 'nombre': 'EXTRACCION ARIDOS RIO CAUTIN'},
    {'san_id': 2008, 'expediente': 'D-125-2019', 'nombre': 'EXTRACCION ARIDOS ABRATEC'},
    {'san_id': 1765, 'expediente': 'D-074-2018', 'nombre': 'PLANTA DE ARIDOS EL MAITEN'},
    {'san_id': 1714, 'expediente': 'D-036-2018', 'nombre': 'PLANTA DE ARIDOS SAN PEDRO'},
]

def get_docs(san_id):
    r = requests.get(f'{BASE}/Sancionatorio/Ficha/{san_id}', timeout=30, headers=HDRS)
    html = r.content.decode('utf-8', errors='replace')
    soup = BeautifulSoup(html, 'html.parser')
    docs = []
    for row in soup.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) >= 4:
            link_cell = cells[-1]
            a = link_cell.find('a', href=True)
            if a and '/General/Descargar/' in a['href']:
                tipo = cells[2].get_text(strip=True) if len(cells) > 2 else ''
                nombre = cells[1].get_text(strip=True) if len(cells) > 1 else ''
                docs.append({'nombre': nombre, 'tipo': tipo, 'href': a['href'], 'url': BASE + a['href']})
    hechos = []
    # Get hechos text from the page
    main_text = soup.get_text(' ', strip=True)
    return docs, main_text

def extract_utm(text):
    results = []
    patterns = [
        (r'[Ee]ste[:\s]+(\d{6,7})[,;\s]+[Nn]orte[:\s]+(\d{6,8})', 'Este/Norte'),
        (r'[Nn]orte[:\s]+(\d{6,8})[,;\s]+[Ee]ste[:\s]+(\d{6,7})', 'Norte/Este'),
        (r'E\s*=\s*(\d{6,7})[,;\s]+N\s*=\s*(\d{6,8})', 'E=/N='),
        (r'(\d{6,7})\s*m?[Ee][,;\s]+(\d{6,8})\s*m?[Nn]', 'mE mN'),
        (r'[Cc]oordenadas?[^0-9]*(\d{6,7})[,;\s]+(\d{6,8})', 'Coordenadas'),
        (r'UTM[^0-9]*(\d{6,7})[,;\s]+(\d{6,8})', 'UTM'),
        (r'(\d{6,7})\s*[,;]\s*(\d{6,8})', 'plain pair'),
    ]
    for pattern, desc in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            g = m.groups()
            n1, n2 = int(g[0]), int(g[1])
            este, norte = None, None
            if 200000 <= n1 <= 800000 and 5000000 <= n2 <= 9500000:
                este, norte = n1, n2
            elif 200000 <= n2 <= 800000 and 5000000 <= n1 <= 9500000:
                este, norte = n2, n1
            if este and norte:
                ctx_start = max(0, m.start()-100)
                ctx = text[ctx_start:m.end()+300]
                huso_m = re.search(r'[Hh]uso\s*(\d{1,2})|[Zz]ona\s*(\d{1,2})|(\d{2})[Hh]', ctx)
                huso = None
                if huso_m:
                    huso_val = next((x for x in huso_m.groups() if x), None)
                    if huso_val:
                        huso = int(huso_val)
                results.append({'este': este, 'norte': norte, 'huso': huso, 'desc': desc, 'context': ctx[:300]})
    # Deduplicate
    seen = set()
    deduped = []
    for r in results:
        key = (r['este'], r['norte'])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped

def parse_pdf(url):
    try:
        r = requests.get(url, timeout=60, headers=HDRS, allow_redirects=True)
        ct = r.headers.get('Content-Type', '')
        if 'pdf' not in ct.lower() and len(r.content) < 2000:
            return '', []
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = '\n'.join((p.extract_text() or '') for p in pdf.pages[:40])
        return text, extract_utm(text)
    except Exception as e:
        return '', []

all_results = {}

for case in san_cases:
    sid = case['san_id']
    print(f"\n{'='*60}")
    print(f"CASE {case['expediente']}: {case['nombre']} (san={sid})")

    docs, page_text = get_docs(sid)
    print(f"  Docs: {len(docs)}")
    for d in docs:
        print(f"    [{d['tipo'][:30]}] {d['nombre'][:40]}")

    # Parse priority docs
    found_coords = []
    parsed = []

    # Sort docs by priority
    def priority(d):
        t = (d['tipo'] + d['nombre']).lower()
        if 'formulaci' in t or 'cargo' in t: return 0
        if 'resoluc' in t and 'sancion' in t: return 1
        if 'resoluc' in t: return 2
        if 'dictamen' in t: return 3
        return 9

    docs_sorted = sorted(docs, key=priority)

    for d in docs_sorted[:6]:
        text, coords = parse_pdf(d['url'])
        has_kw = any(kw in text.lower() for kw in ['utm', 'este', 'norte', 'coordenada', 'huso'])
        print(f"  >> {d['nombre'][:40]}: {len(text)} chars, kw={'YES' if has_kw else 'no'}, coords={len(coords)}")
        if coords:
            for c in coords:
                print(f"     UTM: E={c['este']} N={c['norte']} huso={c['huso']}")
                print(f"     ctx: {c['context'][:150]}")
        if coords:
            found_coords.extend(coords)
            parsed.append({'doc': d['nombre'], 'tipo': d['tipo'], 'coords': coords})
        if found_coords:
            break  # stop after finding coords

    all_results[sid] = {
        'case': case,
        'docs_count': len(docs),
        'coords_found': found_coords,
        'parsed': parsed
    }

with open('aridos_pdf_coords.json', 'w', encoding='utf-8') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

print("\n\n" + "="*60)
print("FINAL SUMMARY:")
for sid, res in all_results.items():
    coords = res['coords_found']
    status = f"{len(coords)} UTM coords" if coords else "NO COORDS FOUND"
    print(f"  {res['case']['expediente']}: {status}")
    for c in coords[:3]:
        print(f"    E={c['este']} N={c['norte']} huso={c['huso']}")

"""Genera el one-pager de SentinelWatch directamente en PDF con ReportLab."""
from pathlib import Path
from reportlab.lib.pagesizes import landscape, A4

ROOT = Path(__file__).resolve().parent.parent
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

W, H = landscape(A4)   # 297 x 210 mm

# ── Paleta ────────────────────────────────────────────────────────────────────
DARK   = colors.HexColor("#0D1B2A")
MGRAY  = colors.HexColor("#1C2E3E")
GREEN  = colors.HexColor("#2ECC71")
ACCENT = colors.HexColor("#F39C12")
WHITE  = colors.white
LGRAY  = colors.HexColor("#CCD6DD")

OUT = str(ROOT / "outputs" / "sentinelwatch_onepager.pdf")
c = canvas.Canvas(OUT, pagesize=(W, H))

def rrect(x, y, w, h, fill):
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.rect(x, y, w, h, fill=1, stroke=0)

def text(x, y, txt, size, color, bold=False, italic=False):
    c.setFillColor(color)
    if bold and italic:
        c.setFont("Helvetica-BoldOblique", size)
    elif bold:
        c.setFont("Helvetica-Bold", size)
    elif italic:
        c.setFont("Helvetica-Oblique", size)
    else:
        c.setFont("Helvetica", size)
    c.drawString(x, y, txt)

def text_right(x, y, txt, size, color, bold=False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawRightString(x, y, txt)

def wrap_text(x, y, txt, size, color, max_width, line_height, bold=False, italic=False):
    if bold and italic:
        c.setFont("Helvetica-BoldOblique", size)
    elif bold:
        c.setFont("Helvetica-Bold", size)
    elif italic:
        c.setFont("Helvetica-Oblique", size)
    else:
        c.setFont("Helvetica", size)
    c.setFillColor(color)
    words = txt.split()
    line = ""
    cy = y
    for word in words:
        test = (line + " " + word).strip()
        if c.stringWidth(test, c._fontname, size) <= max_width:
            line = test
        else:
            c.drawString(x, cy, line)
            cy -= line_height
            line = word
    if line:
        c.drawString(x, cy, line)
    return cy - line_height

# ── Fondo ─────────────────────────────────────────────────────────────────────
rrect(0, 0, W, H, DARK)

# ── Sidebar ───────────────────────────────────────────────────────────────────
SB = 8.2 * cm
rrect(0, 0, SB, H, MGRAY)
rrect(0, H - 2*mm, SB, 2*mm, GREEN)

# Nombre
text(5*mm, H - 12*mm, "SentinelWatch", 18, GREEN, bold=True)
text(5*mm, H - 17*mm, "Detección satelital de minería", 6.5, LGRAY, italic=True)
text(5*mm, H - 20.5*mm, "ilegal en la Amazonía", 6.5, LGRAY, italic=True)
rrect(5*mm, H - 23*mm, SB - 10*mm, 0.8*mm, GREEN)

# Métricas
metrics = [
    ("77.4 %",  "tasa de detección"),
    ("",        "validación independiente"),
    ("24 / 31", "dragas detectadas"),
    ("",        "vs ACCA/Mongabay"),
    ("286 ha",  "área afectada detectada"),
    ("",        "Río Nanay, Perú"),
    ("5 capas", "verificación legal"),
    ("",        "áreas protegidas WDPA"),
]
my = H - 30*mm
for val, lbl in metrics:
    if val:
        text(5*mm, my, val, 16, ACCENT, bold=True)
        my -= 5.5*mm
    else:
        text(5*mm, my, lbl, 6.5, LGRAY)
        my -= 7*mm

# Modelo
rrect(5*mm, my - 1*mm, SB - 10*mm, 0.6*mm, ACCENT)
my -= 5*mm
text(5*mm, my, "Modelo Gaia v0.5.4", 7.5, ACCENT, bold=True)
my -= 5*mm
for line in ["ViT-S/16 (SSL4EO-S12)", "12 bandas Sentinel-2",
             "Fine-tuning supervisado", "Threshold calibrado en campo"]:
    text(5*mm, my, line, 6.5, LGRAY)
    my -= 4.5*mm

# Stack
my = 7*mm
text(5*mm, my, "GEE · PyTorch · FastAPI · GeoJSON", 5.5, LGRAY, italic=True)

# ── Área principal ────────────────────────────────────────────────────────────
MX = SB + 7*mm
MW = W - MX - 7*mm

# Título
text(MX, H - 11*mm, "Vigilancia automatizada de la selva", 15, WHITE, bold=True)
text(MX, H - 15.5*mm, "en tiempo real", 15, WHITE, bold=True)
rrect(MX, H - 17.5*mm, 5.5*cm, 1*mm, GREEN)

# Descripción
desc = ("SentinelWatch compara imágenes Sentinel-1/2 entre períodos de referencia y análisis, "
        "detecta pérdida de vegetación (NDVI) y clasifica cada alerta con un modelo de "
        "deep learning (Gaia) entrenado sobre datos reales de campo.")
wrap_text(MX, H - 21*mm, desc, 7.5, LGRAY, MW, 4*mm)

# ── Pipeline ──────────────────────────────────────────────────────────────────
rrect(MX, H - 38*mm, MW, 0.5*mm, MGRAY)
text(MX, H - 42*mm, "PIPELINE DE DETECCIÓN", 6.5, LGRAY, bold=True)

pipeline = [
    ("01  Adquisición", "Google Earth Engine descarga mosaicos S1/S2 del período de referencia y análisis para la AOI."),
    ("02  NDVI & detección", "Compara índices de vegetación. Píxeles con caída ≥ umbral se vectorizan como alertas."),
    ("03  Clasificación IA", "Gaia v0.5.4 (ViT-S/16) clasifica cada chip: minería ilegal, agricultura o deforestación."),
    ("04  Verificación legal", "Cada alerta se cruza con 5 capas: WDPA, ANP, territorios indígenas y reservas forestales."),
]
cw = MW / 4 - 3*mm
cx = MX
for title, body in pipeline:
    rrect(cx, H - 46*mm, cw, 1.2*mm, ACCENT)
    text(cx, H - 50.5*mm, title, 7, WHITE, bold=True)
    wrap_text(cx, H - 55*mm, body, 6.5, LGRAY, cw, 3.8*mm)
    cx += cw + 4*mm

# ── Validación ────────────────────────────────────────────────────────────────
rrect(MX, H - 85*mm, MW, 1*mm, GREEN)
text(MX, H - 89.5*mm, "VALIDACIÓN INDEPENDIENTE — RÍO NANAY, LORETO, PERÚ (JUNIO 2026)", 6.5, GREEN, bold=True)

val = ("SentinelWatch detectó de forma independiente 24 de 31 dragas documentadas por ACCA/Mongabay "
       "en julio 2024 (77.4%) sin acceso previo a los datos de referencia. Las 7 dragas no detectadas "
       "operan sobre espejo de agua; mejora planificada: índice MNDWI. Período: jun-ago 2023 vs jun-ago 2024.")
wrap_text(MX, H - 94*mm, val, 7.5, LGRAY, MW, 4*mm)

# ── Regiones / API ────────────────────────────────────────────────────────────
rrect(MX, H - 116*mm, MW, 0.5*mm, MGRAY)

col2w = MW / 2 - 3*mm
text(MX, H - 120.5*mm, "REGIONES ACTIVAS", 6.5, LGRAY, bold=True)
for line in ["Perú (Loreto, Madre de Dios)", "Bolivia (Pando, Beni)",
             "Colombia (Amazonas)  ·  Brasil (Acre)"]:
    text(MX, H - (126 + (["Perú (Loreto, Madre de Dios)", "Bolivia (Pando, Beni)",
             "Colombia (Amazonas)  ·  Brasil (Acre)"].index(line)) * 4.5)*mm, line, 7.5, WHITE)

text(MX + col2w + 6*mm, H - 120.5*mm, "SALIDA & API", 6.5, LGRAY, bold=True)
for line in ["GeoJSON geo-referenciado · FastAPI REST",
             "Mapa web interactivo (index.html)",
             "Alerta: coords, confianza, estatus legal"]:
    text(MX + col2w + 6*mm, H - (126 + (["GeoJSON geo-referenciado · FastAPI REST",
             "Mapa web interactivo (index.html)",
             "Alerta: coords, confianza, estatus legal"].index(line)) * 4.5)*mm, line, 7.5, WHITE)

# ── Footer ────────────────────────────────────────────────────────────────────
rrect(0, 0, W, 6*mm, MGRAY)
text(4*mm, 2*mm, "SentinelWatch © 2026 — Sistema de monitoreo satelital de la Amazonía", 5.5, LGRAY)
text_right(W - 4*mm, 2*mm, "sentinel-1 · sentinel-2 · google earth engine · pytorch · ssl4eo", 5.5, LGRAY)

c.save()
print(f"Guardado: {OUT}")

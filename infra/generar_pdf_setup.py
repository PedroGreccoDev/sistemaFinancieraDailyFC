"""Genera el PDF con los pasos de configuración de WhatsApp Cloud API."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem,
)

AZUL = colors.HexColor("#1d4ed8")
GRIS = colors.HexColor("#374151")
VERDE = colors.HexColor("#047857")
ROJO = colors.HexColor("#b91c1c")
GRIS_CLARO = colors.HexColor("#f3f4f6")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=AZUL, fontSize=20, spaceAfter=4)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], textColor=GRIS, fontSize=10, spaceAfter=12)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=GRIS, fontSize=13, spaceBefore=14, spaceAfter=6)
BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontSize=10.5, leading=15, spaceAfter=4)
STEP = ParagraphStyle("STEP", parent=BODY, leftIndent=4)
CODE = ParagraphStyle("CODE", parent=styles["Code"], fontSize=9, textColor=colors.HexColor("#111827"),
                      backColor=GRIS_CLARO, borderPadding=4, leading=12, spaceBefore=2, spaceAfter=6)
NOTA = ParagraphStyle("NOTA", parent=BODY, fontSize=9.5, textColor=GRIS)


def chip(text, color):
    return Paragraph(f'<font color="white"><b>&nbsp;{text}&nbsp;</b></font>', ParagraphStyle(
        "chip", parent=BODY, backColor=color, borderPadding=3))


story = []

story.append(Paragraph("Configuración de WhatsApp Cloud API", H1))
story.append(Paragraph("Sistema de Gestión Financiera — pasos a realizar en Meta (≈ 30 min)", SUB))

story.append(Paragraph(
    "El código ya está migrado a la API oficial de Meta. Lo único que falta es esta "
    "configuración manual en el panel de Meta y cargar las variables en Railway. "
    "Seguí los pasos en orden.", BODY))

# ---- Paso 1
story.append(Paragraph("Paso 1 — Crear la app en Meta", H2))
story.append(Paragraph(
    'Entrá a <b>developers.facebook.com</b> &rarr; "Mis Apps" &rarr; "Crear app" &rarr; '
    'elegí el tipo <b>Empresa / Business</b>.', STEP))

# ---- Paso 2
story.append(Paragraph("Paso 2 — Agregar el producto WhatsApp", H2))
story.append(Paragraph(
    'Dentro de la app, agregá el producto <b>WhatsApp</b>. Meta te da gratis un '
    '<b>número de prueba</b> y un <b>Phone Number ID</b>.', STEP))
story.append(Paragraph('Copiá el <b>Phone Number ID</b> &rarr; va en <b>WHATSAPP_PHONE_NUMBER_ID</b>.', STEP))

# ---- Paso 3
story.append(Paragraph("Paso 3 — Registrar tu número de operador", H2))
story.append(Paragraph(
    'En <b>WhatsApp &rarr; API Setup</b>, agregá tu número de operador como destinatario. '
    'En modo sandbox solo podés mandarle mensajes a números registrados ahí.', STEP))

# ---- Paso 4
story.append(Paragraph("Paso 4 — Token permanente (importante)", H2))
story.append(Paragraph(
    'El token que se ve en "API Setup" <b>dura solo 24 horas</b>. Para producción necesitás uno permanente:', STEP))
story.append(ListFlowable([
    ListItem(Paragraph("Andá a <b>Business Settings &rarr; Usuarios &rarr; Usuarios del sistema</b>.", STEP)),
    ListItem(Paragraph("Creá un <b>System User</b> y asignale esta app.", STEP)),
    ListItem(Paragraph('Dale el permiso <b>whatsapp_business_messaging</b>.', STEP)),
    ListItem(Paragraph("Generá un token <b>sin vencimiento</b>.", STEP)),
], bulletType="1", leftIndent=14))
story.append(Paragraph('Ese token &rarr; va en <b>WHATSAPP_ACCESS_TOKEN</b>.', STEP))

# ---- Paso 5
story.append(Paragraph("Paso 5 — App Secret", H2))
story.append(Paragraph(
    'En <b>Configuración &rarr; Básica</b> de la app, copiá el <b>App Secret</b> '
    '&rarr; va en <b>WHATSAPP_APP_SECRET</b>.', STEP))

# ---- Paso 6
story.append(Paragraph("Paso 6 — Cargar variables en Railway", H2))
story.append(Paragraph(
    'En el servicio <b>backend</b> de Railway, pestaña <b>Variables</b>, cargá:', STEP))
story.append(Paragraph(
    "WHATSAPP_ACCESS_TOKEN = (token permanente del paso 4)<br/>"
    "WHATSAPP_PHONE_NUMBER_ID = (paso 2)<br/>"
    "WHATSAPP_APP_SECRET = (paso 5)<br/>"
    "WHATSAPP_VERIFY_TOKEN = (un string secreto que inventes vos)<br/>"
    "WHATSAPP_OPERATOR_PHONE = 5491123456789 (tu número, solo dígitos)", CODE))

# ---- Paso 7
story.append(Paragraph("Paso 7 — Configurar el webhook", H2))
story.append(Paragraph(
    'En <b>WhatsApp &rarr; Configuration &rarr; Webhook</b>, click en "Edit":', STEP))
story.append(Paragraph(
    "Callback URL:   https://&lt;tu-backend&gt;.railway.app/webhook/whatsapp<br/>"
    "Verify token:   (el MISMO string que pusiste en WHATSAPP_VERIFY_TOKEN)", CODE))
story.append(Paragraph(
    'Tocá <b>"Verify and Save"</b>. Meta va a llamar al endpoint de verificación '
    '(ya implementado). Si las variables están bien, valida solo.', STEP))
story.append(Paragraph(
    'Después, en "Webhook fields", suscribite al campo <b>messages</b>.', STEP))

# ---- Checklist
story.append(Spacer(1, 8))
story.append(Paragraph("Checklist final", H2))
check = [
    "App de tipo Business creada",
    "Producto WhatsApp agregado",
    "Número de operador registrado como destinatario",
    "Token permanente generado (System User)",
    "App Secret copiado",
    "Las 5 variables cargadas en Railway",
    "Webhook verificado y suscripto al campo 'messages'",
    "Prueba: mandar un WhatsApp al número y ver que el bot responde",
]
story.append(ListFlowable(
    [ListItem(Paragraph(c, STEP), bulletColor=VERDE) for c in check],
    bulletType="bullet", start="square", leftIndent=14))

# ---- Advertencias
story.append(Spacer(1, 8))
story.append(Paragraph("Tener en cuenta", H2))
data = [
    [Paragraph("<b>Ventana de 24h</b>", NOTA),
     Paragraph("Solo se puede mandar texto libre dentro de las 24h del último mensaje "
               "del operador. Las notificaciones proactivas (ej. auto-cancelación de "
               "préstamos) fuera de esa ventana necesitan una plantilla aprobada por Meta.", NOTA)],
    [Paragraph("<b>El '9' de Argentina</b>", NOTA),
     Paragraph("Meta a veces entrega el número sin el 9 (54 11... en vez de 549 11...). "
               "Si el bot ignora tus mensajes, avisá: se ajusta la comparación del número.", NOTA)],
    [Paragraph("<b>Modo producción</b>", NOTA),
     Paragraph("Para mandarle a números no registrados (clientes reales), hay que verificar "
               "el negocio en Meta Business y pasar la app a modo Live.", NOTA)],
]
t = Table(data, colWidths=[38*mm, 132*mm])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("BACKGROUND", (0, 0), (0, -1), GRIS_CLARO),
    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
]))
story.append(t)

doc = SimpleDocTemplate(
    "Setup_WhatsApp_Cloud_API.pdf", pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
    title="Setup WhatsApp Cloud API",
)
doc.build(story)
print("PDF generado: Setup_WhatsApp_Cloud_API.pdf")

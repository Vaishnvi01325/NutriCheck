import os
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from config import REPORT_FOLDER


# Color palette
COLOR_PRIMARY = HexColor('#6C5CE7')
COLOR_GREEN = HexColor('#00B894')
COLOR_AMBER = HexColor('#FDCB6E')
COLOR_RED = HexColor('#E17055')
COLOR_DARK = HexColor('#2D3436')
COLOR_LIGHT = HexColor('#DFE6E9')
COLOR_WHITE = HexColor('#FFFFFF')


def get_verdict_color(verdict):
    if verdict == 'Healthy Choice':
        return COLOR_GREEN
    elif verdict == 'Consume in Moderation':
        return COLOR_AMBER
    else:
        return COLOR_RED


def generate_pdf(analysis):
    """
    Generate a PDF report for the given analysis data.
    
    Args:
        analysis: dict with all analysis fields
    
    Returns:
        Path to the generated PDF file
    """
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    filename = f"nutricheck_report_{analysis['id']}.pdf"
    filepath = os.path.join(REPORT_FOLDER, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        textColor=COLOR_PRIMARY,
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLOR_DARK,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=COLOR_PRIMARY,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLOR_DARK,
        spaceAfter=6,
        leading=14,
    )
    verdict_style = ParagraphStyle(
        'Verdict',
        parent=styles['Normal'],
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        spaceBefore=6,
    )
    score_style = ParagraphStyle(
        'Score',
        parent=styles['Title'],
        fontSize=36,
        alignment=TA_CENTER,
        textColor=COLOR_PRIMARY,
        spaceAfter=2,
    )

    elements = []

    # --- Header ---
    elements.append(Paragraph("🍎 NutriCheck Report", title_style))
    elements.append(Paragraph(
        f"Product: {analysis.get('product_name', 'Unknown')} | "
        f"Date: {analysis.get('created_at', 'N/A')}",
        subtitle_style
    ))
    elements.append(HRFlowable(
        width="100%", thickness=1, color=COLOR_PRIMARY, spaceAfter=10
    ))

    # --- Product Image ---
    image_path = analysis.get('image_path', '')
    if image_path and os.path.exists(image_path):
        try:
            img = RLImage(image_path, width=3 * inch, height=3 * inch, kind='proportional')
            elements.append(img)
            elements.append(Spacer(1, 8))
        except Exception:
            pass

    # --- Health Score ---
    elements.append(Paragraph("Health Score", heading_style))
    elements.append(Paragraph(
        f"{analysis.get('health_score', 'N/A')} / 100",
        score_style
    ))

    verdict = analysis.get('verdict', '')
    vc = get_verdict_color(verdict)
    elements.append(Paragraph(
        f'<font color="{vc.hexval()}">{verdict}</font>',
        verdict_style
    ))
    elements.append(Spacer(1, 6))

    # --- Nutrient Table ---
    elements.append(Paragraph("Nutritional Information", heading_style))

    nutrients_data = [
        ['Nutrient', 'Value', 'Unit'],
        ['Calories', str(analysis.get('calories', 'N/A')), 'kcal'],
        ['Sugar', str(analysis.get('sugar', 'N/A')), 'g'],
        ['Fat', str(analysis.get('fat', 'N/A')), 'g'],
        ['Sodium', str(analysis.get('sodium', 'N/A')), 'mg'],
        ['Protein', str(analysis.get('protein', 'N/A')), 'g'],
        ['Fiber', str(analysis.get('fiber', 'N/A')), 'g'],
    ]

    table = Table(nutrients_data, colWidths=[50 * mm, 40 * mm, 30 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_WHITE),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLOR_WHITE, COLOR_LIGHT]),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_LIGHT),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 10))

    # --- Explanation ---
    explanation = analysis.get('explanation', '')
    if explanation:
        elements.append(Paragraph("Analysis Explanation", heading_style))
        elements.append(Paragraph(explanation, body_style))

    # --- Recommendation ---
    recommendation = analysis.get('recommendation', '')
    if recommendation:
        elements.append(Paragraph("Dietary Recommendation", heading_style))
        elements.append(Paragraph(recommendation, body_style))

    # --- Footer ---
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(
        width="100%", thickness=0.5, color=COLOR_LIGHT, spaceAfter=6
    ))
    elements.append(Paragraph(
        "Generated by NutriCheck — Food Label Reader & Health Analyzer",
        ParagraphStyle('Footer', parent=styles['Normal'],
                       fontSize=8, textColor=COLOR_LIGHT, alignment=TA_CENTER)
    ))

    # Build PDF
    doc.build(elements)
    return filepath

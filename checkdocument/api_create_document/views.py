from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.http import FileResponse
from django.conf import settings

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
import textwrap

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from io import BytesIO
import os
from PIL import Image, ImageOps
import qrcode




def load_image(file):
    """Load and auto-orient image."""
    if not file:
        return None
    return ImageOps.exif_transpose(Image.open(file))

def generate_QR(data, size=70):
    """Generate QR as ImageReader."""
    qr = qrcode.QRCode(
        version=5,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    return ImageReader(qr_buffer)

def build_notary_paragraph(document_type, customer_name, schedule_date):
    """Return notary certification paragraph."""
    return (
        f"I, JOHN OLATUNJI OF ONE LONDON SQUARE, CROSS LANES, GUILDFORD, GU1 1UN, "
        f"A DULY AUTHORISED NOTARY PUBLIC OF ENGLAND AND WALES CERTIFY THAT THIS IS A TRUE COPY OF THE DOCUMENT "
        f"{document_type} OF {customer_name} PRODUCED TO ME THIS {schedule_date} "
        f"AND I FURTHER CERTIFY THAT THE INDIVIDUAL THAT APPEARED BEFORE ME VIA VIDEO CONFERENCE CALL IS INDEED "
        f"AND BEARS THE TRUE LIKENESS OF {customer_name}."
    )

def get_bold_words(document_type, customer_name, schedule_date):
    """Return words to make bold in paragraph."""
    # try:
        
    return [
            word.upper() for word in (document_type.split() + customer_name.split() + [schedule_date])
            
            
        ]
    # except:
    #     return [
    #         word for word in (document_type.split() + customer_name.split() + [schedule_date])
            
    #     ]

def draw_paragraph_with_bold(c, paragraph, start_x, start_y, width=80, font_size=10, bold_words=None):
    """Draw wrapped paragraph with selected words in bold."""
    wrapper = textwrap.TextWrapper(width=width)
    lines = wrapper.wrap(paragraph)
    text_obj = c.beginText(start_x, start_y)
    text_obj.setFont("Helvetica", font_size)
    
    for line in lines:
        for word in line.split(" "):
            if word.strip(",.").upper() in bold_words:
                text_obj.setFont("Helvetica-Bold", font_size)
                print(text_obj)
            else:
                text_obj.setFont("Helvetica", font_size)
            text_obj.textOut(word + " ")
        text_obj.textLine("")  # New line
    c.drawText(text_obj)

def add_qr(c, qr_text, x=20, y=10, size=70):
    """Place QR code on canvas."""
    qr_image = generate_QR(qr_text, size=size)
    c.drawImage(qr_image, x=x, y=y, width=size, height=size)

def merge_overlay(base_page, overlay_buffer):
    """Merge overlay page into base page."""
    overlay_pdf = PdfReader(overlay_buffer)
    base_page.merge_page(overlay_pdf.pages[0])
    return base_page


# -----------------------
# Main Document Generator
# -----------------------

def generate_document(first_image, back_image, first_image_2, back_image_2,
                      document_type, layout, multiPagePdf, 
                      qr_text , customer_name,schedule_date=None):
    print(customer_name+" this constomer name")
    print(qr_text+"qr text")
    overlay_buffer = BytesIO()
    page_width, page_height = A4

    # Load all images
    front_image = load_image(first_image)
    back_image = load_image(back_image)
    front_image_2 = load_image(first_image_2)
    back_image_2 = load_image(back_image_2)

    # -------------------------
    # Layout specific handling
    # -------------------------

    if layout == "ONENOTARY":
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'output_1.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]

        c.drawString(200, 428, document_type)

        image_width, image_height = 280, 230
        image_y = page_height - 250

        if back_image:
            start_x = (page_width - (2 * image_width)) / 2
            c.drawImage(ImageReader(front_image), start_x, image_y, width=image_width, height=image_height)
            c.drawImage(ImageReader(back_image), start_x + image_width, image_y, width=image_width, height=image_height)
        else:
            x_center = (page_width - image_width) / 2
            c.drawImage(ImageReader(front_image), x_center, image_y, width=image_width, height=image_height)

        c.save()
        overlay_buffer.seek(0)

        # Merge overlay into template
        base_page = merge_overlay(base_page, overlay_buffer)
        output = PdfWriter()
        output.add_page(base_page)

        result_buffer = BytesIO()
        output.write(result_buffer)
        result_buffer.seek(0)
        return FileResponse(result_buffer, as_attachment=True, filename="Notary_Format_document.pdf")

    elif layout == "UK88":
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        if front_image:
            c.drawImage(ImageReader(front_image), 30, 570, width=230, height=190)
        if back_image:
            c.drawImage(ImageReader(back_image), (page_width-230)/2, 320, width=230, height=190)

        paragraph = build_notary_paragraph(document_type, customer_name, schedule_date)
        bold_words = get_bold_words(document_type, customer_name, schedule_date)
        draw_paragraph_with_bold(c, paragraph, 50, 200, width=80, font_size=10, bold_words=bold_words)

        add_qr(c, qr_text)

        c.save()
        overlay_buffer.seek(0)
        return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")

    elif layout == "UK88_MULTIPAGE":
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        print(customer_name)

        paragraph = build_notary_paragraph(document_type, customer_name, schedule_date)
        bold_words = get_bold_words(document_type, customer_name, schedule_date)
        print(bold_words)
        draw_paragraph_with_bold(c, paragraph, 50, 800, width=80, font_size=10, bold_words=bold_words)

        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)

        overlay_pdf = PdfReader(overlay_buffer)
        paragraph_page_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_page(overlay_pdf.pages[0])
        writer.write(paragraph_page_buffer)
        paragraph_page_buffer.seek(0)

        response_pdf = BytesIO(multiPagePdf.read())
        multiPagePdf.seek(0)

        merger = PdfMerger()
        merger.append(paragraph_page_buffer)
        merger.append(response_pdf)

        final_buffer = BytesIO()
        merger.write(final_buffer)
        merger.close()
        final_buffer.seek(0)
        return FileResponse(final_buffer, as_attachment=True, filename="UK88_Multi_Page_Pdf.pdf")

    elif layout == "us_multipage":
        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'US_MultiPage_format.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]

        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        c.drawString(205, 594, document_type)
        c.save()
        overlay_buffer.seek(0)

        base_page = merge_overlay(base_page, overlay_buffer)
        output_writer = PdfWriter()
        output_writer.add_page(base_page)

        modified_pdf_buffer = BytesIO()
        output_writer.write(modified_pdf_buffer)
        modified_pdf_buffer.seek(0)

        response_pdf = BytesIO(multiPagePdf.read())
        multiPagePdf.seek(0)

        merger = PdfMerger()
        merger.append(modified_pdf_buffer)
        merger.append(response_pdf)

        final_buffer = BytesIO()
        merger.write(final_buffer)
        merger.close()
        final_buffer.seek(0)
        return FileResponse(final_buffer, as_attachment=True, filename="Multi_Page_Pdf.pdf")

    elif layout == "non_multipage":
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)

        base_pdf = PdfReader(multiPagePdf)
        overlay_pdf = PdfReader(overlay_buffer)
        total_page = len(base_pdf.pages)

        output = PdfWriter()
        for i, base_page in enumerate(base_pdf.pages):
            if i == total_page - 1:
                base_page.merge_page(overlay_pdf.pages[0])
            output.add_page(base_page)

        result_buffer = BytesIO()
        output.write(result_buffer)
        result_buffer.seek(0)
        return FileResponse(result_buffer, as_attachment=True, filename="multi_Format_document.pdf")

    else:
        # ----------------
        # Image placement
        # ----------------
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        if front_image and back_image and front_image_2 and back_image_2:
            current_y = 570
            width, height = 270, 180
            current_x = 30
            x_back = (page_width - current_x) / 2

            c.drawImage(ImageReader(front_image), current_x, current_y, width, height)
            c.drawImage(ImageReader(back_image), x_back+20, current_y, width, height)
            c.drawImage(ImageReader(front_image_2), current_x, 350, width, height)
            c.drawImage(ImageReader(back_image_2), x_back+20, 350, width, height)
            c.drawString(50, 50, "IP(FB)DL(FB)")

        elif front_image and front_image_2 and back_image_2:
            width, height = 280, 170
            c.drawImage(ImageReader(front_image), 90, 530, width=360, height=250)
            c.drawImage(ImageReader(front_image_2), 10, 260, width, height)
            c.drawImage(ImageReader(back_image_2), 10+width+20, 260, width, height)
            c.drawString(50, 50, "IP(F)DL(FB)")

        elif front_image and back_image and front_image_2:
            width, height = 270, 180
            c.drawImage(ImageReader(front_image), 40, 550, width, height)
            c.drawImage(ImageReader(back_image), 40+width, 550, width, height)
            c.drawImage(ImageReader(front_image_2), (page_width-width)/2, 250, width, height)
            c.drawString(50, 50, "IP(FB)DL(F)")

        elif front_image and back_image:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            c.drawImage(ImageReader(front_image), x_center, current_y, width, height)
            c.drawImage(ImageReader(back_image), x_center, current_y - height - 20, width, height)
            c.drawString(50, 50, "IP(FB)")

        elif front_image and front_image_2:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            c.drawImage(ImageReader(front_image), x_center, current_y, width, height)
            c.drawImage(ImageReader(front_image_2), x_center, current_y - height - 20, width, height)
            c.drawString(50, 50, "IP(F)DL(F)")

        elif front_image:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            c.drawImage(ImageReader(front_image), x_center, current_y, width, height)

        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)
        return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")


# -----------------------
# API View
# -----------------------

class GeneratePDFView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        first_image = request.FILES.get('front_image')
        back_image = request.FILES.get('back_image')
        first_image_2 = request.FILES.get('front_image2')
        back_image_2 = request.FILES.get('back_image2')
        multiPagePdf = request.FILES.get('multi_page_pdf')
        document_type = request.data.get('document_type', 'Default Document Type')
        layout = request.data.get('layout', 'STANDARD')
        customer_name = request.data.get('customer_name','COSTOMER NAME REQ.')
        
        qr_text = request.data.get('qr_text','QR TEXT')
        schedule_date = request.data.get('schedule_date')

        response = generate_document(
            first_image, back_image, first_image_2, back_image_2,
            document_type, layout, multiPagePdf, qr_text,customer_name,schedule_date
        )
        return response

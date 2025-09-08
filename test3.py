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
import fitz


# -----------------------
# Helpers
# -----------------------

def compress_image(img, max_width=1200, quality=60):
    """
    Resize + compress a PIL.Image to JPEG in a BytesIO buffer.
    SAFE: returns None if img is None.
    If img is already a BytesIO (assumed compressed), returns it unchanged.
    """
    if img is None:
        return None

    if isinstance(img, BytesIO):
        # Already a buffer (likely already compressed)
        img.seek(0)
        return img

    # Expect a PIL.Image
    if not isinstance(img, Image.Image):
        # Unknown type: try to open as image
        try:
            img = Image.open(img)
        except Exception:
            return None

    if img.mode != "RGB":
        img = img.convert("RGB")

    # Scale down if too large
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    buf = BytesIO()
    # JPEG compression; quality=60 is a solid size/clarity tradeoff
    img.save(buf, format="JPEG", quality=60, optimize=True)
    buf.seek(0)
    return buf


def load_image(file):
    """
    Load and auto-orient an image OR convert a PDF into a list of PIL.Image.
    Returns:
        - PIL.Image if normal image
        - list[PIL.Image] if multi-page PDF
        - None if no file
    """
    if not file:
        return None

    filename = getattr(file, "name", "").lower()

    # PDF: render each page
    if filename.endswith(".pdf"):
        pdf_bytes = file.read()
        file.seek(0)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for page_num in range(len(doc)):
            pix = doc[page_num].get_pixmap(dpi=100)  # lower DPI for size
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(ImageOps.exif_transpose(img))
        return images

    # Normal image
    try:
        return ImageOps.exif_transpose(Image.open(file))
    except Exception:
        return None


def generate_QR(data, size=70):
    """Generate a small QR as ImageReader (PNG keeps sharp edges; tiny size anyway)."""
    qr = qrcode.QRCode(
        version=5,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data or "")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_buffer = BytesIO()
    # PNG is fine for QR (lossless, tiny)
    qr_img.save(qr_buffer, format="PNG", optimize=True)
    qr_buffer.seek(0)
    return ImageReader(qr_buffer)


def build_notary_paragraph(document_type, customer_name, schedule_date):

    return (
        f"I, JOHN OLATUNJI OF ONE LONDON SQUARE, CROSS LANES, GUILDFORD, GU1 1UN, "
        f"A DULY AUTHORISED NOTARY PUBLIC OF ENGLAND AND WALES CERTIFY THAT THIS IS A TRUE COPY OF THE DOCUMENT "
        f"{document_type} OF {customer_name} PRODUCED TO ME THIS {schedule_date} "
        f"AND I FURTHER CERTIFY THAT THE INDIVIDUAL THAT APPEARED BEFORE ME VIA VIDEO CONFERENCE CALL IS INDEED "
        f"AND BEARS THE TRUE LIKENESS OF {customer_name}."
    )


def get_bold_words(document_type, customer_name, schedule_date):
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
# Convert images to a single PDF
# -----------------------

def convert_images_to_pdf(files):
    """Convert one or multiple images (or PDF pages) into a single compressed PDF."""
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    page_width, page_height = A4

    for file in files:
        try:
            loaded = load_image(file)
            imgs = loaded if isinstance(loaded, list) else [loaded]

            for img in imgs:
                if img is None:
                    continue
                # Compress
                compressed_buf = compress_image(img)
                comp_img = Image.open(compressed_buf)

                img_width, img_height = comp_img.size
                ratio = min(page_width / img_width, page_height / img_height)
                new_width = img_width * ratio
                new_height = img_height * ratio
                x = (page_width - new_width) / 2
                y = (page_height - new_height) / 2

                c.drawImage(ImageReader(compressed_buf), x, y, width=new_width, height=new_height)
                c.showPage()
        except Exception as e:
            print(f"Error processing {getattr(file, 'name', 'unknown')}: {e}")

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


# -----------------------
# Main Document Generator
# -----------------------

def _compressed_buf_or_none(loaded_img):
    """Helper: returns a compressed BytesIO if PIL.Image, else None."""
    if isinstance(loaded_img, Image.Image):
        return compress_image(loaded_img)
    return None


def generate_document(first_image, back_image, first_image_2, back_image_2,
                      document_type, layout, multiPagePdf,
                      qr_text, customer_name, schedule_date=None):
    print(f"{customer_name} this constomer name")
    print(f"{qr_text} qr text")

    overlay_buffer = BytesIO()
    # Enable page compression on every canvas we create
    c = canvas.Canvas(overlay_buffer, pagesize=A4)
    page_width, page_height = A4

    # Load inputs (each returns PIL.Image or list or None)
    front_image = load_image(first_image)
    back_image = load_image(back_image)
    front_image_2 = load_image(first_image_2)
    back_image_2 = load_image(back_image_2)

    # Compress only if we got a PIL image (lists mean PDF pages; not used here)
    front_buf = _compressed_buf_or_none(front_image)
    back_buf = _compressed_buf_or_none(back_image)
    front2_buf = _compressed_buf_or_none(front_image_2)
    back2_buf = _compressed_buf_or_none(back_image_2)

    # -------------------------
    # Layout specific handling
    # -------------------------

    if layout == "ONENOTARY":
        # Start fresh overlay
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'output_1.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]

        c.drawString(200, 428, document_type or "")

        image_width, image_height = 280, 230
        image_y = page_height - 250

        if  back_buf is not None:
            start_x = (page_width - (2 * image_width)) / 2
            front_buf.seek(0)
            back_buf.seek(0)
            c.drawImage(ImageReader(front_buf), start_x, image_y, width=image_width, height=image_height)
            c.drawImage(ImageReader(back_buf), start_x + image_width, image_y, width=image_width, height=image_height)
        elif front_buf is not None:
            x_center = (page_width - image_width) / 2
            front_buf.seek(0)
            c.drawImage(ImageReader(front_buf), x_center, image_y, width=image_width, height=image_height)

        c.save()
        overlay_buffer.seek(0)

        base_page = merge_overlay(base_page, overlay_buffer)
        output = PdfWriter()
        output.add_page(base_page)
        result_buffer = BytesIO()
        output.write(result_buffer)
        result_buffer.seek(0)
        return FileResponse(result_buffer, as_attachment=True, filename="Notary_Format_document.pdf")

    elif layout == "UK88":
        # Start fresh overlay
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        if front_buf is not None:
            front_buf.seek(0)
            c.drawImage(ImageReader(front_buf), (page_width-230)/2, 570, width=230, height=190)

        if back_buf is not None:
            back_buf.seek(0)
            c.drawImage(ImageReader(back_buf), (page_width-230)/2, 320, width=230, height=190)

        paragraph = build_notary_paragraph(document_type, customer_name, schedule_date)
        bold_words = get_bold_words(document_type, customer_name, schedule_date)
        draw_paragraph_with_bold(c, paragraph, 50, 200, width=80, font_size=10, bold_words=bold_words)

        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)
        return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")

    elif layout == "UK88_MULTIPAGE":
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        paragraph = build_notary_paragraph(document_type, customer_name, schedule_date)
        bold_words = get_bold_words(document_type, customer_name, schedule_date)
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

        # If user uploaded images instead of a single PDF, convert to one PDF first
        if multiPagePdf and not hasattr(multiPagePdf, "read"):
            # Unexpected type; ignore
            pass

        response_pdf = BytesIO(multiPagePdf.read()) if multiPagePdf else BytesIO()
        if multiPagePdf:
            multiPagePdf.seek(0)

        merger = PdfMerger()
        merger.append(paragraph_page_buffer)
        if response_pdf.getbuffer().nbytes > 0:
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

        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        c.drawString(205, 594, document_type or "")
        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)

        base_page = merge_overlay(base_page, overlay_buffer)
        output_writer = PdfWriter()
        output_writer.add_page(base_page)

        modified_pdf_buffer = BytesIO()
        output_writer.write(modified_pdf_buffer)
        modified_pdf_buffer.seek(0)

        response_pdf = BytesIO(multiPagePdf.read()) if multiPagePdf else BytesIO()
        if multiPagePdf:
            multiPagePdf.seek(0)

        merger = PdfMerger()
        merger.append(modified_pdf_buffer)
        if response_pdf.getbuffer().nbytes > 0:
            merger.append(response_pdf)

        final_buffer = BytesIO()
        merger.write(final_buffer)
        merger.close()
        final_buffer.seek(0)
        return FileResponse(final_buffer, as_attachment=True, filename="Multi_Page_Pdf.pdf")

    elif layout == "non_multipage":
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)

        base_pdf = PdfReader(multiPagePdf) if multiPagePdf else None
        overlay_pdf = PdfReader(overlay_buffer)

        if not base_pdf:
            # If nothing to merge with, just return the overlay page
            return FileResponse(overlay_buffer, as_attachment=True, filename="multi_Format_document.pdf")

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
        # Image placement (generic)
        # ----------------
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        # Draw whichever buffers exist
        if front_buf and back_buf and front2_buf and back2_buf:
            current_y = 570
            width, height = 270, 180
            current_x = 30
            x_back = (page_width - current_x) / 2

            for buf, (x, y) in [
                (front_buf, (current_x, current_y)),
                (back_buf, (x_back+20, current_y)),
                (front2_buf, (current_x, 350)),
                (back2_buf, (x_back+20, 350)),
            ]:
                buf.seek(0)
                c.drawImage(ImageReader(buf), x, y, width, height)

        elif front_buf and front2_buf and back2_buf:
            width, height = 280, 170
            front_buf.seek(0); c.drawImage(ImageReader(front_buf), 90, 530, width=360, height=250)
            front2_buf.seek(0); c.drawImage(ImageReader(front2_buf), 10, 260, width, height)
            back2_buf.seek(0); c.drawImage(ImageReader(back2_buf), 10+width+20, 260, width, height)
            c.drawString(50, 50, "IP(F)DL(FB)")

        elif front_buf and back_buf and front2_buf:
            width, height = 270, 180
            front_buf.seek(0); c.drawImage(ImageReader(front_buf), 40, 550, width, height)
            back_buf.seek(0); c.drawImage(ImageReader(back_buf), 40+width, 550, width, height)
            front2_buf.seek(0); c.drawImage(ImageReader(front2_buf), (page_width-width)/2, 250, width, height)
            c.drawString(50, 50, "IP(FB)DL(F)")

        elif front_buf and back_buf:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            front_buf.seek(0); c.drawImage(ImageReader(front_buf), x_center, current_y, width, height)
            back_buf.seek(0); c.drawImage(ImageReader(back_buf), x_center, current_y - height - 20, width, height)
            c.drawString(50, 50, "IP(FB)")

        elif front_buf and front2_buf:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            front_buf.seek(0); c.drawImage(ImageReader(front_buf), x_center, current_y, width, height)
            front2_buf.seek(0); c.drawImage(ImageReader(front2_buf), x_center, current_y - height - 20, width, height)
            c.drawString(50, 50, "IP(F)DL(F)")

        elif front_buf:
            width, height = 270, 180
            x_center = (page_width - width) / 2
            current_y = page_height - height - 50
            front_buf.seek(0); c.drawImage(ImageReader(front_buf), x_center, current_y, width, height)

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

        # Can be single PDF or multiple images
        multiPagePdf_files = request.FILES.getlist('multi_page_pdf')

        document_type = request.data.get('document_type', 'Default Document Type')
        layout = request.data.get('layout', 'STANDARD')
        customer_name = request.data.get('customer_name', 'CUSTOMER NAME REQ.')
        qr_text = request.data.get('qr_text', 'QR TEXT')
        schedule_date = request.data.get('schedule_date')

        multiPagePdf = None
        if multiPagePdf_files:
            if len(multiPagePdf_files) == 1 and multiPagePdf_files[0].name.lower().endswith(".pdf"):
                multiPagePdf = multiPagePdf_files[0]
            else:
                multiPagePdf = convert_images_to_pdf(multiPagePdf_files)

        response = generate_document(
            first_image, back_image, first_image_2, back_image_2,
            document_type, layout, multiPagePdf, qr_text, customer_name, schedule_date
        )
        return response

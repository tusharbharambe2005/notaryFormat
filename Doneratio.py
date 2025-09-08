from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
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

def calculate_dynamic_size(img_buffer, max_width=400, max_height=300, min_width=200, min_height=150):
    """
    Calculate dynamic width and height maintaining aspect ratio.
    Returns optimal size within given bounds.
    """
    img = Image.open(img_buffer)
    original_width, original_height = img.size
    img_buffer.seek(0)  # Reset buffer position
    
    # Calculate aspect ratio
    aspect_ratio = original_width / original_height
    
    # Start with max dimensions and scale down if needed
    if aspect_ratio > 1:  # Landscape
        width = min(max_width, original_width)
        height = width / aspect_ratio
        
        if height > max_height:
            height = max_height
            width = height * aspect_ratio
    else:  # Portrait or square
        height = min(max_height, original_height)
        width = height * aspect_ratio
        
        if width > max_width:
            width = max_width
            height = width / aspect_ratio
    
    # Ensure minimum sizes
    if width < min_width:
        width = min_width
        height = width / aspect_ratio
    
    if height < min_height:
        height = min_height
        width = height * aspect_ratio
    
    return int(width), int(height)


def compress_image(img, max_width=1200, quality=75):
    """
    Resize + compress a PIL.Image to JPEG in a BytesIO buffer.
    SAFE: returns None if img is None.
    Increased quality to 75 for better clarity.
    """
    if not isinstance(img, Image.Image):
        return None  # safety: skip invalid inputs
    
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Scale down if too large, but maintain better quality
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(img.height * ratio)
        # Use LANCZOS for better quality resizing
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    buf = BytesIO()
    # Increased quality for better clarity
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return buf


def compress_pdf_multipage(input_buffer, dpi=150, quality=80):
    """
    Two-step PDF compression with higher DPI and quality for better clarity.
    """
    input_buffer.seek(0)
    doc = fitz.open(stream=input_buffer.read(), filetype="pdf")

    compressed_buffer = BytesIO()
    c = canvas.Canvas(compressed_buffer, pagesize=A4)
    page_width, page_height = A4

    for page_num in range(len(doc)):
        pix = doc[page_num].get_pixmap(dpi=dpi)  # Increased DPI for better quality
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Recompress image with better quality
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)

        # Scale to A4 maintaining aspect ratio
        img_width, img_height = img.size
        ratio = min(page_width / img_width, page_height / img_height)
        new_width = img_width * ratio
        new_height = img_height * ratio
        x = (page_width - new_width) / 2
        y = (page_height - new_height) / 2

        c.drawImage(ImageReader(buf), x, y, width=new_width, height=new_height)
        c.showPage()

    c.save()
    compressed_buffer.seek(0)
    return compressed_buffer


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

    # PDF: render each page with higher DPI for better quality
    if filename.endswith(".pdf"):
        pdf_bytes = file.read()
        file.seek(0)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for page_num in range(len(doc)):
            pix = doc[page_num].get_pixmap(dpi=150)  # Increased DPI
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


def convert_images_to_pdf(files):
    """Convert one or multiple images (or PDF pages) into a single compressed PDF with dynamic sizing."""
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
                
                # Compress with better quality
                compressed_buf = compress_image(img, quality=80)
                
                # Calculate dynamic size maintaining aspect ratio
                width, height = calculate_dynamic_size(compressed_buf, 
                                                     max_width=page_width * 0.9, 
                                                     max_height=page_height * 0.9)
                
                # Center on page
                x = (page_width - width) / 2
                y = (page_height - height) / 2

                c.drawImage(ImageReader(compressed_buf), x, y, width=width, height=height)
                c.showPage()
        except Exception as e:
            print(f"Error processing {getattr(file, 'name', 'unknown')}: {e}")

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def get_image_size_in_points(img_buf):
    """
    Convert a compressed BytesIO (JPEG/PNG) into width/height in points.
    Default assumes 144 dpi for better quality.
    """
    img = Image.open(img_buf)
    dpi_val = img.info.get("dpi", (144, 144))[0]  # Higher default DPI
    
    width_px, height_px = img.size
    width_pt = (width_px / dpi_val) * 72
    height_pt = (height_px / dpi_val) * 72
    
    return width_pt, height_pt


# -----------------------
# Main Document Generator
# -----------------------

def generate_document(first_image, back_image, first_image_2, back_image_2,
                      document_type, layout, multiPagePdf,
                      qr_text, customer_name, schedule_date=None):

    overlay_buffer = BytesIO()
    c = canvas.Canvas(overlay_buffer, pagesize=A4)
    page_width, page_height = A4

    # Load inputs (each returns PIL.Image or list or None)
    front_image = load_image(first_image)
    back_image = load_image(back_image)
    front_image_2 = load_image(first_image_2)
    back_image_2 = load_image(back_image_2)

    # Compress only if we got a PIL image (lists mean PDF pages; not used here)
    front_image = compress_image(front_image, quality=80)  # Better quality
    back_image = compress_image(back_image, quality=80)
    front_image_2 = compress_image(front_image_2, quality=80)
    back_image_2 = compress_image(back_image_2, quality=80)

    # -------------------------
    # Layout specific handling
    # -------------------------

    if layout == "ONENOTARY":
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'output_1.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]

        c.drawString(200, 428, document_type or "")

        # Use dynamic sizing for ONENOTARY layout
        if back_image is not None:
            # Two images side by side with dynamic sizing
            available_width = page_width - 100  # margins
            width_each = (available_width - 20) / 2  # 20px gap
            
            width1, height1 = calculate_dynamic_size(front_image, 
                                                   max_width=width_each, 
                                                   max_height=230)
            width2, height2 = calculate_dynamic_size(back_image, 
                                                   max_width=width_each, 
                                                   max_height=230)
            
            start_x = (page_width - (width1 + width2 + 20)) / 2
            image_y = page_height - 250
            
            front_image.seek(0)
            back_image.seek(0)
            c.drawImage(ImageReader(front_image), start_x, image_y, width=width1, height=height1)
            c.drawImage(ImageReader(back_image), start_x + width1 + 20, image_y, width=width2, height=height2)
            
        elif front_image is not None:
            # Single image centered with dynamic sizing
            width, height = calculate_dynamic_size(front_image, 
                                                 max_width=400, 
                                                 max_height=230)
            x_center = (page_width - width) / 2
            image_y = page_height - 250
            
            front_image.seek(0)
            c.drawImage(ImageReader(front_image), x_center, image_y, width=width, height=height)

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
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        if front_image is not None:
            width, height = calculate_dynamic_size(front_image, max_width=300, max_height=200)
            x_center = (page_width - width) / 2
            front_image.seek(0)
            c.drawImage(ImageReader(front_image), x_center, 570, width=width, height=height)

        if back_image is not None:
            width, height = calculate_dynamic_size(back_image, max_width=300, max_height=200)
            x_center = (page_width - width) / 2
            back_image.seek(0)
            c.drawImage(ImageReader(back_image), x_center, 320, width=width, height=height)

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

        if multiPagePdf and not hasattr(multiPagePdf, "read"):
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
        compressed_final = compress_pdf_multipage(final_buffer)
        return FileResponse(compressed_final, as_attachment=True, filename="UK88_Multi_Page_Pdf.pdf")

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
        compressed_final = compress_pdf_multipage(final_buffer)
        
        return FileResponse(compressed_final, as_attachment=True, filename="Multi_Page_Pdf.pdf")

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
        # Simple image placement logic (from 2nd code) with dynamic sizing
        # ----------------
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        # Count available images
        available_images = [img for img in [front_image, back_image, front_image_2, back_image_2] if img is not None]
        num_images = len(available_images)

        if num_images == 4:
            # All 4 images - 2x2 grid with dynamic sizing
            current_y = 570
            width = 270
            height = 180
            current_x = 30
            x_back = (page_width - current_x) / 2

            c.drawImage(ImageReader(front_image), current_x, current_y, width, height)
            c.drawImage(ImageReader(back_image), x_back+20, current_y, width, height)
            c.drawImage(ImageReader(front_image_2), current_x, 350, width, height)
            c.drawImage(ImageReader(back_image_2), x_back+20, 350, width, height)

        elif num_images == 3:
            if front_image and front_image_2 and back_image_2:
                # One large on top, two smaller below
                width, height = 280, 170
                
                c.drawImage(ImageReader(front_image), 90, 530, width=360, height=250)
                c.drawImage(ImageReader(front_image_2), 10, 260, width, height)
                c.drawImage(ImageReader(back_image_2), 10+width+20, 260, width, height)
            
            elif front_image and back_image and front_image_2:
                # Two on top, one below
                width, height = 270, 180
                c.drawImage(ImageReader(front_image), 40, 550, width, height)
                c.drawImage(ImageReader(back_image), 40+width, 550, width, height)
                c.drawImage(ImageReader(front_image_2), (page_width-width)/2, 250, width, height)

        elif num_images == 2:
            if front_image and back_image:
                # Two images stacked vertically with dynamic sizing
                max_width = 270
                max_height = 180
                
                width1, height1 = calculate_dynamic_size(front_image, max_width, max_height)
                width2, height2 = calculate_dynamic_size(back_image, max_width, max_height)
                
                x_center1 = (page_width - width1) / 2
                x_center2 = (page_width - width2) / 2
                current_y = page_height - height1 - 50
                
                c.drawImage(ImageReader(front_image), x_center1, current_y, width1, height1)
                c.drawImage(ImageReader(back_image), x_center2, current_y - height2 - 20, width2, height2)
            
            elif front_image and front_image_2:
                # Two images stacked vertically
                max_width = 270
                max_height = 180
                
                width1, height1 = calculate_dynamic_size(front_image, max_width, max_height)
                width2, height2 = calculate_dynamic_size(front_image_2, max_width, max_height)
                
                x_center1 = (page_width - width1) / 2
                x_center2 = (page_width - width2) / 2
                current_y = page_height - height1 - 50
                
                c.drawImage(ImageReader(front_image), x_center1, current_y, width1, height1)
                c.drawImage(ImageReader(front_image_2), x_center2, current_y - height2 - 20, width2, height2)

        elif num_images == 1:
            # Single image - use actual image size in points for better quality
            if front_image:
                front_image.seek(0)
                img_width, img_height = get_image_size_in_points(front_image)

                # Center on page
                x_center = (page_width - img_width) / 2
                current_y = page_height - img_height - 50

                c.drawImage(ImageReader(front_image), x_center, current_y,
                    width=img_width, height=img_height)

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
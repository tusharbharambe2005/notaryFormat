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


def pil_from_buffer_or_image(img_input):
    """Return a PIL.Image instance from BytesIO/file-like or PIL.Image."""
    if img_input is None:
        return None
    try:
        if isinstance(img_input, Image.Image):
            return img_input
        if hasattr(img_input, "seek"):
            img_input.seek(0)
        return Image.open(img_input)
    except Exception:
        return None


def calculate_dynamic_size(img_input, max_width=400, max_height=300, min_width=50, min_height=50):
    """
    Calculate width and height maintaining aspect ratio.
    Accepts either PIL.Image or file-like/BytesIO containing image.
    Returns (width, height) as integers (points).
    """
    img = pil_from_buffer_or_image(img_input)
    if img is None:
        return int(min_width), int(min_height)

    original_width, original_height = img.size
    if original_height == 0 or original_width == 0:
        return int(min_width), int(min_height)

    aspect_ratio = original_width / float(original_height)

    if aspect_ratio >= 1:  # landscape or square
        width = min(max_width, original_width)
        height = width / aspect_ratio
        if height > max_height:
            height = max_height
            width = height * aspect_ratio
    else:  # portrait
        height = min(max_height, original_height)
        width = height * aspect_ratio
        if width > max_width:
            width = max_width
            height = width / aspect_ratio

    # enforce minimums Yeh code minimum size constraints enforce karta hai. Agar calculated dimensions bahut chote ho jayen, toh image ko minimum readable size mein force karta hai.
    if width < min_width:
        width = min_width
        height = max(min_height, width / max(aspect_ratio, 0.0001))
    if height < min_height:
        height = min_height
        width = max(min_width, height * aspect_ratio)

    return int(round(width)), int(round(height))


def compress_image(img, max_width=1200, quality=75):
    """
    Resize + compress a PIL.Image to JPEG in a BytesIO buffer.
    Accepts PIL.Image. Returns BytesIO or None.
    """
    if not isinstance(img, Image.Image):
        return None

    if img.mode != "RGB":
        img = img.convert("RGB")

    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return buf





def compress_pdf_multipage(input_buffer, dpi=100, quality=60):
    """
    Rasterize & recompress each page (fitz), produce a new PDF as BytesIO.
    """
    input_buffer.seek(0)
    doc = fitz.open(stream=input_buffer.read(), filetype="pdf")

    compressed_buffer = BytesIO()
    c = canvas.Canvas(compressed_buffer, pagesize=A4)
    page_width, page_height = A4

    for page_num in range(len(doc)):
        pix = doc[page_num].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Recompress image
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)

        # Fit to A4 while maintaining aspect ratio
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
        - None if no file / error
    """
    if not file:
        return None

    filename = getattr(file, "name", "").lower()

    # PDF: render each page with higher DPI
    if filename.endswith(".pdf"):
        try:
            pdf_bytes = file.read()
            file.seek(0)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            images = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(ImageOps.exif_transpose(img))
            return images
        except Exception:
            return None

    # Normal image
    try:
        file.seek(0)
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


def convert_images_to_pdf(files, force_compress=False):
    """
    Convert image/file inputs list into a single PDF (BytesIO).
    If force_compress True -> compress images before embedding.
    """
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

                if force_compress:
                    img_buf = compress_image(img)
                    comp_img = Image.open(img_buf)
                else:
                    img_buf = BytesIO()
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(img_buf, format="JPEG")
                    img_buf.seek(0)
                    comp_img = Image.open(img_buf)

                img_width, img_height = comp_img.size
                ratio = min(page_width / img_width, page_height / img_height)
                new_width = img_width * ratio
                new_height = img_height * ratio
                x = (page_width - new_width) / 2
                y = (page_height - new_height) / 2

                c.drawImage(ImageReader(img_buf), x, y, width=new_width, height=new_height)
                c.showPage()

        except Exception as e:
            print(f"Error processing {getattr(file, 'name', 'unknown')}: {e}")

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


# -----------------------
# Main Document Generator
# -----------------------

def generate_document(first_image, back_image, first_image_2, back_image_2,
                      document_type, layout, multiPagePdf,
                      qr_text, customer_name, schedule_date=None):
    """
    Main generator that returns a FileResponse (PDF) for given layout and images.
    Images are normalized early to BytesIO objects.
    """
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

    # Constants defaults
    margin = 50
    gap = 20

# -------------------------
# ONENOTARY 
# -------------------------
    if layout == "ONENOTARY":
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'output_1.pdf')
        try:
            original_pdf = PdfReader(open(template_path, "rb"))
            base_page = original_pdf.pages[0]
        except Exception:
            base_page = None

        # Text area (adjust as needed)
        c.drawString(200, 428, document_type or "")

        # Define safe area to avoid template text/header/footer
        available_top = page_height - 160  # Space from top for header
        available_bottom = margin + 60     # Space from bottom for footer/QR
        available_height = max(100, available_top - available_bottom)
        available_width = page_width - 2 * margin

        # Two images side-by-side
        if back_image is not None:
            width_each = (available_width - gap) / 2
            
            # Calculate sizes with full available dimensions
            width1, height1 = calculate_dynamic_size(front_image, max_width=width_each, max_height=available_height, min_width=50, min_height=50)
            width2, height2 = calculate_dynamic_size(back_image, max_width=width_each, max_height=available_height, min_width=50, min_height=50)

            max_img_height = max(height1, height2)
            
            # NEW CONDITION: If height is greater than 230, use smaller dimensions
            if max_img_height > 230:
                max_img_width = min(width_each, 180)  # Limit width per image
                max_img_height_limit = 220  # Limit height per image
                
                width1, height1 = calculate_dynamic_size(front_image, max_width=max_img_width, max_height=max_img_height_limit, min_width=50, min_height=50)
                width2, height2 = calculate_dynamic_size(back_image, max_width=max_img_width, max_height=max_img_height_limit, min_width=50, min_height=50)
            
            # Center vertically within available space
            image_y = page_height - 250

            start_x = (page_width - (width1 + width2 + gap)) / 2

            front_image.seek(0)
            back_image.seek(0)
            c.drawImage(ImageReader(front_image), start_x, image_y, width=width1, height=height1)
            c.drawImage(ImageReader(back_image), start_x + width1 + gap, image_y, width=width2, height=height2)

        # Single image
        elif front_image is not None:
            max_w = available_width
            max_h = available_height
            
            width, height = calculate_dynamic_size(front_image, max_width=max_w, max_height=max_h, min_width=50, min_height=50)
            
            # NEW CONDITION: If height is greater than 230, use smaller dimensions
            if height > 230:
                max_w = min(available_width, 380)  # Limit width
                max_h = 220  # Limit height
                width, height = calculate_dynamic_size(front_image, max_width=max_w, max_height=max_h, min_width=50, min_height=50)
            
            x_center = (page_width - width) / 2
            image_y = page_height - 250

            front_image.seek(0)
            c.drawImage(ImageReader(front_image), x_center, image_y, width=width, height=height)

        add_qr(c, qr_text)
        c.save()
        overlay_buffer.seek(0)

        if base_page:
            base_page = merge_overlay(base_page, overlay_buffer)
            output = PdfWriter()
            output.add_page(base_page)
            result_buffer = BytesIO()
            output.write(result_buffer)
            result_buffer.seek(0)
            return FileResponse(result_buffer, as_attachment=True, filename="Notary_Format_document.pdf")
        else:
            # fallback: return overlay alone
            return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")
    # -------------------------
    # UK88 Single Page
    # -------------------------
    elif layout == "UK88":
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        # Top placements - tuned to your earlier coordinates but now dynamic sizing
        if front_image and back_image:
            width1, height1 = calculate_dynamic_size(front_image, max_width=page_width - 2 * margin, max_height=page_height * 0.35)
            width2, height2 = calculate_dynamic_size(back_image,  max_width=page_width - 2 * margin, max_height=page_height * 0.35)

            max_img_height = max(height1, height2)
            print(width1)
            
            # NEW CONDITION: If height is greater than 230, use smaller dimensions
            if max_img_height > 290:
                max_img_width = min(page_width - 2 * margin, 400)  # Limit width per image
                max_img_height_limit = 290  # Limit height per image
                
                width1, height1 = calculate_dynamic_size(front_image, max_width=max_img_width, max_height=max_img_height_limit, min_width=50, min_height=50)
                width2, height2 = calculate_dynamic_size(back_image, max_width=max_img_width, max_height=max_img_height_limit, min_width=50, min_height=50)
                max_img_height = max(height1, height2)
            x_center1 = (page_width - width1) / 2
            x_center2 = (page_width - width2) / 2

            front_image.seek(0)
            back_image.seek(0)
            # place first near top
            top_y = page_height  - height1-15
            c.drawImage(ImageReader(front_image), x_center1, top_y, width=width1, height=height1)
            # place second below
            second_y = top_y - height2 - 25
            c.drawImage(ImageReader(back_image), x_center2, second_y, width=width2, height=height2)

        elif front_image:
            width, height = calculate_dynamic_size(front_image, max_width=page_width - 2 * margin, max_height=page_height * 0.6)
            if height > 355:
                max_w = min(page_width - 2 * margin, 400)  # Limit width
                max_h = 355  # Limit height
                width, height = calculate_dynamic_size(front_image, max_width=max_w, max_height=max_h, min_width=50, min_height=50)
            x_center = (page_width - width) / 2
            front_image.seek(0)
            c.drawImage(ImageReader(front_image), x_center, page_height - margin - height, width=width, height=height)

        paragraph = build_notary_paragraph(document_type, customer_name, schedule_date)
        bold_words = get_bold_words(document_type, customer_name, schedule_date)
        # place paragraph a bit lower
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
            # add_qr(c, qr_text)
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
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        # Reusable available area for this general layout
        avail_top = page_height - margin
        avail_bottom = margin + 40
        avail_height = max(100, avail_top - avail_bottom)
        avail_width = page_width - 2 * margin
        page_width, page_height = A4

        # Many combinations — each placed with dynamic sizing and vertical centering
        try:
            # Four images present (2x2)
            if front_image and back_image and front_image_2 and back_image_2:
                # compute each cell width (two columns)
                col_w = (avail_width - gap) / 2
                # heights limited to half available height (minus small gap)
                cell_h = (avail_height - gap) / 2

                width1, height1 = calculate_dynamic_size(front_image, max_width=col_w, max_height=cell_h)
                width2, height2 = calculate_dynamic_size(back_image,  max_width=col_w, max_height=cell_h)
                width3, height3 = calculate_dynamic_size(front_image_2, max_width=col_w, max_height=cell_h)
                width4, height4 = calculate_dynamic_size(back_image_2,  max_width=col_w, max_height=cell_h)

                top_y = avail_bottom + cell_h + gap  # y position for top row
                left_x = margin
                right_x = margin + col_w + gap

                c.drawImage(ImageReader(front_image), left_x + (col_w - width1) / 2, top_y + (cell_h - height1) / 2, width=width1, height=height1)
                c.drawImage(ImageReader(back_image), right_x + (col_w - width2) / 2, top_y + (cell_h - height2) / 2, width=width2, height=height2)
                c.drawImage(ImageReader(front_image_2), left_x + (col_w - width3) / 2, avail_bottom + (cell_h - height3) / 2, width=width3, height=height3)
                c.drawImage(ImageReader(back_image_2), right_x + (col_w - width4) / 2, avail_bottom + (cell_h - height4) / 2, width=width4, height=height4)

            # Three images (one big, two below)
            elif front_image and front_image_2 and back_image_2:
                top_h = avail_height * 0.55
                col_w = (avail_width - gap) / 2
                
                width1, height1 = calculate_dynamic_size(front_image, max_width=avail_width, max_height=top_h)     
                width2, height2 = calculate_dynamic_size(front_image_2, max_width=col_w, max_height=avail_height * 0.4)
                width3, height3 = calculate_dynamic_size(back_image_2,  max_width=col_w, max_height=avail_height * 0.4)

                top_y = avail_bottom + (avail_height - (height1 + gap + max(height2, height3))) / 2 + max(height2, height3)
                c.drawImage(ImageReader(front_image), (page_width - width1) / 2, top_y, width=width1, height=height1)

                bottom_y = top_y - gap - max(height2, height3)
                c.drawImage(ImageReader(front_image_2), margin, bottom_y + (max(height2, height3) - height2) / 2, width=width2, height=height2)
                c.drawImage(ImageReader(back_image_2), margin + col_w + gap, bottom_y + (max(height2, height3) - height3) / 2, width=width3, height=height3)

            elif front_image and back_image and front_image_2:
                # Two on top, one below
                top_h = avail_height * 0.4
                col_w = (avail_width - gap) / 2
                

                width1, height1 = calculate_dynamic_size(front_image, max_width=col_w, max_height=avail_height * 0.55)
                width2, height2 = calculate_dynamic_size(back_image,  max_width=col_w, max_height=avail_height * 0.55)
                width3, height3 = calculate_dynamic_size(front_image_2, max_width=12222, max_height=255)

                top_y = avail_bottom + (avail_height - (height1 + gap + max(height2, height3))) / 2 + max(height2, height3)
                bottom_y = top_y - gap - max(height2, height3)


                c.drawImage(ImageReader(front_image), 40, 550, width=width1, height=height1)
                c.drawImage(ImageReader(back_image), width1+70, 550, width=width2, height=height2)
                c.drawImage( ImageReader(front_image_2),(page_width-width3)/2, 250, width3, height3)
            # Two images stacked vertically centered
            elif front_image and back_image:
                width1, height1 = calculate_dynamic_size(front_image, max_width=avail_width, max_height=avail_height * 0.6)
                width2, height2 = calculate_dynamic_size(back_image,  max_width=avail_width, max_height=avail_height * 0.6)
                total_needed = height1 + height2 + gap
                
                if total_needed > avail_height:
                    
                    scale = avail_height / float(total_needed)
                    
                    
                    width1, height1 = int(width1 * scale), int(height1 * scale)
                    width2, height2 = int(width2 * scale), int(height2 * scale)
                    print(width2,height2)
                    
                    total_needed = height1 + height2 + gap

                start_y = avail_bottom + (avail_height - total_needed) / 2
                c.drawImage(ImageReader(front_image), (page_width - width1) / 2, start_y + height2 + gap, width=width1, height=height1)
                c.drawImage(ImageReader(back_image),  (page_width - width2) / 2, start_y, width=width2, height=height2)

            elif front_image and front_image_2:
                width1, height1 = calculate_dynamic_size(front_image, max_width=avail_width, max_height=avail_height * 0.6)
                width2, height2 = calculate_dynamic_size(front_image_2, max_width=avail_width, max_height=avail_height * 0.6)

                total_needed = height1 + height2 + gap
                if total_needed > avail_height:
                    scale = avail_height / float(total_needed)
                    width1, height1 = int(width1 * scale), int(height1 * scale)
                    width2, height2 = int(width2 * scale), int(height2 * scale)
                    total_needed = height1 + height2 + gap

                start_y = avail_bottom + (avail_height - total_needed) / 2

                c.drawImage(ImageReader(front_image), (page_width - width1) / 2, start_y + height2 + gap, width=width1, height=height1)

                c.drawImage(ImageReader(front_image_2), (page_width - width2) / 2, start_y, width=width2, height=height2)

            # Single image centered
            elif front_image:
                w, h = calculate_dynamic_size(front_image, max_width=avail_width, max_height=avail_height)
                x_center = (page_width - w) / 2
                y_center = avail_bottom + (avail_height - h) / 2
                c.drawImage(ImageReader(front_image), x_center, y_center, width=w, height=h)

            # fallback: nothing to draw
        except Exception as e:
            print("Error in default layout drawing:", e)

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

        # multiPagePdf can be a single pdf file or multiple image files
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

                #  size check for direct uploaded PDF
                size_in_mb = multiPagePdf.size / (1024 * 1024)
                if size_in_mb > 5:
                    # Compress if >5MB
                    buffer = BytesIO(multiPagePdf.read())
                    multiPagePdf.seek(0)
                    compressed_pdf = compress_pdf_multipage(buffer)
                    multiPagePdf = compressed_pdf

            else:
                # Step 1: Make PDF without compression
                temp_pdf = convert_images_to_pdf(multiPagePdf_files, force_compress=False)

                # Step 2: Check size
                size_in_mb = len(temp_pdf.getvalue()) / (1024 * 1024)
                if size_in_mb > 5:  
                    # Compress only if >5 MB
                    temp_pdf = convert_images_to_pdf(multiPagePdf_files, force_compress=True)

                multiPagePdf = temp_pdf

        response = generate_document(
            first_image, back_image, first_image_2, back_image_2,
            document_type, layout, multiPagePdf, qr_text, customer_name, schedule_date
        )
        return response

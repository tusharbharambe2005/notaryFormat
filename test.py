from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.http import FileResponse
from django.conf import settings

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
import textwrap

from PyPDF2 import PdfReader, PdfWriter, PdfMerger

from io import BytesIO
import os
from PIL import Image, ImageOps
import qrcode


#load image
def load_image(file):
    if not file:
        return None
    return  ImageOps.exif_transpose(Image.open(file))

# Generate QR code
def generate_QR(data,size=70):
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


# Draw paragraph with bold words
def draw_paragraph_with_bold(c,paragraph,start_x,start_y,width=80,font_size=10,bold_words=None):
    wrapper = textwrap.TextWrapper(width=80)
    lines = wrapper.wrap(paragraph)
    text_obj = c.beginText(start_x, start_y)  # Start position (x, y)
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

# Generate document
def generate_document(first_image,back_image,first_image_2,back_image_2,document_type,layout,multiPagePdf, qr_text="Temp para",customer_name="Tushar Bharambe",schedule_date="2023-10-1"):

    overlay_buffer = BytesIO()
    page_width, page_height = A4

    front_image = load_image(first_image)
    back_image = load_image(back_image)
    front_image_2 = load_image(first_image_2)
    back_image_2 = load_image(back_image_2)

    if layout == "ONENOTARY":
        image_width = 280
        image_height = 230
        page_width, page_height = A4
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'output_1.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]
        c.drawString(200,428,document_type)


        # Place images
        image_y = page_height - 250
        if back_image:
            total_width = 2 * image_width
            start_x = (page_width - total_width) / 2
            c.drawImage(ImageReader(front_image), start_x, image_y, width=image_width, height=image_height)
            c.drawImage(ImageReader(back_image), start_x + image_width, image_y, width=image_width, height=image_height)

        else:
            x_center = (page_width - image_width) / 2
            c.drawImage(ImageReader(front_image), x_center, image_y, width=image_width, height=image_height)

        c.save()
        overlay_buffer.seek(0)

        # Merge overlay onto base PDF
        overlay_pdf = PdfReader(overlay_buffer)
        output = PdfWriter()
        base_page.merge_page(overlay_pdf.pages[0])
        output.add_page(base_page)
        result_buffer = BytesIO()
        output.write(result_buffer)
        result_buffer.seek(0)
        return FileResponse(result_buffer, as_attachment=True, filename="Notary_Format_document.pdf")
    elif layout == "UK88":
        width = 230
        height = 190
        current_y=570
        current_x = 30
        back_x=current_x=(page_width-width)/2
        c=canvas.Canvas(overlay_buffer, pagesize=A4)

        print(customer_name+"\n")
        print(schedule_date+"\n")
        print(document_type+"\n")

        if front_image:
            c.drawImage(ImageReader(front_image),current_x,current_y,width,height)
            print("first")
        if back_image:
            c.drawImage(ImageReader(back_image),back_x,current_y-250,width,height)
            print("back")

        paragraph = (
                f"I, JOHN OLATUNJI OF ONE LONDON SQUARE, CROSS LANES, GUILDFORD, GU1 1UN, "
                f"A DULY AUTHORISED NOTARY PUBLIC OF ENGLAND AND WALES CERTIFY THAT THIS IS A TRUE COPY OF THE DOCUMENT "
                f"{document_type} OF {customer_name} PRODUCED TO ME THIS {schedule_date} "
                f"AND I FURTHER CERTIFY THAT THE INDIVIDUAL THAT APPEARED BEFORE ME VIA VIDEO CONFERENCE CALL IS INDEED "
                f"AND BEARS THE TRUE LIKENESS OF {customer_name}."
            )

        print(paragraph)

        # Bold words list
        bold_words = [
            word.upper() for word in (document_type.split() + customer_name.split() + [schedule_date])
        ]
        draw_paragraph_with_bold(c, paragraph, 50, 200, width=width, font_size=10, bold_words=bold_words)
            
        # Generate and place QR code
        qr_image = generate_QR(qr_text, size=70)
        c.drawImage(qr_image, x=20, y=10, width=70, height=70)
        c.save()
        overlay_buffer.seek(0)
        print("all done")
        return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")
    
    elif layout=='us_multipage':
        # print("done ####################")
        
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        template_path = os.path.join(settings.MEDIA_ROOT, 'templates', 'US_MultiPage_format.pdf')
        original_pdf = PdfReader(open(template_path, "rb"))
        base_page = original_pdf.pages[0]
        overlay_buffer = BytesIO()
        
            #add the document type this
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        c.drawString(205, 594, document_type)   
        c.save()
        overlay_buffer.seek(0)
            
        overlay_Add_DT_pdf = PdfReader(overlay_buffer)# DT= document type
            
        # Merge text overlay into base page
        output_writer = PdfWriter()
        base_page.merge_page(overlay_Add_DT_pdf.pages[0])
        output_writer.add_page(base_page)
            
        # Save first modified PDF in memory
        modified_pdf_buffer = BytesIO()
        output_writer.write(modified_pdf_buffer)
        modified_pdf_buffer.seek(0)

        response_pdf = BytesIO(multiPagePdf.read())
        multiPagePdf.seek(0)  # reset so Django doesn't lose file
            
        # 4. Merge modified first PDF + second PDF
        merger = PdfMerger()
        merger.append(modified_pdf_buffer)  # first (with document_type text)
        merger.append(response_pdf)         # second (response throw)
            
            
        final_buffer = BytesIO()
        merger.write(final_buffer)
        merger.close()
        final_buffer.seek(0)
        return FileResponse(final_buffer,as_attachment=True,filename="Multi_Page_Pdf.pdf")
            
    elif layout=='non_multipage':
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)

        qr_image = generate_QR(qr_text, size=70)  # Should return path or BytesIO of PNG
        c.drawImage(qr_image, x=20, y=10, width=70, height=70)
        c.save()

        overlay_buffer.seek(0)

        # Step 2: Read base and overlay PDFs
        base_pdf = PdfReader(multiPagePdf)
        overlay_pdf = PdfReader(overlay_buffer)

        total_page = len(base_pdf.pages)
        # Step 3: Merge overlay onto the first page (or loop for all pages)
        output = PdfWriter()
        for  i,base_page in enumerate(base_pdf.pages):
            # You can apply overlay only on first page, or all pages
            if i == total_page-1:
                base_page.merge_page(overlay_pdf.pages[0])
            output.add_page(base_page)

        # Step 4: Write result to buffer
        result_buffer = BytesIO()
        output.write(result_buffer)
        result_buffer.seek(0)

        
        return FileResponse(result_buffer, as_attachment=True, filename="multi_Format_document.pdf")
    elif layout == 'UK88_MULTIPAGE':
        # 1. Create buffer for paragraph page
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=A4)
        
        
        width = 230
        paragraph = (
            f"I, JOHN OLATUNJI OF ONE LONDON SQUARE, CROSS LANES, GUILDFORD, GU1 1UN, "
            f"A DULY AUTHORISED NOTARY PUBLIC OF ENGLAND AND WALES CERTIFY THAT THIS IS A TRUE COPY OF THE DOCUMENT "
            f"{document_type} OF {customer_name} PRODUCED TO ME THIS {schedule_date} "
            f"AND I FURTHER CERTIFY THAT THE INDIVIDUAL THAT APPEARED BEFORE ME VIA VIDEO CONFERENCE CALL IS INDEED "
            f"AND BEARS THE TRUE LIKENESS OF {customer_name}."
        )

        # Bold words list
        bold_words = [
            word.upper() for word in (document_type.split() + customer_name.split() + [schedule_date])
        ]

        # Draw paragraph
        draw_paragraph_with_bold(c, paragraph, 50, 800, width=width, font_size=10, bold_words=bold_words)
        
        ###### add QR
        qr_image = generate_QR(qr_text, size=70)  # Should return path or BytesIO of PNG
        c.drawImage(qr_image, x=20, y=10, width=70, height=70)
        c.save()

        # 2. Convert to PDF
        overlay_buffer.seek(0)
        overlay_pdf = PdfReader(overlay_buffer)

        # 3. Take first page (the paragraph page)
        paragraph_page_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_page(overlay_pdf.pages[0])
        writer.write(paragraph_page_buffer)
        paragraph_page_buffer.seek(0)

        # 4. Read the multipage PDF (original document)
        response_pdf = BytesIO(multiPagePdf.read())
        multiPagePdf.seek(0)

        # 5. Merge both
        merger = PdfMerger()
        merger.append(paragraph_page_buffer)  # First: paragraph page
        merger.append(response_pdf)           # Then: original multipage PDF

        # 6. Return final file
        final_buffer = BytesIO()
        merger.write(final_buffer)
        merger.close()
        final_buffer.seek(0)

        return FileResponse(final_buffer, as_attachment=True, filename="UK88_Multi_Page_Pdf.pdf")

    else:
        c= canvas.Canvas(overlay_buffer, pagesize=A4)
        if front_image and back_image and front_image_2 and back_image_2:

                current_y=570
                width=270
                height=180
                current_x=30
                x_back= (page_width-current_x)/2

                if front_image:
                    c.drawImage(ImageReader(front_image), current_x,current_y ,width, height)
                    # current_x -= image_width + 20
                if back_image:
                    c.drawImage(ImageReader(back_image), x_back+20, current_y, width, height)
                    # current_y -= image_height + 20

                if front_image_2:
                    c.drawImage(ImageReader(front_image_2), current_x, 350, width, height)
                    # current_x -= image_width + 20# space between

                if back_image_2:
                    c.drawImage(ImageReader(back_image_2), x_back + 20, 350, width, height)
                    # current_x -= image_width + 20
                c.drawString(50,50,"IP(FB)DL(FB)")


        elif front_image  and front_image_2 and back_image_2:
                
                width=280
                height=170
                x_center=10
                current_y=260
                x_frontImage =90

                c.drawImage(ImageReader(front_image), x_frontImage, 530 ,width=360, height=250)

                if front_image_2:
                    c.drawImage(ImageReader(front_image_2), x_center, current_y, width, height)

                if back_image_2:
                    c.drawImage(ImageReader(back_image_2), x_center+width+20, current_y, width, height)

                c.drawString(50,50,"IP(F)DL(FB)")
                    
        elif front_image and back_image and front_image_2:
                x_center=40
                current_y=550
                width=270
                height=180
                x_frontImage2 =(page_width-width)/2

                c.drawImage(ImageReader(front_image), x_center, current_y, width, height)

                if back_image:
                    c.drawImage(ImageReader(back_image), x_center+width, current_y, width, height)
                    current_y -= height + 20
                if(front_image_2):
                    c.drawImage(ImageReader(front_image_2), x_frontImage2, 250, width, height)
                    current_y -= height + 20
                c.drawString(50,50,"IP(FB)DL(F)")
        elif front_image and back_image:
                width=270
                height=180
                x_center = (page_width - width) / 2
                current_y = page_height - height - 50
                c = canvas.Canvas(overlay_buffer, pagesize=A4)

                # Draw front image
                
                c.drawImage(ImageReader(front_image), x_center, current_y, width=width, height=height)
                current_y -= height + 20  # Space below front image

                # Draw back image if available
                if back_image:
                    c.drawImage(ImageReader(back_image), x_center, current_y, width=width, height=height)
                    current_y -= height + 20

                c.drawString(50,50,"IP(FB)")
        elif front_image and front_image_2:
                width=270
                height=180
                x_center = (page_width - width) / 2
                current_y = page_height - height - 50

                # Draw front image
                c.drawImage(ImageReader(front_image), x_center, current_y, width=width, height=height)
                current_y -= height + 20  # Space below front image


                # Draw back image if available
                if front_image_2:
                    c.drawImage(ImageReader(front_image_2), x_center, current_y, width=width, height=height)
                    current_y -= height + 20

                c.drawString(50,50,"IP(F)DL(F)")


        elif front_image:
                width=270
                height=180
                x_center = (page_width - width) / 2
                current_y = page_height - height - 50

                # Draw front image
                c.drawImage(ImageReader(front_image), x_center, current_y, width=width, height=height)
                current_y -= height + 20  # Space below front image
        
        qr_image = generate_QR(qr_text, size=70)
        c.drawImage(qr_image, x=20, y=10, width=70, height=70)
        c.save()
        overlay_buffer.seek(0)
        
        
        return FileResponse(overlay_buffer, as_attachment=True, filename="Notary_Format_document.pdf")

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
        qr_text = request.data.get('qr_text', 'Temp para')

        response = generate_document(first_image,back_image,first_image_2,back_image_2,document_type,layout,multiPagePdf,qr_text)
        return response
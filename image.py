from PIL import Image

# Open the image
img = Image.open("/Users/tusharbharambe/workspace/testing_document_genrater/marksheet.jpg")
# print(img.info)
# Try to read DPI
dpi = img.info.get("dpi", (96, 96))[0]  # fallback to 96 if not present

print(img.info)
# print(f"DPI: {dpi}")

# image_processor.py
import requests
from PIL import Image, ImageFilter, ImageOps
from io import BytesIO

def make_blurry_square_from_url(url, output_file="output.jpg", size=1200):
    """
    Download an image from a URL and output a square 1200x1200 JPEG
    with blurred/darkened background fill.
    """
    # Download image
    print("Downloading image...")
    response = requests.get(url)
    img = Image.open(BytesIO(response.content)).convert("RGB")

    # Create blurred square background
    bg = ImageOps.fit(img.copy(), (size, size), method=Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(40))

    # Darken background slightly
    overlay = Image.new("RGB", (size, size), (0, 0, 0))
    bg = Image.blend(bg, overlay, alpha=0.2)

    # Resize main image to fit inside
    img.thumbnail((size*0.9, size*0.9), Image.Resampling.LANCZOS)
    offset = ((size - img.width)//2, (size - img.height)//2)
    bg.paste(img, offset)

    # Save result
    bg.save(output_file, "JPEG", quality=95)
    print("Saved:", output_file)

if __name__ == "__main__":
    # Ask user for image URL
    url = input("Enter image URL: ").strip()
    out = input("Enter output filename (default: output.jpg): ").strip()
    if not out:
        out = "output.jpg"
    make_blurry_square_from_url(url, out)
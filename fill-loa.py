#!/usr/bin/env python3
"""
Fill out SignalWire LOA form with T-Mobile bill information
"""
import os
from PIL import Image, ImageDraw, ImageFont
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io

# Form data from T-Mobile bill
FORM_DATA = {
    "phone_number": "(480) 616-9129",
    "provider": "T-Mobile",
    "billing_name": "Samson Cirocco",
    "account_number": "976348428",
    "installation_address": "20709 N 59TH DR, Glendale AZ 85308-6761",
    "alternate_contact": "(602) 295-0104",
    "space_name": "6eyes.signalwire.com",
    "project_id": "6b9a5a5f-7d10-436c-abf0-c623208d76cd",
    "date": "February 11, 2026"
}

def generate_signature(name, width=200, height=60):
    """Generate a cursive-style signature image"""
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Try to use a cursive font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", 32)
    except:
        font = ImageFont.load_default()
    
    # Draw signature in dark blue/black
    draw.text((10, 10), name, fill=(0, 0, 128, 255), font=font)
    
    return img

def create_overlay_pdf():
    """Create a PDF overlay with form data"""
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    
    # Coordinates are approximate - adjust based on form layout
    # Y-axis is from bottom, so letter height (792) - position from top
    
    # Telephone Number (top section)
    can.drawString(50, 720, FORM_DATA["phone_number"])
    
    # Previous Phone Service Provider
    can.drawString(50, 695, FORM_DATA["provider"])
    
    # Customer Billing Name
    can.drawString(50, 655, FORM_DATA["billing_name"])
    
    # Account Number
    can.drawString(350, 655, FORM_DATA["account_number"])
    
    # Full Installation Address
    can.drawString(50, 630, FORM_DATA["installation_address"])
    
    # Mailing Address (same as installation)
    can.drawString(50, 605, FORM_DATA["installation_address"])
    
    # Alternate Contact
    can.drawString(50, 580, FORM_DATA["alternate_contact"])
    
    # SignalWire Space Name
    can.drawString(150, 360, FORM_DATA["space_name"])
    
    # SignalWire Project ID
    can.drawString(150, 340, FORM_DATA["project_id"])
    
    # Date
    can.drawString(450, 300, FORM_DATA["date"])
    
    # Signature (cursive text)
    can.setFont("Helvetica-Oblique", 24)
    can.drawString(150, 300, FORM_DATA["billing_name"])
    
    can.save()
    packet.seek(0)
    return packet

def fill_loa(input_pdf, output_pdf):
    """Fill out the LOA form"""
    print(f"📄 Filling out LOA form...")
    print(f"   Input: {input_pdf}")
    print(f"   Output: {output_pdf}")
    
    # Read the blank LOA form
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    
    # Create overlay with form data
    overlay_pdf = create_overlay_pdf()
    overlay_reader = PdfReader(overlay_pdf)
    
    # Merge overlay onto first page
    page = reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)
    
    # Write filled form
    with open(output_pdf, 'wb') as f:
        writer.write(f)
    
    print(f"\n✅ LOA form filled!")
    print(f"\n📋 Form Data:")
    for key, value in FORM_DATA.items():
        print(f"   {key}: {value}")
    
    print(f"\n📎 Files to send to support@signalwire.com:")
    print(f"   1. {output_pdf} (completed LOA)")
    print(f"   2. T-Mobile bill (file_22...pdf)")

if __name__ == "__main__":
    input_pdf = "/home/samson/.openclaw/media/inbound/file_23---15093031-a719-4315-97d6-a81a6e9b9ed4.pdf"
    output_pdf = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/SignalWire-LOA-Completed.pdf"
    
    fill_loa(input_pdf, output_pdf)
    
    print(f"\n{'='*70}")
    print(f"✅ LOA FORM COMPLETE")
    print(f"{'='*70}")
    print(f"\nNext steps:")
    print(f"1. Review: {output_pdf}")
    print(f"2. Email both files to: support@signalwire.com")
    print(f"3. Subject: 'Port Request for (480) 616-9129'")
    print(f"4. Body: 'Please see attached LOA and T-Mobile bill for porting request.'")

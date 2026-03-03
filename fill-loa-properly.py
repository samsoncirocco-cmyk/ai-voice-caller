#!/usr/bin/env python3
"""
Properly fill out the LOA PDF using form fields
"""
import PyPDF2
from PyPDF2 import PdfReader, PdfWriter
import io

input_pdf = "/home/samson/.openclaw/media/inbound/file_23---15093031-a719-4315-97d6-a81a6e9b9ed4.pdf"
output_pdf = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/SignalWire-LOA-Filled.pdf"

# Form data
form_data = {
    "Telephone Number": "(480) 616-9129",
    "Provider": "T-Mobile",
    "Long Distance Provider": "T-Mobile",
    "Billing Name": "Samson Cirocco",
    "Account Number": "976348428",
    "Installation Address": "20709 N 59TH DR, Glendale AZ 85308-6761",
    "Mailing Address": "20709 N 59TH DR, Glendale AZ 85308-6761",
    "Alternate Contact": "(602) 295-0104",
    "Space Name": "6eyes.signalwire.com",
    "Project ID": "6b9a5a5f-7d10-436c-abf0-c623208d76cd",
    "Date": "February 11, 2026",
    "Signature": "Samson Cirocco"
}

reader = PdfReader(input_pdf)

# Check if PDF has form fields
if reader.get_fields():
    print("✅ PDF has form fields!")
    fields = reader.get_fields()
    print(f"\nFound {len(fields)} fields:")
    for field_name in fields:
        print(f"  - {field_name}")
    
    # Fill the form
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    
    # Update form fields
    writer.update_page_form_field_values(
        writer.pages[0],
        form_data
    )
    
    with open(output_pdf, 'wb') as f:
        writer.write(f)
    
    print(f"\n✅ Form filled: {output_pdf}")
else:
    print("❌ PDF has no form fields - it's a flat document")
    print("Need to use a signing platform instead")
    print("\nOptions:")
    print("1. Use DocuSign API")
    print("2. Use HelloSign/Dropbox Sign API")
    print("3. Upload to SignNow, PandaDoc, or Adobe Sign manually")
    print("4. Print, sign physically, scan back")

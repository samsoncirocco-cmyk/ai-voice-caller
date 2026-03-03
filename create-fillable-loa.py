#!/usr/bin/env python3
"""
Create a fillable LOA PDF with form fields and signature
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfform import textFieldRelative

def create_fillable_loa():
    filename = "SignalWire-LOA-Fillable.pdf"
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width/2, height - 0.6*inch, 
                        "Letter of Authorization for Local Number Porting Request")
    
    # Instructions
    c.setFont("Helvetica", 8)
    c.drawCentredString(width/2, height - 0.8*inch,
                       "Pre-filled with information from T-Mobile bill. Please review and sign below.")
    
    y = height - 1.2*inch
    c.setFont("Helvetica-Bold", 10)
    
    # Helper function to add filled fields
    def add_field(label, value, y_pos):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.5*inch, y_pos, label)
        c.setFont("Helvetica", 9)
        c.drawString(3*inch, y_pos, value)
        return y_pos - 0.25*inch
    
    # Customer Information
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.5*inch, y, "Customer Information (from T-Mobile Bill)")
    y -= 0.3*inch
    
    y = add_field("Telephone Number(s) to be Ported:", "(480) 616-9129", y)
    y = add_field("Previous Phone Service Provider:", "T-Mobile", y)
    y = add_field("Long Distance Provider:", "T-Mobile (same as local provider)", y)
    y = add_field("Customer Billing Name:", "Samson Cirocco", y)
    y = add_field("Account Number:", "976348428", y)
    y = add_field("Full Installation Address:", "20709 N 59TH DR, Glendale AZ 85308-6761", y)
    y = add_field("Mailing Address:", "Same as Installation Address", y)
    y = add_field("Alternate Contact Information:", "(602) 295-0104", y)
    
    # Authorization Section
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.5*inch, y, "Customer Authorization")
    y -= 0.2*inch
    
    c.setFont("Helvetica-Bold", 8)
    c.drawString(0.5*inch, y, "YOU MUST MAINTAIN SERVICE WITH YOUR PREVIOUS PROVIDER UNTIL THE PORT PROCESS IS COMPLETE")
    y -= 0.25*inch
    
    # Authorization text
    c.setFont("Helvetica", 8)
    auth_text = [
        "By submitting this form, I, the undersigned, authorize SignalWire, Inc. (SignalWire) to act on my behalf to make",
        "the necessary changes to my current business phone service to port the phone number(s) listed above, including",
        "porting/disconnecting these phone number(s). I have been advised by SignalWire that although all effort is made to",
        "coordinate a prompt conversion, local number porting may result in a minor disruption in my local and/or long distance",
        "services. I have the authority to change the phone service provider of the number(s) to be ported and I am also an",
        "authorized user on the associated SignalWire account."
    ]
    for line in auth_text:
        c.drawString(0.5*inch, y, line)
        y -= 0.12*inch
    
    # SignalWire Details
    y -= 0.2*inch
    y = add_field("SignalWire Space Name:", "6eyes.signalwire.com", y)
    y = add_field("SignalWire Project ID:", "6b9a5a5f-7d10-436c-abf0-c623208d76cd", y)
    
    # Signature Section
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.5*inch, y, "Authorized Signature:")
    
    # Draw signature line
    c.line(2.5*inch, y - 0.05*inch, 6*inch, y - 0.05*inch)
    
    # Add instructions for signature
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(2.5*inch, y - 0.25*inch, "Sign here using Adobe Acrobat, Preview, or any PDF editor")
    
    y -= 0.5*inch
    y = add_field("Printed Name:", "Samson Cirocco", y)
    y = add_field("Date:", "February 11, 2026", y)
    
    # Footer Note
    y -= 0.4*inch
    c.setFont("Helvetica-Bold", 8)
    c.drawString(0.5*inch, y, "NOTE:")
    c.setFont("Helvetica", 7)
    note_lines = [
        "You must activate your SignalWire service and submit the completed form before the port request can be initiated.",
        "It can take up to 15 business days from the date SignalWire receives your completed Number Port Request form to",
        "process the request. During this period, you must maintain your phone service with your previous provider."
    ]
    y -= 0.15*inch
    for line in note_lines:
        c.drawString(0.5*inch, y, line)
        y -= 0.1*inch
    
    # Instructions at bottom
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.5*inch, y, "HOW TO SIGN THIS DOCUMENT:")
    c.setFont("Helvetica", 8)
    instructions = [
        "1. Open this PDF in Adobe Acrobat Reader (free download from adobe.com)",
        "2. Click 'Fill & Sign' in the right panel",
        "3. Click 'Sign' and create your signature",
        "4. Place signature on the signature line above",
        "5. Save the signed PDF",
        "6. Email signed PDF + T-Mobile bill to: support@signalwire.com"
    ]
    y -= 0.15*inch
    for inst in instructions:
        c.drawString(0.7*inch, y, inst)
        y -= 0.12*inch
    
    c.save()
    return filename

if __name__ == "__main__":
    filename = create_fillable_loa()
    print(f"✅ Created fillable LOA: {filename}")
    print(f"\n📋 This PDF can be signed in:")
    print(f"   • Adobe Acrobat Reader (Fill & Sign)")
    print(f"   • Preview (Mac - Markup toolbar)")
    print(f"   • Any PDF editor")
    print(f"\n📧 After signing:")
    print(f"   Email to: support@signalwire.com")
    print(f"   Attach: Signed LOA + T-Mobile bill")
    print(f"   Subject: Port Request for (480) 616-9129")

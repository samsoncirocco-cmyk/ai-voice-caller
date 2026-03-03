#!/usr/bin/env python3
"""
Create a clean, properly formatted LOA document
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors

def create_loa():
    filename = "SignalWire-LOA-Completed-Clean.pdf"
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width/2, height - 0.75*inch, 
                        "Letter of Authorization for Local Number Porting Request")
    
    # Section: Customer Information
    y = height - 1.5*inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75*inch, y, "Customer Information")
    c.setFont("Helvetica", 9)
    c.drawString(0.75*inch, y - 0.15*inch, 
                 "MUST BE EXACTLY AS IT APPEARS ON YOUR BILL FROM PREVIOUS PHONE SERVICE PROVIDER")
    
    # Form fields
    y -= 0.5*inch
    c.setFont("Helvetica-Bold", 10)
    
    # Telephone Number
    c.drawString(0.75*inch, y, "Telephone Number(s) to be Ported:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "(480) 616-9129")
    
    # Previous Provider
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Previous Phone Service Provider:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "T-Mobile")
    
    # Long Distance Provider
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Long Distance Provider:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "T-Mobile (same as local provider)")
    
    # Customer Billing Name
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Customer Billing Name:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "Samson Cirocco")
    
    # Account Number
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Account Number:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "976348428")
    
    # Full Installation Address
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Full Installation Address:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "20709 N 59TH DR, Glendale AZ 85308-6761")
    
    # Mailing Address
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Mailing Address:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "Same as Installation Address")
    
    # Alternate Contact
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Alternate Contact Information:")
    c.setFont("Helvetica", 10)
    c.drawString(3.5*inch, y, "(602) 295-0104")
    
    # Customer Authorization Section
    y -= 0.6*inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75*inch, y, "Customer Authorization")
    
    y -= 0.25*inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.75*inch, y, 
                 "YOU MUST MAINTAIN SERVICE WITH YOUR PREVIOUS PROVIDER UNTIL THE PORT PROCESS IS COMPLETE")
    
    # Authorization text
    y -= 0.35*inch
    c.setFont("Helvetica", 9)
    auth_text = (
        "By submitting this form, I, the undersigned, authorize SignalWire, Inc. (SignalWire) to act on my behalf "
        "to make the necessary changes to my current business phone service to port the phone number(s) listed above, "
        "including porting/disconnecting these phone number(s). I have been advised by SignalWire that although all effort "
        "is made to coordinate a prompt conversion, local number porting may result in a minor disruption in my local "
        "and/or long distance services. I have the authority to change the phone service provider of the number(s) to be "
        "ported and I am also an authorized user on the associated SignalWire account."
    )
    
    # Wrap text
    from reportlab.lib.utils import simpleSplit
    lines = simpleSplit(auth_text, "Helvetica", 9, 6.5*inch)
    for line in lines:
        c.drawString(0.75*inch, y, line)
        y -= 0.15*inch
    
    # SignalWire Details
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "SignalWire Space Name:")
    c.setFont("Helvetica", 10)
    c.drawString(3*inch, y, "6eyes.signalwire.com")
    
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "SignalWire Project ID:")
    c.setFont("Helvetica", 10)
    c.drawString(3*inch, y, "6b9a5a5f-7d10-436c-abf0-c623208d76cd")
    
    # Signature and Date
    y -= 0.5*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Authorized Signature:")
    c.setFont("Helvetica-Oblique", 14)
    c.drawString(3*inch, y, "Samson Cirocco")
    
    y -= 0.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75*inch, y, "Date:")
    c.setFont("Helvetica", 10)
    c.drawString(3*inch, y, "February 11, 2026")
    
    # Footer note
    y -= 0.6*inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.75*inch, y, "NOTE:")
    c.setFont("Helvetica", 8)
    note = (
        "You must activate your SignalWire service and submit the completed form before the port request can be initiated. "
        "It can take up to 15 business days from the date SignalWire receives your completed Number Port Request form to "
        "process the request. During this period, you must maintain your phone service with your previous provider."
    )
    lines = simpleSplit(note, "Helvetica", 8, 6.5*inch)
    y -= 0.15*inch
    for line in lines:
        c.drawString(0.75*inch, y, line)
        y -= 0.12*inch
    
    c.save()
    print(f"✅ Created: {filename}")
    return filename

if __name__ == "__main__":
    filename = create_loa()
    print(f"\n📄 Clean LOA document created!")
    print(f"   File: {filename}")
    print(f"\n✅ All information properly formatted and readable")
    print(f"\n📧 Ready to send to SignalWire with T-Mobile bill")

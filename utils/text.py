import re

def sanitize_text(text):
    """Remove emojis and non-ASCII characters that FPDF can't handle"""
    if text is None:
        return ''
    
    # Convert to string
    text = str(text)
    
    # Remove emojis and other unsupported Unicode characters
    # Keep only ASCII printable characters plus basic Latin extended
    text = re.sub(r'[^\x00-\x7F\xA0-\xFF]+', '', text)
    
    # Remove any remaining problematic characters
    text = text.encode('latin-1', errors='ignore').decode('latin-1')
    
    return text

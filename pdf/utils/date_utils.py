from datetime import datetime

def format_date(raw_date):
    """Convert datetime or string to DD/MM/YYYY format."""
    if not raw_date:
        return ""
    
    if isinstance(raw_date, datetime):
        return raw_date.strftime("%d/%m/%Y")
    
    return str(raw_date)

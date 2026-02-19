# backend/pdf/utils/text_utils.py

def sanitize_text(value):
    """
    Ensures text is safe for FPDF (Latin-1) by converting to string
    and replacing unsupported characters.
    """
    if value is None:
        return ""

    # Convert to string
    text = str(value)

    # Replace characters not supported by Latin-1
    return text.encode("latin-1", "replace").decode("latin-1")


def wrap_text(text, max_chars=80):
    """
    Splits long text into multiple lines for PDF rendering.
    """
    if not text:
        return [""]

    words = text.split()
    lines = []
    current = []
    count = 0

    for w in words:
        if count + len(w) + 1 > max_chars:
            lines.append(" ".join(current))
            current = [w]
            count = len(w)
        else:
            current.append(w)
            count += len(w) + 1

    if current:
        lines.append(" ".join(current))

    return lines


__all__ = ["sanitize_text", "wrap_text"]

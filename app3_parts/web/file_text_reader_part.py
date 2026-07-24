# PDF byte sniffing and text-file decoder.

def _looks_like_pdf_bytes(raw: bytes) -> bool:
    try:
        if not raw:
            return False
        head = raw[:1024]
        # Allow leading whitespace/newlines before %PDF
        return b"%PDF" in head
    except Exception:
        return False


def read_text_file(raw: bytes) -> str:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "utf-16", "latin-1"]
    for enc in encodings:
        try:
            txt = raw.decode(enc)
            if txt:
                txt = txt.replace("", "")
                return txt.strip()
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore").replace("", "").strip()

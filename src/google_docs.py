"""
Create a Google Doc formatted for A10 envelopes (4.125" x 9.5").
One envelope address block per page.
"""
from __future__ import annotations
import google.auth
from googleapiclient.discovery import build


# A10 envelope: 4.125 x 9.5 inches → points (1 inch = 914400 EMU, page units in pts = 72/inch)
# Google Docs page size is in EMU (914400 per inch)
_A10_W = int(9.5  * 914400)   # landscape: long edge = width
_A10_H = int(4.125 * 914400)
_MARGIN = int(0.5 * 914400)   # 0.5" margins


def _docs_service():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive"]
    )
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _drive_service():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_envelope_doc(rows: list[dict], zip_code: str) -> str:
    """
    rows: list of dicts with keys: owner_name, address, city, state, zip_code
    Returns the URL of the created Google Doc.
    """
    docs = _docs_service()

    # Create blank document
    doc = docs.documents().create(body={"title": f"A10 Envelopes — {zip_code}"}).execute()
    doc_id = doc["documentId"]

    # Set page size to A10 envelope (landscape)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"updateDocumentStyle": {
            "documentStyle": {
                "pageSize": {"width":  {"magnitude": _A10_W, "unit": "EMU"},
                             "height": {"magnitude": _A10_H, "unit": "EMU"}},
                "marginTop":    {"magnitude": _MARGIN, "unit": "EMU"},
                "marginBottom": {"magnitude": _MARGIN, "unit": "EMU"},
                "marginLeft":   {"magnitude": _MARGIN, "unit": "EMU"},
                "marginRight":  {"magnitude": _MARGIN, "unit": "EMU"},
            },
            "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight",
        }}
    ]}).execute()

    # Build text content: each address block separated by a page break
    requests = []
    insert_index = 1  # Google Docs body starts at index 1

    for i, row in enumerate(rows):
        name    = (row.get("owner_name") or "").strip()
        addr    = (row.get("address") or "").strip()
        city    = (row.get("city") or "").strip()
        state   = (row.get("state") or "").strip()
        zipcode = (row.get("zip_code") or "").strip()

        if not addr:
            continue

        city_line = ", ".join(filter(None, [city, state]))
        if zipcode:
            city_line = f"{city_line} {zipcode}".strip()

        lines = [l for l in [name, addr, city_line] if l]
        block = "\n".join(lines)

        if i > 0:
            # Page break before each envelope after the first
            requests.append({"insertPageBreak": {
                "location": {"index": insert_index}
            }})
            insert_index += 1

        requests.append({"insertText": {
            "location": {"index": insert_index},
            "text": block,
        }})
        insert_index += len(block)

    if requests:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    # Style all text: 12pt, centered, middle-align via paragraph style
    # Re-fetch to get accurate end index
    doc_content = docs.documents().get(documentId=doc_id).execute()
    body_end = doc_content["body"]["content"][-1]["endIndex"] - 1

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": body_end},
            "textStyle": {"fontSize": {"magnitude": 14, "unit": "PT"},
                          "weightedFontFamily": {"fontFamily": "Arial"}},
            "fields": "fontSize,weightedFontFamily",
        }},
        {"updateParagraphStyle": {
            "range": {"startIndex": 1, "endIndex": body_end},
            "paragraphStyle": {
                "alignment": "CENTER",
                "spaceAbove": {"magnitude": 36, "unit": "PT"},
            },
            "fields": "alignment,spaceAbove",
        }},
    ]}).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"

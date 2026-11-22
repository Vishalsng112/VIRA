"""Inline QR rendering without an external image service."""
import base64
import io


def qr_svg_data_uri(payload: str) -> str:
    """Render a payload as an inline SVG data URI so the UI stays offline."""
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"

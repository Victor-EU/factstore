"""A small PDF writer for supplier documents: text and rules on A4, with Chinese.

Latin text uses Helvetica. Text with Chinese uses Adobe's predefined STSong-Light font
with the UniGB-UCS2-H encoding, which PDF readers and text extractors know without the
font being embedded. Enough for proforma invoices, packing lists and inspection
reports that look and extract like the real thing.
"""

from dataclasses import dataclass, field

PAGE_W, PAGE_H = 595, 842


# Helvetica advance widths for printable ASCII (per 1000 em), from the standard AFM.
_HELVETICA = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
              556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
              722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
              278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
              556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]


def _is_cjk(c: str) -> bool:
    return ord(c) > 0x2E7F


def _has_cjk(text: str) -> bool:
    return any(_is_cjk(c) for c in text)


def width(text: str, size: float) -> float:
    """Approximate rendered width: Helvetica metrics for Latin, full em for Chinese."""
    total = 0
    for c in text:
        o = ord(c)
        total += 1000 if _is_cjk(c) else _HELVETICA[o - 32] if 32 <= o < 127 else 556
    return total * size / 1000


def fit(text: str, max_width: float, size: float) -> str:
    while text and width(text, size) > max_width:
        text = text[:-1]
    return text


def _runs(text: str):
    run, cjk = "", None
    for c in text:
        if cjk is None or _is_cjk(c) == cjk or c == " ":
            run += c
            cjk = _is_cjk(c) if cjk is None or c != " " else cjk
        else:
            yield run, cjk
            run, cjk = c, _is_cjk(c)
    if run:
        yield run, cjk


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _latin(text: str) -> str:
    return text.encode("cp1252", errors="replace").decode("cp1252")


@dataclass
class Page:
    ops: list[str] = field(default_factory=list)

    def text(self, x: float, y: float, text: str, size: float = 9, bold: bool = False) -> None:
        """Latin runs in Helvetica, Chinese runs in STSong-Light, laid end to end."""
        for run, cjk in _runs(text):
            if cjk:
                encoded = "".join(f"{ord(c):04X}" for c in run if ord(c) <= 0xFFFF)
                self.ops.append(f"BT /F3 {size} Tf {x:.1f} {y:.1f} Td <{encoded}> Tj ET")
            else:
                font = "/F2" if bold else "/F1"
                self.ops.append(f"BT {font} {size} Tf {x:.1f} {y:.1f} Td ({_escape(_latin(run))}) Tj ET")
            x += width(run, size)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        self.ops.append(f"{width} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

    def rect(self, x: float, y: float, w: float, h: float, width: float = 0.5) -> None:
        self.ops.append(f"{width} w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re S")


class Document:
    def __init__(self, title: str):
        self.title = title
        self.pages: list[Page] = []

    def page(self) -> Page:
        page = Page()
        self.pages.append(page)
        return page

    def save(self, path: str) -> None:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")  # placeholder, filled once the page tree exists
        pages_id = add(b"")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        descriptor = add(b"<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [-25 -254 1000 880] "
                         b"/ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 880 /StemV 93 >>")
        descendant = add(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
                         b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> "
                         b"/DW 1000 /W [1 95 500] /FontDescriptor " + str(descriptor).encode() + b" 0 R >>")
        f3 = add(b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H "
                 b"/DescendantFonts [" + str(descendant).encode() + b" 0 R] >>")
        resources = f"<< /Font << /F1 {f1} 0 R /F2 {f2} 0 R /F3 {f3} 0 R >> >>".encode()
        kids = []
        for page in self.pages:
            content = "\n".join(page.ops).encode("latin-1")
            stream = add(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
            kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                            f"/Resources ".encode() + resources + f" /Contents {stream} 0 R >>".encode()))
        objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                                 f"/Count {len(kids)} >>").encode()
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
        info = add(f"<< /Title ({_escape(_latin(self.title))}) /Producer (factstore fixture) >>".encode())

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        with open(path, "wb") as fh:
            fh.write(out)

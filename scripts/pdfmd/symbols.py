"""Adobe Symbol font is stored in the private-use area. Map it back to letters."""

from __future__ import annotations

# Byte of the Symbol encoding → Unicode. Only the slots that are not ASCII.
_BYTES = {
    0x22: "∀",
    0x24: "∃",
    0x27: "∋",
    0x20: " ",
    0x2A: "∗",
    0x2B: "+",
    0x2C: ",",
    0x2D: "−",
    0x30: "0",
    0x32: "2",
    0x33: "3",
    0x35: "5",
    0x37: "7",
    0x39: "9",
    0x3C: "<",
    0x3E: ">",
    # Symbol slot 0x3F is the question mark (hook plus a separate dot).
    0x3F: "?",
    0x40: "≅",
    0x41: "Α",
    0x42: "Β",
    0x43: "Χ",
    0x44: "Δ",
    0x45: "Ε",
    0x46: "Φ",
    0x47: "Γ",
    0x48: "Η",
    0x49: "Ι",
    0x4A: "ϑ",
    0x4B: "Κ",
    0x4C: "Λ",
    0x4D: "Μ",
    0x4E: "Ν",
    0x4F: "Ο",
    0x50: "Π",
    0x51: "Θ",
    0x52: "Ρ",
    0x53: "Σ",
    0x54: "Τ",
    0x55: "Υ",
    0x5B: "[",
    0x5D: "]",
    0x56: "ς",
    0x57: "Ω",
    0x58: "Ξ",
    0x59: "Ψ",
    0x5A: "Ζ",
    0x61: "α",
    0x62: "β",
    0x63: "χ",
    0x64: "δ",
    0x65: "ε",
    0x66: "φ",
    0x67: "γ",
    0x68: "η",
    0x69: "ι",
    0x6A: "ϕ",
    0x6B: "κ",
    0x6C: "λ",
    0x6D: "μ",
    0x6E: "ν",
    0x6F: "ο",
    0x70: "π",
    0x71: "θ",
    0x72: "ρ",
    0x73: "σ",
    0x74: "τ",
    0x75: "υ",
    0x76: "ϖ",
    0x77: "ω",
    0x78: "ξ",
    0x79: "ψ",
    0x7A: "ζ",
    0x7E: "~",
    # Symbol slots used as empty checkboxes in questionnaires.
    0x7F: "☐",
    0x86: "☐",
    0xA0: " ",
    # Symbol slot 0xA2 is a prime, written as «Г'».
    0xA2: "′",
    0xA3: "≤",
    0xA5: "∞",
    # Word stores a square list marker in the Symbol private-use slot.
    0xA7: "▪",
    # Symbol slot 0xAF is «↓», the pair of 0xAD «↑».
    0xAF: "↓",
    # Symbol slot 0xAD is «↑» (elevated labs), the pair of 0xAE «→».
    0xAD: "↑",
    # Symbol slot used as a right arrow in regimen tables.
    0xAE: "→",
    0xB0: "°",
    0xB1: "±",
    # Symbol slot 0xB3 is «≥», the pair of 0xA3 «≤».
    0xB3: "≥",
    0xB4: "×",
    0xB5: "∝",
    0xB7: "•",
    0xB8: "÷",
    0xB9: "≠",
    0xBA: "≡",
    0xBB: "≈",
    # Symbol slot 0xBE is an em-wide dash, the same width as «—», used as a list marker.
    0xBE: "—",
    0xD7: "⋅",
    # The same arrowhead in Wingdings and in the embedded CID font.
    0xD8: "►",
    # Symbol slot 0xE3 is the copyright sign («1990 ©»).
    0xE3: "©",
    # Wingdings check mark.
    0xFC: "✓",
}

# Slots whose picture depends on the font. Symbol's «1» is a Webdings checkbox.
_WINGDINGS = {0xB2: "✦", 0xE9: "↑", 0xEA: "↓", 0xFC: "✓"}
_WINGDINGS2 = {0x97: "•"}
_WEBDINGS = {0x31: "☐"}
_OPEN = {"\ue12c": "•", "\ue46f": "▪"}

PUA = {chr(0xF000 + byte): char for byte, char in _BYTES.items()}


def map_symbol(text: str, font: str = "") -> str:
    if not any(0xE000 <= ord(ch) <= 0xF8FF for ch in text):
        return text
    name = font.lower().replace(" ", "")
    if "wingdings2" in name:
        extra = _WINGDINGS2
    elif "wingding" in name:
        extra = _WINGDINGS
    elif "webding" in name:
        extra = _WEBDINGS
    else:
        extra = {}
    out = []
    for ch in text:
        if ch in _OPEN and ("opensymbol" in name or not name):
            out.append(_OPEN[ch])
            continue
        byte = ord(ch) - 0xF000
        if 0 <= byte <= 0xFF and byte in extra:
            out.append(extra[byte])
            continue
        # Webdings stores a checkbox where Symbol stores the digit 1.
        if byte == 0x31:
            if name and "webding" not in name:
                out.append("1")
            else:
                out.append(ch)
            continue
        if ch in PUA and not extra:
            out.append(PUA[ch])
            continue
        out.append(ch)
    return "".join(out)

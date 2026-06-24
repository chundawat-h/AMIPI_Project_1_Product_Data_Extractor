from dotenv import load_dotenv
load_dotenv()

"""
AMIPI Product Data Extractor
=============================
Extracts structured product data from messy jewelry/diamond descriptions.

Architecture:
  - AI (Gemini gemini-2.5-flash) handles flexible NL understanding:
      style_number extraction, category, stone type, carat weight.
  - Deterministic validation rules handle:
      style number parsing, metal group mapping, lab-grown detection,
      design ID derivation, brand mapping, confidence scoring.
"""

import os
import re
import json
import csv
import argparse
import sys
from typing import Optional

# ─────────────────────────────────────────────────
#  DETERMINISTIC VALIDATION RULES
# ─────────────────────────────────────────────────

METAL_LABELS = {
    "14W": "14K White Gold",
    "14Y": "14K Yellow Gold",
    "14R": "14K Rose Gold",
    "18W": "18K White Gold",
    "18Y": "18K Yellow Gold",
    "18R": "18K Rose Gold",
    "PT":  "Platinum",
}

# Rule: Metal group mapping (from instructions)
METAL_GROUP_MAP = {
    "14W": "14K", "14Y": "14K", "14R": "14K",
    "18W": "18K", "18Y": "18K", "18R": "18K",
    "PT":  "PT",
}

# Rule: Color stones (from instructions)
COLOR_STONES = {"EMERALD", "RUBY", "SAPPHIRE"}

KNOWN_QUALITY_CODES = {
    "VS", "VS1", "VS2", "VVS", "VVS1", "VVS2",
    "SI", "SI1", "SI2", "FG", "GH", "DEF", "EF",
    "S", "EM", "RA"
}

# Rule: Style number pattern (optional L + letter + 6 digits + hyphen + suffix)
STYLE_PATTERN = re.compile(r"^(L?)([A-Z]\d{6})-([A-Z0-9]+)$", re.IGNORECASE)


def parse_style_number(style_number: str) -> dict:
    """
    DETERMINISTIC: Parse a full style number into components.
    Implements rules from the instructions:
      - Lab-grown prefix detection (leading L)
      - Parent derivation
      - Design ID = first 4 chars of parent after removing leading L
      - Metal code and group from suffix
    """
    if not style_number:
        return {}

    m = STYLE_PATTERN.match(style_number.strip())
    if not m:
        return {"parse_error": f"Style '{style_number}' does not match expected pattern (L?)(Letter)(6 digits)-(suffix)"}

    lab_prefix, base_part, suffix = m.group(1), m.group(2), m.group(3)
    is_lab_grown = lab_prefix.upper() == "L"                    # Rule: L prefix = lab-grown

    parent = (lab_prefix + base_part).upper()                   # e.g. LB401400 or B401400

    # Rule: Design ID = first 4 chars of parent AFTER stripping leading L
    clean_for_design = base_part.upper()                        # strip L, keep B401400 → B401
    design_id = clean_for_design[:4].upper()

    metal, quality = _parse_suffix(suffix.upper())
    metal_group = METAL_GROUP_MAP.get(metal) if metal else None  # Rule: metal group map

    return {
        "is_lab_grown": is_lab_grown,
        "parent":       parent,
        "design_id":    design_id,
        "metal":        metal,
        "metal_group":  metal_group,
        "quality":      quality,
    }


def _parse_suffix(suffix: str) -> tuple[Optional[str], Optional[str]]:
    """
    DETERMINISTIC: Extract metal code then quality from style suffix.
    Longest-match first to handle e.g. 'PTVVS2' → metal=PT, quality=VVS2.
    """
    for metal in sorted(METAL_LABELS.keys(), key=len, reverse=True):
        if suffix.startswith(metal):
            quality = suffix[len(metal):] or None
            return metal, quality
    return None, suffix or None


def brand_from_lab_grown(is_lab_grown: bool) -> str:
    """DETERMINISTIC rule: ALAB for lab-grown, AMIPI for natural."""
    return "ALAB" if is_lab_grown else "AMIPI"


def normalise_stone_type(ai_stone_type: str, is_lab_grown: bool) -> str:
    """
    DETERMINISTIC post-processing: normalise the AI's stone type output
    to one of the canonical values.
    """
    if not ai_stone_type:
        return "Lab-Grown Diamond" if is_lab_grown else "Natural Diamond"

    upper = ai_stone_type.upper()

    # Color stone detection (from instructions)
    for cs in COLOR_STONES:
        if cs in upper:
            if "DIAMOND" in upper:
                return f"Diamond + {cs.title()}"
            return cs.title()

    if "LAB" in upper or is_lab_grown:
        return "Lab-Grown Diamond"
    return "Natural Diamond"


def compute_confidence(parsed: dict, ai_result: dict) -> float:
    """
    DETERMINISTIC scoring based on how many fields were successfully resolved.
    """
    score = 0.0
    if not parsed.get("parse_error"):    score += 0.30
    if parsed.get("metal"):              score += 0.15
    if parsed.get("metal_group"):        score += 0.10
    q = parsed.get("quality") or ai_result.get("quality")
    if q:
        score += 0.10
        if q.upper() in KNOWN_QUALITY_CODES: score += 0.05
    if ai_result.get("stone_type"):      score += 0.10
    if ai_result.get("category"):        score += 0.10
    if ai_result.get("carat_weight") is not None: score += 0.10
    return round(min(score, 1.0), 2)


# ─────────────────────────────────────────────────
#  AI EXTRACTION  (Gemini)
# ─────────────────────────────────────────────────

AI_SYSTEM_PROMPT = """You are a jewelry product data extraction assistant specializing in diamond and gemstone products.
Given a messy product description, extract ONLY these fields as a valid JSON object.
Return ONLY the JSON — no markdown fences, no preamble, no explanation.

{
  "style_number": "<full style number including metal/quality suffix, as it appears in the text; e.g. B401400-14WVS or LB401400-14WVS>",
  "stone_type": "<choose one: Natural Diamond | Lab-Grown Diamond | Ruby | Emerald | Sapphire | Diamond + Ruby | Diamond + Emerald | Diamond + Sapphire>",
  "category": "<choose one: Band | Ring | Pendant | Necklace | Bracelet | Earrings>",
  "carat_weight": <numeric value, or null>,
  "quality": "<diamond/color-grade code visible in text, e.g. VS, VS1, VVS2, SI, FG, GH, DEF, RA, EM; null if absent>",
  "notes_or_warnings": ["<list any ambiguities, missing data, or assumptions>"]
}

Key hints:
- Style numbers start the description: look for a code like B401400-14WVS or LB401400-14WVS.
- L prefix before the style code means lab-grown (e.g. LB401400).
- Carat weight follows keywords: cttw, ctw, ct.
- Quality codes appear in the suffix or inline: VS, VVS2, SI, FG, GH, DEF, RA, etc.
- Color stone combos: 'alternate', 'half and half', 'half diamond half color stone'.
"""


def ai_extract(raw_text: str, api_key: str) -> dict:
    """
    AI component: use Gemini for flexible natural-language understanding.
    Returns the parsed AI fields dict.
    """
    import urllib.request, urllib.error

    payload = json.dumps({
        "systemInstruction": {
            "parts": [{"text": AI_SYSTEM_PROMPT}]
        },
        "contents": [{
            "parts": [{"text": raw_text}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```json\s*|```$", "", text, flags=re.MULTILINE).strip()
            return json.loads(text)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"notes_or_warnings": [f"HTTP {e.code}: {body[:200]}"]}
    except json.JSONDecodeError as e:
        return {"notes_or_warnings": [f"JSON parse error from AI: {e}"]}
    except KeyError as e:
        return {"notes_or_warnings": [f"Unexpected API response format: {e}"]}
    except Exception as e:
        return {"notes_or_warnings": [f"AI call failed: {e}"]}


# ─────────────────────────────────────────────────
#  PIPELINE
# ─────────────────────────────────────────────────

def process_row(row_id: int, raw_text: str, api_key: str) -> dict:
    """Full pipeline for one row: AI → deterministic validation → merge."""
    warnings = []

    # 1. AI extraction (flexible NL understanding)
    ai = ai_extract(raw_text, api_key)
    warnings += ai.pop("notes_or_warnings", []) or []

    # 2. Deterministic: parse style number from what AI found
    style_number = (ai.get("style_number") or "").strip()
    parsed = parse_style_number(style_number)

    if parsed.get("parse_error"):
        warnings.append(parsed["parse_error"])

    # 3. Deterministic: quality (suffix from style number wins over AI inline)
    quality = parsed.get("quality") or ai.get("quality")

    # 4. Deterministic: stone type normalisation
    is_lab_grown = parsed.get("is_lab_grown", False)
    stone_type = normalise_stone_type(ai.get("stone_type", ""), is_lab_grown)

    # 5. Deterministic: brand mapping
    brand = brand_from_lab_grown(is_lab_grown)

    # 6. Deterministic: confidence score
    conf = compute_confidence(parsed, {**ai, "stone_type": stone_type, "quality": quality})

    # 7. Carat weight cleanup
    carat_weight = ai.get("carat_weight")
    if isinstance(carat_weight, str):
        try:
            carat_weight = float(re.sub(r"[^\d.]", "", carat_weight))
        except ValueError:
            warnings.append(f"Could not parse carat_weight value: {carat_weight!r}")
            carat_weight = None

    return {
        "id":                row_id,
        "raw_product_text":  raw_text,
        "style_number":      style_number or None,
        "parent":            parsed.get("parent"),
        "design_id":         parsed.get("design_id"),
        "metal":             parsed.get("metal"),
        "metal_group":       parsed.get("metal_group"),
        "quality":           quality,
        "stone_type":        stone_type,
        "category":          ai.get("category"),
        "is_lab_grown":      is_lab_grown,
        "brand":             brand,
        "carat_weight":      carat_weight,
        "confidence_score":  conf,
        "notes_or_warnings": warnings,
    }


def run(input_csv: str, output_json: str, output_csv: str, api_key: str):
    """Read input CSV, process all rows, write JSON and CSV outputs."""
    try:
        with open(input_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"ERROR: Input file not found: {input_csv}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("WARNING: Input CSV is empty. Nothing to process.")
        return

    results = []
    for row in rows:
        row_id = row.get("id", "?")
        raw_text = row.get("raw_product_text", "").strip()

        if not raw_text:
            results.append({
                "id": row_id, "raw_product_text": "",
                "notes_or_warnings": ["Empty raw_product_text — skipped"],
                "confidence_score": 0.0,
            })
            continue

        print(f"  [{row_id:>2}] {raw_text[:65]}...")
        result = process_row(int(row_id), raw_text, api_key)
        results.append(result)
        print(f"       → {result['style_number']} | {result['stone_type']} | {result['category']} | conf={result['confidence_score']}")

    # Write JSON
    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Write CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in results:
                w.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in r.items()})

    print(f"\n✓ {len(results)} records written.")
    print(f"  JSON → {output_json}")
    print(f"  CSV  → {output_csv}")
    return results


# ─────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AMIPI Product Data Extractor: converts messy jewelry descriptions to structured data."
    )
    parser.add_argument("--input",       default="data/product_descriptions.csv")
    parser.add_argument("--output-json", default="outputs/extracted_products.json")
    parser.add_argument("--output-csv",  default="outputs/extracted_products.csv")
    parser.add_argument(
        "--single", metavar="TEXT",
        help="Extract a single description from the command line (skips CSV)"
    )
    args = parser.parse_args()

    # api_key = os.environ.get("ANTHROPIC_API_KEY")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set the GEMINI_API_KEY environment variable first.", file=sys.stderr)
        sys.exit(1)

    if args.single:
        result = process_row(0, args.single, api_key)
        print(json.dumps(result, indent=2))
    else:
        run(args.input, args.output_json, args.output_csv, api_key)
# AMIPI Product Data Extractor

**Project 1 — AI Intern Assignment**  
Converts messy jewelry / diamond product descriptions into clean, structured JSON + CSV.

---

## Overview

Jewelry product descriptions are inconsistent, abbreviated, and written in varying orders. This tool solves that by combining:

| Layer | Responsibility |
|---|---|
| **Gemini (gemini-2.5-flash)** | Flexible natural-language understanding — extracts style number as written, stone type, product category, carat weight, and quality from freeform text. |
| **Deterministic validation rules** | Style-number parsing, metal group mapping, lab-grown detection, design ID derivation, brand mapping, confidence scoring. These rules are hard-coded from the business spec and never rely on AI guessing. |

---

## Quick Start

### 1. Prerequisites

- Python **3.10+** (uses built-in `tuple[...]` type hints)
- A [Gemini API key](https://aistudio.google.com/)
- Uses minimal dependencies (`python-dotenv` for loading the `.env` file)

### 2. Clone repo
run this on your terminal:
```bash
git clone https://github.com/chundawat-h/AMIPI_Project_1_Product_Data_Extractor.git
cd AMIPI_Project_1_Product_Data_Extractor
```

### 3. Set your API key

Create a `.env` file in the root directory and add your key:

```env
GEMINI_API_KEY="your-gemini-api-key"
```

### 3. Run on the full CSV

```bash
python extractor.py
```

Defaults:
- Input:  `data/product_descriptions.csv`
- Output: `outputs/extracted_products.json` and `outputs/extracted_products.csv`

Override paths:

```bash
python extractor.py \
  --input data/product_descriptions.csv \
  --output-json outputs/my_results.json \
  --output-csv  outputs/my_results.csv
```

### 4. Extract a single description (no CSV needed)

```bash
python extractor.py --single "B401400-14WVS Natural Diamond Band, 1.20cttw, round diamonds"
```

---

## Project Structure

```
product-extractor/
├── extractor.py                  # Main script (all logic here)
├── requirements.txt              # Documents pip dependencies like python-dotenv
├── README.md                     # This file
├── data/
│   └── product_descriptions.csv  # Input data (do not edit)
└── outputs/
    ├── extracted_products.json   # Full structured output (JSON)
    └── extracted_products.csv    # Same data as CSV
```

---

## Output Fields

| Field | Source | Description |
|---|---|---|
| `id` | Input CSV | Row identifier |
| `raw_product_text` | Input CSV | Original messy description |
| `style_number` | **AI** | Full style number as parsed from text |
| `parent` | **Deterministic** | Style number without metal/quality suffix |
| `design_id` | **Deterministic** | First 4 chars of parent (after stripping leading L) |
| `metal` | **Deterministic** | Metal code parsed from suffix (14W, 18Y, PT, etc.) |
| `metal_group` | **Deterministic** | 14K / 18K / PT — grouped per business rule |
| `quality` | **Deterministic** (suffix) + AI fallback | VS, VVS2, SI, FG, GH, DEF, etc. |
| `stone_type` | AI + **Deterministic normalisation** | Natural Diamond, Lab-Grown Diamond, Ruby, Diamond + Emerald, etc. |
| `category` | **AI** | Band, Ring, Pendant, Necklace, Bracelet, Earrings |
| `is_lab_grown` | **Deterministic** | `true` if style number starts with L |
| `brand` | **Deterministic** | AMIPI (natural) or ALAB (lab-grown) |
| `carat_weight` | **AI** | Numeric carat weight (cttw / ctw / ct) |
| `confidence_score` | **Deterministic** | 0.0–1.0 based on fields resolved (see scoring below) |
| `notes_or_warnings` | Both | List of ambiguities, assumptions, or parse errors |

---

## Deterministic Validation Rules

These rules are implemented in code and **never** rely on AI interpretation.

### 1. Style Number Pattern

```
(L?) (Letter) (6 digits) - (suffix)
e.g.  B401400-14WVS   or   LB401400-14WVS
```

Regex: `^(L?)([A-Z]\d{6})-([A-Z0-9]+)$`

### 2. Lab-Grown Detection

A leading `L` before the style code means lab-grown.  
`LB401400` → `is_lab_grown = True`

### 3. Parent Derivation

Parent = full style base without the metal/quality suffix.  
`LB401400-14WVS` → parent = `LB401400`

### 4. Design ID Derivation

Design ID = first 4 characters of the base code **after removing the leading L**.  
`LB401400` → strip L → `B401400` → first 4 → `B401`  
`B501200`  → `B501`

### 5. Suffix Parsing (Metal + Quality)

The suffix is split by matching the longest known metal code as a prefix:

| Metal code | Meaning |
|---|---|
| 14W | 14K White Gold |
| 14Y | 14K Yellow Gold |
| 14R | 14K Rose Gold |
| 18W | 18K White Gold |
| 18Y | 18K Yellow Gold |
| 18R | 18K Rose Gold |
| PT  | Platinum |

Remaining characters after the metal code = quality (VS, VVS2, FG, etc.).

Example: `PTVVS2` → metal=`PT`, quality=`VVS2`

### 6. Metal Group Mapping

| Codes | Group |
|---|---|
| 14W, 14Y, 14R | 14K |
| 18W, 18Y, 18R | 18K |
| PT | PT |

### 7. Brand Mapping

| Condition | Brand |
|---|---|
| `is_lab_grown = True` | ALAB |
| `is_lab_grown = False` | AMIPI |

### 8. Color Stone Classification

Color stones: `Emerald`, `Ruby`, `Sapphire`  
If a color stone AND diamond both appear → `Diamond + {Stone}`  
If color stone only → `{Stone}` (e.g. `Ruby`)

### 9. Confidence Scoring

| Criterion | Points |
|---|---|
| Style number parsed cleanly | +0.30 |
| Metal code identified | +0.15 |
| Metal group resolved | +0.10 |
| Quality code found | +0.10 |
| Quality is a known code | +0.05 |
| Stone type resolved | +0.10 |
| Category resolved | +0.10 |
| Carat weight found | +0.10 |
| **Max** | **1.00** |

---

## Where AI Is Used vs Deterministic Rules

```
Raw text
   │
   ▼
[AI: Gemini gemini-2.5-flash]
   Extracts: style_number (as written), stone_type (freeform),
             category, carat_weight, quality (inline)
   │
   ▼
[Deterministic rules]
   parse_style_number()    → parent, design_id, metal, metal_group, is_lab_grown
   brand_from_lab_grown()  → AMIPI / ALAB
   normalise_stone_type()  → canonical stone type string
   compute_confidence()    → 0.0–1.0 score
   │
   ▼
Merged output record
```

**Why this split?**  
AI excels at reading messy, inconsistent phrasing ("F-G quality", "18 white", "half emerald half diamond").  
Deterministic rules guarantee correctness on structured fields — a pure AI prompt could hallucinate metal groups or misidentify lab-grown status. The rules are auditable and testable.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `GEMINI_API_KEY` not set | Prints a clear error and exits with code 1 |
| Input CSV not found | Prints `ERROR: Input file not found:` and exits |
| Empty `raw_product_text` row | Skipped; logged in `notes_or_warnings` with `confidence_score = 0.0` |
| Style number doesn't match pattern | `parse_error` logged in `notes_or_warnings`; deterministic fields are `null` |
| AI returns invalid JSON | Error caught; logged in `notes_or_warnings`; deterministic fields still populated |
| AI HTTP error (rate limit, auth) | Error caught; logged in `notes_or_warnings`; row still emitted with partial data |
| Non-numeric `carat_weight` from AI | Cleaned with regex; if still unparseable, set to `null` and warned |

---

## Sample Outputs

### Sample 1 — Natural Diamond Band (row 1)

```json
{
  "id": 1,
  "raw_product_text": "B401400-14WVS Natural Diamond Band, 1.20cttw, round diamonds, size 6.5",
  "style_number": "B401400-14WVS",
  "parent": "B401400",
  "design_id": "B401",
  "metal": "14W",
  "metal_group": "14K",
  "quality": "VS",
  "stone_type": "Natural Diamond",
  "category": "Band",
  "is_lab_grown": false,
  "brand": "AMIPI",
  "carat_weight": 1.2,
  "confidence_score": 1.0,
  "notes_or_warnings": []
}
```

### Sample 2 — Lab-Grown Diamond Pendant (row 5)

```json
{
  "id": 5,
  "raw_product_text": "LB701100-18WFG Lab diamond pendant, F-G quality, 0.95cttw",
  "style_number": "LB701100-18WFG",
  "parent": "LB701100",
  "design_id": "B701",
  "metal": "18W",
  "metal_group": "18K",
  "quality": "FG",
  "stone_type": "Lab-Grown Diamond",
  "category": "Pendant",
  "is_lab_grown": true,
  "brand": "ALAB",
  "carat_weight": 0.95,
  "confidence_score": 1.0,
  "notes_or_warnings": []
}
```

### Sample 3 — Lab-Grown Diamond Bracelet, Platinum (row 11)

```json
{
  "id": 11,
  "raw_product_text": "LB445500-PTVVS2 Lab diamond bracelet platinum VVS2 3.25cttw",
  "style_number": "LB445500-PTVVS2",
  "parent": "LB445500",
  "design_id": "B445",
  "metal": "PT",
  "metal_group": "PT",
  "quality": "VVS2",
  "stone_type": "Lab-Grown Diamond",
  "category": "Bracelet",
  "is_lab_grown": true,
  "brand": "ALAB",
  "carat_weight": 3.25,
  "confidence_score": 1.0,
  "notes_or_warnings": []
}
```

---

## Edge Cases Handled

| Row | Description | Handling |
|---|---|---|
| Row 9 — `B221100-18W` | No quality in suffix; only metal code | Quality = `null`; confidence penalised |
| Row 10 — `B332200-14Y SI` | Space before quality code in raw text | AI reconstructs style number; deterministic parses correctly |
| Row 12 — `B778800-18R` | No quality, no carat weight | Both null; confidence = 0.75 |
| Row 15 — `B998877-14RS Ruby color stone only` | Color stone only, no diamond | stone_type = "Ruby"; brand = AMIPI |

---

## Notes on AI Usage

- The AI prompt uses a **structured JSON schema** with explicit field names and value enumerations to constrain outputs.
- Inline hints ("Key hints:" section in the system prompt) reduce hallucination on jewelry-specific terminology.
- The AI is **not trusted** for style number parsing, metal groups, lab-grown status, or brand — those are validated deterministically after the AI call.
- If the AI returns malformed JSON, the row is still processed with deterministic fields populated from the raw text where possible.

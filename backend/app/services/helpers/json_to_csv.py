"""
json_to_csv.py
--------------
Converts the BSE/NSE quarterly results JSON (as returned by the API)
into the structured CSV format used for financial reporting.

Usage:
    python json_to_csv.py result.json output.csv

The script reads the nested JSON structure, extracts each quarter's data
from the `resCmpData` array, and writes a pivot-style CSV where:
  - Rows  = financial line items
  - Columns = quarters (most recent first, as returned in the JSON)
"""

import json
import csv
import sys
import os
import io


# ── Helper ──────────────────────────────────────────────────────────────────

def fmt(value, dash_if_none=True):
    """Return the raw value as-is, or '-' for null/None."""
    if value is None or value == "":
        return "-" if dash_if_none else ""
    return str(value)


def res_type_label(code):
    """Map re_res_type code to a human-readable audit label."""
    mapping = {"U": "UNAUDITED", "A": "AUDITED"}
    return mapping.get(code, code)


# ── Row definitions ──────────────────────────────────────────────────────────
# Each entry is either:
#   ("Label", "json_key")        → numeric cell, formatted with commas
#   ("Label", None)              → always '-'
#   ("Label", "__zero__")        → always '0'
#   ("Label", "__empty__")       → always '' (section header)
#   ("Label", "__part__")        → section marker row

ROWS = [
    # Section headers (no data)
    ("Part 1",                                                          "__empty__"),
    ("Revenue from operations",                                         "__empty__"),
    ("Revenue from operations",                                         "re_net_sale"),
    ("Other income",                                                    "re_oth_inc_new"),
    ("Total income",                                                    "re_total_inc"),
    ("Expenses",                                                        "__empty__"),
    ("(a) Cost of materials consumed",                                  "re_rawmat_consump"),
    ("(b) Purchases of stock-in-trade",                                 "re_pur_trd_goods"),
    ("(c) Changes in inventories of finished goods, work-in-progress and stock-in-trade", "re_int_new"),
    ("(d) Employee benefits expense",                                   "re_staff_cost"),
    ("(e) Finance costs",                                               "re_int_new"),
    ("(f) Depreciation and amortisation expense",                       "re_depr_und_exp"),
    ("(g) Other expenses",                                              "re_oth_exp"),
    ("Total Expenses",                                                  "re_oth_tot_exp"),
    ("Profit / (Loss) before exceptional items and tax",               None),
    ("Exceptional items",                                               "re_excepn_items_new"),
    ("Profit / (Loss) before tax",                                      "re_pro_loss_bef_tax"),
    ("Tax Expenses",                                                    "__empty__"),
    ("Current Tax",                                                     "re_curr_tax"),
    ("Deferred Tax",                                                    "re_deff_tax"),
    ("Total Tax expense",                                               "re_tax"),
    ("Net movement in regulatory deferral account balances related to profit or loss and the related deferred tax movement", None),
    ("Profit (Loss) for the period from continuing operations",         "re_con_pro_loss"),
    ("Profit / (loss) from discontinued operations",                    "re_pro_los_frm_dis_opr"),
    ("Tax expense of discontinued operations",                          "re_tax_expens_of_dis_opr"),
    ("Profit / (loss) from Discontinued operations (after tax)",        "re_prolos_dis_opr_aftr_tax"),
    ("Profit / (loss) for the period",                                  None),
    ("Share of profit / (loss) of associates",                          "re_share_associate"),
    ("Consolidated Net Profit / Loss for the period",                   "re_proloss_ord_act"),
    ("Other comprehensive income",                                      None),
    ("Total comprehensive income",                                      None),
    ("Total profit or loss, attributable to",                           "__empty__"),
    ("Profit or loss, attributable to owners of parent",               None),
    ("Total profit or loss, attributable to non-controlling interests", None),
    ("Total Comprehensive income for the period attributable to",       "__empty__"),
    ("Comprehensive income for the period attributable to owners of parent", None),
    ("Total comprehensive income for the period attributable to owners of parent non-controlling interests", None),
    ("Details of equity share capital",                                 "__empty__"),
    ("Paid-up equity share capital",                                    "re_pdup"),
    ("Face Value(in Rs.)",                                              "re_face_val"),
    ("Details of debt securities",                                      "__empty__"),
    ("Paid-up debt capital",                                            None),
    ("Face value of debt securities (in Rs.)",                          None),
    ("Reserve excluding Revaluation Reserves as per balance sheet of previous accounting year", None),
    ("Debenture redemption reserve",                                    None),
    ("Earnings per share",                                              "__empty__"),
    ("Earnings per equity share for continuing operations",             "__empty__"),
    ("Basic EPS for continuing operations",                             None),
    ("Diluted EPS for continuing operations",                           None),
    ("Earnings per equity share for discontinued operations",           "__empty__"),
    ("Basic EPS for continued and discontinued operations",             None),
    ("Diluted EPS for discontinued operations",                         None),
    ("Earnings per equity share",                                       "__empty__"),
    ("Basic EPS for continued and discontinued operations",             "re_basic_eps_for_cont_dic_opr"),
    ("Diluted EPS for continued and discontinued operations",           "re_dilut_eps_for_cont_dic_opr"),
    ("Debt equity ratio (in %)",                                        None),
    ("Debt service coverage ratio (in %)",                              None),
    ("Interest service coverage ratio (in %)",                          None),
]


# ── Main conversion logic ────────────────────────────────────────────────────

def convert(input_path: str, output_path: str):
    # Load JSON from file and delegate to dict-based converter
    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    csv_text = dict_to_csv_text(raw)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        f.write(csv_text)

    # Count rows for the print message: header rows + data rows
    # Extract quarters length to compute rows
    if isinstance(raw, dict) and "stdout" in raw:
        raw = json.loads(raw["stdout"])
    quarters = raw.get("resCmpData", [])
    data_row_count = len(ROWS)
    print(f"✅  Written {data_row_count} rows × {len(quarters)} quarters → {output_path}")


def dict_to_csv_text(raw: dict) -> str:
    """Convert loaded JSON (dict) into CSV text and return it.

    The function accepts the same structure expected by `convert` (including
    the outer wrapper with `stdout`) and returns the CSV as a string.
    """
    # Handle the outer wrapper: {"returncode":0, "stdout": "<json string>"}
    if isinstance(raw, dict) and "stdout" in raw:
        raw = json.loads(raw["stdout"])

    quarters = raw.get("resCmpData", [])
    if not quarters:
        raise ValueError("No data found in 'resCmpData' key.")

    # Build header rows
    quarter_dates = [q.get("re_to_dt", "") for q in quarters]
    audit_labels = [res_type_label(q.get("re_res_type")) for q in quarters]

    header_row1 = ["QUARTER ENDED"] + quarter_dates
    header_row2 = ["PARTICULARS"] + audit_labels

    # Build data rows
    data_rows = []
    for label, key in ROWS:
        if key == "__empty__":
            row = [label] + [""] * len(quarters)
        elif key is None:
            row = [label] + ["-"] * len(quarters)
        elif key == "__zero__":
            row = [label] + ["0"] * len(quarters)
        else:
            cells = []
            for q in quarters:
                raw_val = q.get(key)
                if raw_val == "0" or raw_val == 0:
                    cells.append("0")
                else:
                    cells.append(fmt(raw_val))
            row = [label] + cells
        data_rows.append(row)

    # Write CSV into a string buffer
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="|", quoting=csv.QUOTE_ALL)
    writer.writerow(header_row1)
    writer.writerow(header_row2)
    for row in data_rows:
        writer.writerow(row)

    return buf.getvalue()


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python json_to_csv.py <input.json> <output.csv>")
        sys.exit(1)

    input_file  = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.exists(input_file):
        print(f"Error: '{input_file}' not found.")
        sys.exit(1)

    convert(input_file, output_file)
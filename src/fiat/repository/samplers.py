import csv
import json
from pathlib import Path


def sample_notebook_content(raw_text: str, max_chars: int = 4000) -> tuple[str, dict]:
    try:
        data = json.loads(raw_text)
        cells = data.get("cells", [])
        if not isinstance(cells, list):
            raise ValueError()
    except Exception:
        return raw_text[:max_chars], {"sampler": "notebook_fallback", "truncated": len(raw_text) > max_chars}

    lines = []
    total_len = 0
    included_count = 0
    omitted_outputs_count = 0

    for idx, cell in enumerate(cells):
        ctype = cell.get("cell_type")
        source_raw = cell.get("source", "")
        source = "".join(source_raw) if isinstance(source_raw, list) else str(source_raw)
        
        cell_text = ""
        if ctype == "markdown":
            cell_text = f"# [MD Cell {idx}]\n{source.strip()[:400]}"
        elif ctype == "code":
            cell_text = f"# [Code Cell {idx}]\n{source.strip()[:800]}"
            for out in cell.get("outputs", []):
                out_type = out.get("output_type")
                if out_type == "error":
                    ename = out.get("ename", "Error")
                    evalue = out.get("evalue", "")
                    tb = "\n".join(out.get("traceback", []))[-300:]
                    cell_text += f"\n# [Cell {idx} Error] {ename}: {evalue}\n{tb}"
                else:
                    omitted_outputs_count += 1

        if total_len + len(cell_text) > max_chars and included_count > 0:
            break
        lines.append(cell_text)
        total_len += len(cell_text) + 1
        included_count += 1

    formatted = "\n\n".join(lines)
    return formatted, {
        "sampler": "ipynb",
        "total_cells": len(cells),
        "included_cells": included_count,
        "omitted_outputs_count": omitted_outputs_count,
        "truncated": total_len >= max_chars
    }

def sample_tabular_content(file_path: Path, max_chars: int = 2000, max_scan_lines: int = 10000, sample_rows: int = 5) -> tuple[str, dict]:
    delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
    headers = []
    rows_data: list[list[str]] = []
    row_count = 0
    row_count_capped = False

    try:
        with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            try:
                headers = [str(h)[:64] for h in next(reader)]
            except StopIteration:
                return "[Empty Tabular File]", {"sampler": "tabular", "columns": 0, "rows_counted": 0}

            for row in reader:
                row_count += 1
                if len(rows_data) < sample_rows:
                    rows_data.append([str(c)[:80] for c in row])
                if row_count >= max_scan_lines:
                    row_count_capped = True
                    # finish counting without loading all into memory
                    for _ in reader:
                        row_count += 1
                    break
    except Exception as e:
        return f"[Error reading tabular file: {e}]", {"sampler": "tabular_error"}

    # infer types
    col_types = []
    for col_idx in range(len(headers)):
        vals = [r[col_idx] for r in rows_data if col_idx < len(r) and r[col_idx].strip() != ""]
        if not vals:
            col_types.append("empty")
            continue
        try:
            [int(v) for v in vals]
            col_types.append("int")
            continue
        except ValueError:
            pass
        try:
            [float(v) for v in vals]
            col_types.append("float")
            continue
        except ValueError:
            pass
        if all(v.lower() in {"true", "false"} for v in vals):
            col_types.append("bool")
            continue
        col_types.append("str")

    cols_desc = ", ".join(
        f"{h} ({t})" for h, t in zip(headers, col_types, strict=False)
    )
    sample_lines = [f"{i+1}: {','.join(r)}" for i, r in enumerate(rows_data)]
    
    summary = f"[Tabular Summary: {row_count}{'+' if row_count_capped else ''} rows x {len(headers)} cols]\n"
    summary += f"Columns: {cols_desc}\nSample Rows:\n" + "\n".join(sample_lines)
    
    if len(summary) > max_chars:
        summary = summary[:max_chars]

    return summary, {
        "sampler": "tabular",
        "columns": len(headers),
        "rows_counted": row_count,
        "row_count_capped": row_count_capped,
        "truncated": len(summary) >= max_chars
    }

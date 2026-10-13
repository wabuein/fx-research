from __future__ import annotations

import csv
from pathlib import Path

from fxresearch.paths import relative_to_root


class ReportWriter:

    def __init__(self, echo: bool = True, flush: bool = False) -> None:
        self.echo = echo
        self.flush = flush

        self.lines: list[str] = []

    def out(self, line: str = "") -> None:
        if self.echo: print(line, flush=self.flush)
        self.lines.append(line)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n")


def write_rows(path: Path, rows: list[dict], empty_header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()) if rows else [empty_header])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def announce(path: Path) -> None:
    print(f"Wrote {relative_to_root(path)}")

import os
import re
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


APP_TITLE = "PDF Rechnungs-Umbenenner"


def clean_filename_part(value: str, fallback: str = "Unbekannt") -> str:
    value = (value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|]", "-", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._- ")
    return value or fallback


def extract_text_from_pdf(path: Path) -> str:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber ist nicht installiert.")
    text_parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def find_invoice_number(text: str) -> str:
    patterns = [
        r"(?:Rechnung(?:s)?(?:nummer|nr\.?|-Nr\.?)|Rechnungs-Nr\.?|Beleg(?:nummer|nr\.?)|Invoice\s*(?:No\.?|Number))\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/\.]{2,})",
        r"\bRE\s*[-:]?\s*([A-Z0-9][A-Z0-9\-\/\.]{2,})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_filename_part(match.group(1), "OhneNr")
    return "OhneNr"


def find_date(text: str) -> str:
    patterns = [
        r"(?:Rechnungsdatum|Datum|Invoice Date)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace("/", ".").replace("-", ".")
            for fmt in ("%d.%m.%Y", "%d.%m.%y"):
                try:
                    return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
                except ValueError:
                    pass
    return "00.00.0000"


def find_amount(text: str) -> str:
    patterns = [
        r"(?:Gesamtbetrag|Rechnungsbetrag|Endbetrag|Zu zahlen|Bruttobetrag|Total|Amount Due)\s*[:\-]?\s*(?:EUR|€)?\s*([0-9]{1,3}(?:[.\s][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        r"([0-9]{1,3}(?:[.\s][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|€)",
    ]
    amounts = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).replace(" ", "")
            normalized = value.replace(".", "").replace(",", ".")
            try:
                amounts.append((float(normalized), value))
            except ValueError:
                pass
    if amounts:
        return max(amounts, key=lambda x: x[0])[1]
    return "0,00"


def find_company(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ignore = ("rechnung", "invoice", "datum", "kund", "betrag", "seite", "ust", "steuer", "iban", "bic")
    for line in lines[:25]:
        low = line.lower()
        if any(word in low for word in ignore):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-zÄÖÜäöüß]", line):
            return clean_filename_part(line, "Firma")[:60]
    return "Firma"


def build_new_name(path: Path):
    text = extract_text_from_pdf(path)
    nummer = find_invoice_number(text)
    firma = find_company(text)
    datum = find_date(text)
    betrag = find_amount(text)
    return f"RE{nummer}_{firma}_{datum}_{betrag}EUR.pdf"


def unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    counter = 2
    while True:
        candidate = target.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x600")
        self.folder = None
        self.rows = []

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="PDF-Ordner auswählen", command=self.choose_folder).pack(side="left")
        ttk.Button(top, text="Vorschau erstellen", command=self.preview).pack(side="left", padx=8)
        ttk.Button(top, text="Umbenennen", command=self.rename_files).pack(side="left")
        ttk.Button(top, text="Beenden", command=self.destroy).pack(side="right")

        self.folder_label = ttk.Label(self, text="Kein Ordner ausgewählt", padding=10)
        self.folder_label.pack(fill="x")

        columns = ("old", "new", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("old", text="Alter Dateiname")
        self.tree.heading("new", text="Neuer Dateiname")
        self.tree.heading("status", text="Status")
        self.tree.column("old", width=330)
        self.tree.column("new", width=470)
        self.tree.column("status", width=160)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

    def choose_folder(self):
        selected = filedialog.askdirectory()
        if selected:
            self.folder = Path(selected)
            self.folder_label.config(text=str(self.folder))

    def preview(self):
        if not self.folder:
            messagebox.showwarning(APP_TITLE, "Bitte zuerst einen Ordner auswählen.")
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.rows = []
        pdfs = sorted(self.folder.glob("*.pdf"))
        if not pdfs:
            messagebox.showinfo(APP_TITLE, "Keine PDF-Dateien im Ordner gefunden.")
            return

        for pdf in pdfs:
            try:
                new_name = build_new_name(pdf)
                status = "OK"
            except Exception as exc:
                new_name = ""
                status = f"Fehler: {exc}"
            self.rows.append((pdf, new_name, status))
            self.tree.insert("", "end", values=(pdf.name, new_name, status))

    def rename_files(self):
        if not self.rows:
            messagebox.showwarning(APP_TITLE, "Bitte zuerst eine Vorschau erstellen.")
            return

        if not messagebox.askyesno(APP_TITLE, "Dateien jetzt wirklich umbenennen?"):
            return

        log_lines = ["Status;Alter Dateiname;Neuer Dateiname"]
        changed = 0

        for pdf, new_name, status in self.rows:
            if status != "OK" or not new_name:
                log_lines.append(f"SKIP;{pdf.name};{status}")
                continue

            target = unique_path(pdf.with_name(new_name))
            try:
                pdf.rename(target)
                log_lines.append(f"OK;{pdf.name};{target.name}")
                changed += 1
            except Exception as exc:
                log_lines.append(f"ERROR;{pdf.name};{exc}")

        log_path = self.folder / "pdf_umbenennung_log.csv"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        messagebox.showinfo(APP_TITLE, f"{changed} Datei(en) umbenannt.\nLog: {log_path}")
        self.preview()


if __name__ == "__main__":
    App().mainloop()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CSV_IN = DATA_DIR / "tbl_instrumentos.csv"

# Saídas (mantemos CSVs só para auditoria interna; NÃO precisa anexar no email)
OUT_PRIORIDADES = DATA_DIR / "prioridades.csv"
OUT_ALERTA_60 = DATA_DIR / "alertas_60.csv"
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"
OUT_LOG = DATA_DIR / "resumo_execucao.json"

DATE_COLS_END = ["vigencia_termino", "VIGÊNCIA - TÉRMINO", "vencimento", "Vencimento", "vigencia_fim"]
DATE_COLS_START = ["vigencia_inicio", "VIGÊNCIA - INÍCIO", "inicio", "Inicio"]

def norm(s: str) -> str:
    return (s or "").strip()

def upper(s: str) -> str:
    return norm(s).upper()

def first(row: Dict[str, str], keys: List[str]) -> str:
    for k in keys:
        if k in row and norm(row[k]) != "":
            return row[k]
    return ""

def parse_date_any(raw: str) -> Optional[date]:
    raw = norm(raw)
    if not raw:
        return None

    # dd/mm/yyyy ou dd-mm-yyyy
    for sep in ["/", "-"]:
        parts = raw.split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            try:
                dd = int(parts[0]); mm = int(parts[1]); yy = int(parts[2])
                return date(yy, mm, dd)
            except Exception:
                pass

    # yyyy-mm-dd
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            yy = int(raw[0:4]); mm = int(raw[5:7]); dd = int(raw[8:10])
            return date(yy, mm, dd)
        except Exception:
            pass

    # fallback ISO
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None

def days_to(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return (d - today).days

def is_concluido(row: Dict[str, str]) -> bool:
    v = upper(first(row, [
        "status_execucao", "status_execução",
        "situacao_execucao", "situação_execucao",
        "andamento", "execucao", "execução"
    ]))
    return ("CONCL" in v) or ("FINALIZ" in v)

def is_arquivado(row: Dict[str, str]) -> bool:
    v = upper(first(row, ["arquivado", "Arquivado", "status_geral", "Status Geral", "status"]))
    return v in {"SIM", "S", "1", "TRUE"} or ("ARQUIV" in v)

def ensure_publicacao_doe(row: Dict[str, str]) -> None:
    extr = norm(row.get("numero_extrato_publicado", ""))
    if not norm(row.get("publicacao_doe", "")) and extr:
        row["publicacao_doe"] = extr

def sniff_dialect(path: Path) -> csv.Dialect:
    sample = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,|\t")
    except Exception:
        # fallback BR
        class D(csv.Dialect):
            delimiter = ";"
            quotechar = '"'
            doublequote = True
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        return D()

def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], csv.Dialect]:
    dialect = sniff_dialect(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []
        rows: List[Dict[str, str]] = []
        for r in reader:
            if not any(norm(str(v)) for v in r.values()):
                continue
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
        return rows, headers, dialect

def write_csv(path: Path, rows: List[Dict[str, str]], headers: List[str], dialect: csv.Dialect) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, dialect=dialect)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})

def categoria_status(dias: Optional[int]) -> str:
    if dias is None:
        return "SEM DATA"
    if dias < 0:
        return "VENCIDO"
    if dias <= 60:
        return "CRITICO_60"
    if dias <= 180:
        return "ALERTA_180"
    return "CONFORTAVEL"

def main() -> int:
    today = date.today()

    if not CSV_IN.exists():
        print(f"[ERRO] CSV não encontrado: {CSV_IN}", file=sys.stderr)
        return 1

    rows, headers, dialect = read_csv(CSV_IN)

    # Colunas calculadas (mantém compatibilidade do seu painel)
    wanted_cols = [
        "dias_para_vencer",
        "status_prazo",          # CONFORTAVEL / ALERTA_180 / CRITICO_60 / VENCIDO / SEM DATA
        "alerta_180",
        "alerta_60",
        "status_execucao_padrao",
        "publicacao_doe",
    ]
    for c in wanted_cols:
        if c not in headers:
            headers.append(c)

    prioridades = []
    alertas180 = []
    alertas60 = []

    cont = {"CONFORTAVEL": 0, "ALERTA_180": 0, "CRITICO_60": 0, "VENCIDO": 0, "SEM DATA": 0}
    menor_prazo = None  # (dias, identificacao)

    for r in rows:
        ensure_publicacao_doe(r)

        fim_raw = first(r, DATE_COLS_END)
        fim = parse_date_any(fim_raw)
        dias = days_to(fim, today)

        r["dias_para_vencer"] = "" if dias is None else str(dias)
        st = categoria_status(dias)
        r["status_prazo"] = st
        r["alerta_180"] = "SIM" if (dias is not None and 61 <= dias <= 180) else "NÃO"
        r["alerta_60"] = "SIM" if (dias is not None and 0 <= dias <= 60) else "NÃO"
        r["status_execucao_padrao"] = "CONCLUÍDO" if is_concluido(r) else "EM ANDAMENTO"

        cont[st] = cont.get(st, 0) + 1

        # menor prazo útil (para referência de gestão)
        ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
        if dias is not None:
            if (menor_prazo is None) or (dias < menor_prazo[0]):
                menor_prazo = (dias, ident)

        # ignora arquivados para filas
        if is_arquivado(r):
            continue

        prioridades.append(r)
        if r["alerta_180"] == "SIM":
            alertas180.append(r)
        if r["alerta_60"] == "SIM":
            alertas60.append(r)

    def sort_key(r: Dict[str, str]):
        try:
            d = int(r.get("dias_para_vencer", "").strip())
        except Exception:
            d = 10**9
        ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
        return (d, ident)

    prioridades.sort(key=sort_key)
    alertas180.sort(key=sort_key)
    alertas60.sort(key=sort_key)

    out_headers = headers[:]

    # arquivos (auditoria interna)
    write_csv(OUT_PRIORIDADES, prioridades, out_headers, dialect)
    write_csv(OUT_ALERTA_180, alertas180, out_headers, dialect)
    write_csv(OUT_ALERTA_60, alertas60, out_headers, dialect)

    resumo = {
        "data_execucao": today.isoformat(),
        "total_registros": len(rows),
        "nao_arquivados": len(prioridades),
        "contagens": cont,
        "alerta_180_qtd": len(alertas180),
        "critico_60_qtd": len(alertas60),
        "menor_prazo_dias": None if menor_prazo is None else menor_prazo[0],
        "menor_prazo_identificacao": None if menor_prazo is None else menor_prazo[1],
    }
    OUT_LOG.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    # Atualiza o CSV de entrada com colunas calculadas (mantém seu painel rico)
    write_csv(CSV_IN, rows, out_headers, dialect)

    print("[OK] Monitoramento concluído:", json.dumps(resumo, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CSV_IN = DATA_DIR / "tbl_instrumentos.csv"
OUT_PRIORIDADES = DATA_DIR / "prioridades.csv"
OUT_ALERTA_30 = DATA_DIR / "alertas_30.csv"
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"
OUT_LOG = DATA_DIR / "resumo_execucao.json"

DATE_COLS_START = ["vigencia_inicio", "VIGÊNCIA - INÍCIO", "inicio", "Inicio"]
DATE_COLS_END = ["vigencia_termino", "VIGÊNCIA - TÉRMINO", "vencimento", "Vencimento", "vigencia_fim"]

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

    # Aceita dd/mm/yyyy ou dd-mm-yyyy
    for sep in ["/", "-"]:
        parts = raw.split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            try:
                dd = int(parts[0]); mm = int(parts[1]); yy = int(parts[2])
                return date(yy, mm, dd)
            except Exception:
                pass

    # Aceita yyyy-mm-dd
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            yy = int(raw[0:4]); mm = int(raw[5:7]); dd = int(raw[8:10])
            return date(yy, mm, dd)
        except Exception:
            pass

    # Fallback
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None

def days_to(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return (d - today).days

def risco_categoria(dias: Optional[int]) -> str:
    if dias is None:
        return "SEM DATA"
    if dias < 0:
        return "VENCIDO"
    if dias <= 30:
        return "CRÍTICO (≤30d)"
    if dias <= 90:
        return "ALTO (31–90d)"
    if dias <= 180:
        return "MÉDIO (91–180d)"
    if dias <= 365:
        return "BAIXO (181–365d)"
    return "OK (>365d)"

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
    """
    Migra automaticamente:
    - se existir numero_extrato_publicado e publicacao_doe estiver vazio, copia
    """
    extr = norm(row.get("numero_extrato_publicado", ""))
    if not norm(row.get("publicacao_doe", "")) and extr:
        row["publicacao_doe"] = extr

def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = []
        for r in reader:
            # remove linhas vazias
            if not any(norm(str(v)) for v in r.values()):
                continue
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
        return rows, headers

def write_csv(path: Path, rows: List[Dict[str, str]], headers: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})

def main() -> int:
    today = date.today()
    if not CSV_IN.exists():
        print(f"[ERRO] CSV não encontrado: {CSV_IN}", file=sys.stderr)
        return 1

    rows, headers = read_csv(CSV_IN)

    # Garante colunas de saída (sem quebrar seu painel)
    wanted_cols = [
        "dias_para_vencer", "categoria_risco", "alerta_30", "alerta_180",
        "status_execucao_padrao", "publicacao_doe"
    ]
    for c in wanted_cols:
        if c not in headers:
            headers.append(c)

    prioridades = []
    alertas30 = []
    alertas180 = []

    for r in rows:
        ensure_publicacao_doe(r)

        fim_raw = first(r, DATE_COLS_END)
        fim = parse_date_any(fim_raw)
        dias = days_to(fim, today)

        r["dias_para_vencer"] = "" if dias is None else str(dias)
        r["categoria_risco"] = risco_categoria(dias)
        r["alerta_30"] = "SIM" if (dias is not None and 0 <= dias <= 30) else "NÃO"
        r["alerta_180"] = "SIM" if (dias is not None and 0 <= dias <= 180) else "NÃO"
        r["status_execucao_padrao"] = "CONCLUÍDO" if is_concluido(r) else "EM ANDAMENTO"

        # filas (ignora arquivado automaticamente)
        if is_arquivado(r):
            continue

        # prioridades (ordena por dias)
        prioridades.append(r)

        if r["alerta_30"] == "SIM":
            alertas30.append(r)
        if r["alerta_180"] == "SIM":
            alertas180.append(r)

    def sort_key(r: Dict[str, str]) -> Tuple[int, str]:
        # None vai pro fim
        try:
            d = int(r.get("dias_para_vencer", "").strip())
        except Exception:
            d = 10**9
        ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
        return (d, ident)

    prioridades.sort(key=sort_key)
    alertas30.sort(key=sort_key)
    alertas180.sort(key=sort_key)

    # Define headers de saída mais “amigáveis” (sem perder dados)
    # Mantém todas as colunas do CSV original + calculadas
    out_headers = headers[:]

    # Escreve saídas
    write_csv(OUT_PRIORIDADES, prioridades, out_headers)
    write_csv(OUT_ALERTA_30, alertas30, out_headers)
    write_csv(OUT_ALERTA_180, alertas180, out_headers)

    # Log de execução
    resumo = {
        "data_execucao": today.isoformat(),
        "total_registros": len(rows),
        "prioridades": len(prioridades),
        "alerta_30": len(alertas30),
        "alerta_180": len(alertas180),
    }
    OUT_LOG.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    # Opcional: atualizar o próprio CSV de entrada com as colunas calculadas
    # (Isso é útil se você quer ver as colunas também quando abrir no Numbers/Excel)
    write_csv(CSV_IN, rows, out_headers)

    print("[OK] Monitoramento concluído:", json.dumps(resumo, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
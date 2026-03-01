#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CSV_IN = DATA_DIR / "tbl_instrumentos.csv"

OUT_PRIORIDADES = DATA_DIR / "prioridades.csv"
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"
OUT_ALERTA_60 = DATA_DIR / "alertas_60.csv"
OUT_LOG = DATA_DIR / "resumo_execucao.json"

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

def sniff_delimiter(path: Path) -> str:
    # Detecta automaticamente (',' ou ';')
    sample = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        return dialect.delimiter
    except Exception:
        # fallback comum em planilhas BR
        return ";"

def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    delim = sniff_delimiter(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        headers = reader.fieldnames or []
        rows: List[Dict[str, str]] = []
        for r in reader:
            if not any(norm(str(v)) for v in r.values()):
                continue
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
        return rows, headers, delim

def write_csv(path: Path, rows: List[Dict[str, str]], headers: List[str], delim: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, delimiter=delim)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})

def categoria_prazo(dias: Optional[int]) -> str:
    if dias is None:
        return "SEM DATA"
    if dias < 0:
        return "VENCIDO"
    if dias <= 60:
        return "CRÍTICO (≤60d)"
    if dias <= 180:
        return "ALERTA (61–180d)"
    return "CONFORTÁVEL (>180d)"

def main() -> int:
    today = date.today()

    if not CSV_IN.exists():
        print(f"[ERRO] CSV não encontrado: {CSV_IN}", file=sys.stderr)
        return 1

    rows, headers, delim = read_csv(CSV_IN)

    # Colunas calculadas (não quebra sua planilha; só adiciona)
    wanted_cols = [
        "dias_para_vencer", "categoria_prazo",
        "alerta_60", "alerta_180",
        "status_execucao_padrao"
    ]
    for c in wanted_cols:
        if c not in headers:
            headers.append(c)

    prioridades: List[Dict[str, str]] = []
    alertas60: List[Dict[str, str]] = []
    alertas180: List[Dict[str, str]] = []

    # Contadores “base”
    total_registros = len(rows)
    ignorados_arquivados = 0
    concluidos = 0

    # Para “menor prazo”
    menor_dias: Optional[int] = None
    menor_ref: str = ""

    # Contadores por categoria
    confortavel = 0
    alerta_61_180 = 0
    critico_ate_60 = 0
    vencido = 0
    sem_data = 0

    for r in rows:
        if is_concluido(r):
            concluidos += 1

        if is_arquivado(r):
            ignorados_arquivados += 1
            continue

        fim_raw = first(r, DATE_COLS_END)
        fim = parse_date_any(fim_raw)
        dias = days_to(fim, today)

        r["dias_para_vencer"] = "" if dias is None else str(dias)
        r["categoria_prazo"] = categoria_prazo(dias)
        r["alerta_60"] = "SIM" if (dias is not None and 0 <= dias <= 60) else "NÃO"
        r["alerta_180"] = "SIM" if (dias is not None and 0 <= dias <= 180) else "NÃO"
        r["status_execucao_padrao"] = "CONCLUÍDO" if is_concluido(r) else "EM ANDAMENTO"

        # Contabiliza categorias
        if dias is None:
            sem_data += 1
        elif dias < 0:
            vencido += 1
        elif dias <= 60:
            critico_ate_60 += 1
        elif dias <= 180:
            alerta_61_180 += 1
        else:
            confortavel += 1

        # Menor prazo (considera só com data)
        if dias is not None:
            if (menor_dias is None) or (dias < menor_dias):
                menor_dias = dias
                ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
                menor_ref = f"{ident} — {fim_raw}"

        # Filas para CSVs de apoio (mesmo que você não anexe)
        prioridades.append(r)
        if r["alerta_60"] == "SIM":
            alertas60.append(r)
        if r["alerta_180"] == "SIM":
            alertas180.append(r)

    def sort_key(r: Dict[str, str]) -> Tuple[int, str]:
        try:
            d = int(norm(r.get("dias_para_vencer", "")))
        except Exception:
            d = 10**9
        ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
        return (d, ident)

    prioridades.sort(key=sort_key)
    alertas60.sort(key=sort_key)
    alertas180.sort(key=sort_key)

    out_headers = headers[:]

    # Escreve saídas (úteis para auditoria interna)
    write_csv(OUT_PRIORIDADES, prioridades, out_headers, delim)
    write_csv(OUT_ALERTA_60, alertas60, out_headers, delim)
    write_csv(OUT_ALERTA_180, alertas180, out_headers, delim)

    total_base_painel = len(prioridades)

    resumo = {
        "data_execucao": today.isoformat(),
        "total_registros": total_registros,
        "total_base_painel": total_base_painel,
        "ignorados_arquivados": ignorados_arquivados,
        "concluidos": concluidos,
        "categorias": {
            "confortavel_gt_180": confortavel,
            "alerta_61_180": alerta_61_180,
            "critico_ate_60": critico_ate_60,
            "vencido": vencido,
            "sem_data": sem_data
        },
        "alertas": {
            "alerta_180": len(alertas180),
            "alerta_60": len(alertas60)
        },
        "menor_prazo_dias": (menor_dias if menor_dias is not None else ""),
        "menor_prazo_ref": menor_ref
    }
    OUT_LOG.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    # Atualiza o CSV com colunas calculadas (mantém seu arquivo “vivo”)
    write_csv(CSV_IN, rows, out_headers, delim)

    print("[OK] Monitoramento concluído:", json.dumps(resumo, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

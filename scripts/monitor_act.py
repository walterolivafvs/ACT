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

OUT_PRIORIDADES = DATA_DIR / "prioridades.csv"
OUT_ALERTA_30 = DATA_DIR / "alertas_30.csv"
OUT_ALERTA_60 = DATA_DIR / "alertas_60.csv"
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"
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

    # fallback ISO
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None

def days_to(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return (d - today).days

def risco_categoria(dias: Optional[int]) -> str:
    """
    Faixas alinhadas à sua governança:
    - ≤180d: PREPARAÇÃO (disparar com antecedência)
    - ≤60d : EXECUÇÃO (ajustes finais e tramitação forte)
    - ≤30d : CRÍTICO (risco alto de não tramitar a tempo)
    """
    if dias is None:
        return "SEM DATA"
    if dias < 0:
        return "VENCIDO"
    if dias <= 30:
        return "CRÍTICO (≤30d)"
    if dias <= 60:
        return "EXECUÇÃO (≤60d)"
    if dias <= 180:
        return "PREPARAÇÃO (≤180d)"
    return "OK (>180d)"

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
    Se existir numero_extrato_publicado e publicacao_doe estiver vazio, copia para publicacao_doe.
    (Assim você mantém o painel coerente com “Publicação DOE”.)
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

    # Colunas calculadas (não quebra seu painel; só adiciona)
    wanted_cols = [
        "dias_para_vencer",
        "categoria_risco",
        "alerta_30",
        "alerta_60",
        "alerta_180",
        "status_execucao_padrao",
        "publicacao_doe"
    ]
    for c in wanted_cols:
        if c not in headers:
            headers.append(c)

    prioridades: List[Dict[str, str]] = []
    alertas30: List[Dict[str, str]] = []
    alertas60: List[Dict[str, str]] = []
    alertas180: List[Dict[str, str]] = []

    # contadores do relatório
    count_critico = 0
    count_execucao = 0
    count_preparacao = 0
    count_semdata = 0
    count_vencido = 0
    count_ok = 0
    count_concluidos = 0
    count_arquivados = 0

    for r in rows:
        ensure_publicacao_doe(r)

        # status execução padronizado (para seu botão “concluídos” no HTML, se quiser usar)
        r["status_execucao_padrao"] = "CONCLUÍDO" if is_concluido(r) else "EM ANDAMENTO"
        if is_concluido(r):
            count_concluidos += 1

        if is_arquivado(r):
            count_arquivados += 1
            # arquivado não entra nas filas de alerta
            continue

        fim_raw = first(r, DATE_COLS_END)
        fim = parse_date_any(fim_raw)
        dias = days_to(fim, today)

        r["dias_para_vencer"] = "" if dias is None else str(dias)
        r["categoria_risco"] = risco_categoria(dias)

        r["alerta_30"] = "SIM" if (dias is not None and 0 <= dias <= 30) else "NÃO"
        r["alerta_60"] = "SIM" if (dias is not None and 0 <= dias <= 60) else "NÃO"
        r["alerta_180"] = "SIM" if (dias is not None and 0 <= dias <= 180) else "NÃO"

        # contadores por categoria
        cat = r["categoria_risco"]
        if cat.startswith("CRÍTICO"):
            count_critico += 1
        elif cat.startswith("EXECUÇÃO"):
            count_execucao += 1
        elif cat.startswith("PREPARAÇÃO"):
            count_preparacao += 1
        elif cat == "SEM DATA":
            count_semdata += 1
        elif cat == "VENCIDO":
            count_vencido += 1
        elif cat.startswith("OK"):
            count_ok += 1

        prioridades.append(r)
        if r["alerta_30"] == "SIM":
            alertas30.append(r)
        if r["alerta_60"] == "SIM":
            alertas60.append(r)
        if r["alerta_180"] == "SIM":
            alertas180.append(r)

    def sort_key(r: Dict[str, str]) -> Tuple[int, str]:
        try:
            d = int(r.get("dias_para_vencer", "").strip())
        except Exception:
            d = 10**9
        ident = norm(r.get("identificacao", "")) or norm(r.get("Identificação", ""))
        return (d, ident)

    prioridades.sort(key=sort_key)
    alertas30.sort(key=sort_key)
    alertas60.sort(key=sort_key)
    alertas180.sort(key=sort_key)

    out_headers = headers[:]

    # Saídas
    write_csv(OUT_PRIORIDADES, prioridades, out_headers)
    write_csv(OUT_ALERTA_30, alertas30, out_headers)
    write_csv(OUT_ALERTA_60, alertas60, out_headers)
    write_csv(OUT_ALERTA_180, alertas180, out_headers)

    resumo = {
        "data_execucao": today.isoformat(),
        "total_registros_csv": len(rows),
        "ignorados_arquivados": count_arquivados,
        "total_base_painel": len(prioridades),
        "concluidos": count_concluidos,
        "categorias": {
            "preparacao_ate_180": count_preparacao,
            "execucao_ate_60": count_execucao,
            "critico_ate_30": count_critico,
            "ok": count_ok,
            "sem_data": count_semdata,
            "vencido": count_vencido
        },
        "alertas": {
            "alerta_180": len(alertas180),
            "alerta_60": len(alertas60),
            "alerta_30": len(alertas30)
        }
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    # Atualiza o CSV com colunas calculadas (opcional, mas você queria ver em Numbers/Excel)
    write_csv(CSV_IN, rows, out_headers)

    print("[OK] Monitoramento concluído:", json.dumps(resumo, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

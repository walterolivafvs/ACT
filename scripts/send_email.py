#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

RESUMO = DATA / "resumo_execucao.json"
ANEXOS = [
    DATA / "prioridades.csv",
    DATA / "alertas_180.csv",
    DATA / "alertas_60.csv",
    DATA / "alertas_30.csv",
]

def must_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"[ERRO] Variável de ambiente ausente: {name}")
    return v

def main():
    # Secrets/ENV do GitHub Actions
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip())

    smtp_user = must_env("SMTP_USER")          # ex: walterolivafvs@gmail.com
    smtp_pass = must_env("SMTP_PASS")          # senha de app do Gmail
    to_list = must_env("SMTP_TO")              # emails separados por vírgula
    from_name = os.getenv("SMTP_FROM_NAME", "FVS-RCP • DEPI").strip()

    tos = [x.strip() for x in to_list.split(",") if x.strip()]
    if not tos:
        raise SystemExit("[ERRO] SMTP_TO vazio após parsing.")

    if not RESUMO.exists():
        raise SystemExit(f"[ERRO] Não encontrei {RESUMO}. Rode monitor_act.py antes.")

    resumo = json.loads(RESUMO.read_text(encoding="utf-8"))

    data_exec = resumo.get("data_execucao", "")
    cats = (resumo.get("categorias") or {})
    al = (resumo.get("alertas") or {})

    preparacao = int(cats.get("preparacao_ate_180", 0))
    execucao = int(cats.get("execucao_ate_60", 0))
    critico = int(cats.get("critico_ate_30", 0))
    ok = int(cats.get("ok", 0))
    sem_data = int(cats.get("sem_data", 0))
    vencido = int(cats.get("vencido", 0))

    total_base = int(resumo.get("total_base_painel", 0))
    ignorados = int(resumo.get("ignorados_arquivados", 0))
    concluidos = int(resumo.get("concluidos", 0))

    alerta180 = int(al.get("alerta_180", 0))
    alerta60 = int(al.get("alerta_60", 0))
    alerta30 = int(al.get("alerta_30", 0))

    # Assunto “executivo”
    subject = f"Relatório mensal ACTs — {data_exec} | 180d:{alerta180} • 60d:{alerta60} • 30d:{alerta30}"

    body = f"""Relatório mensal de monitoramento de ACTs (execução automática)

Data de execução: {data_exec}

BASE (sem arquivados):
- Total na base do painel: {total_base}
- Concluídos (marcados em status_execucao): {concluidos}
- Ignorados (arquivados): {ignorados}

GATILHOS DE GESTÃO (por prazo):
- PREPARAÇÃO (≤180 dias): {preparacao}  | arquivo: alertas_180.csv
- EXECUÇÃO (≤60 dias): {execucao}      | arquivo: alertas_60.csv
- CRÍTICO (≤30 dias): {critico}        | arquivo: alertas_30.csv

OUTROS:
- OK (>180 dias): {ok}
- SEM DATA: {sem_data}
- VENCIDO: {vencido}

Anexos:
- prioridades.csv (ordenado por dias para vencer)
- alertas_180.csv
- alertas_60.csv
- alertas_30.csv
"""

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content(body)

    # anexos
    for p in ANEXOS:
        if not p.exists():
            # não aborta: só avisa no corpo
            msg.add_attachment(
                f"[AVISO] Arquivo não encontrado: {p.name}\n".encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename=f"AVISO_{p.name}.txt",
            )
            continue

        data = p.read_bytes()
        msg.add_attachment(
            data,
            maintype="text",
            subtype="csv",
            filename=p.name
        )

    # envio SMTP (Gmail)
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo()
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)

    print("[OK] Email enviado para:", tos)

if __name__ == "__main__":
    main()

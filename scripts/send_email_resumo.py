#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESUMO_JSON = DATA_DIR / "resumo_execucao.json"

def pick(env_name: str, required: bool = True) -> str:
    v = os.getenv(env_name, "").strip()
    if required and not v:
        raise RuntimeError(f"Variável/secreto ausente: {env_name}")
    return v

def fmt_bolinha(cor: str) -> str:
    # símbolos simples (funcionam bem no Gmail)
    return {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴", "cinza": "⚪"}.get(cor, "•")

def main():
    smtp_user = pick("SMTP_USER")
    smtp_pass = pick("SMTP_PASS")
    smtp_to = pick("SMTP_TO")  # pode ser "a@a.com,b@b.com"
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip())

    if not RESUMO_JSON.exists():
        raise RuntimeError(f"Resumo não encontrado: {RESUMO_JSON}. Rode monitor_act.py antes.")

    resumo = json.loads(RESUMO_JSON.read_text(encoding="utf-8"))

    data_exec = resumo.get("data_execucao", "")
    cont = resumo.get("contagens", {}) or {}
    confort = int(cont.get("CONFORTAVEL", 0))
    alerta180 = int(cont.get("ALERTA_180", 0))
    crit60 = int(cont.get("CRITICO_60", 0))
    vencido = int(cont.get("VENCIDO", 0))
    sem_data = int(cont.get("SEM DATA", 0))

    menor_d = resumo.get("menor_prazo_dias", None)
    menor_id = resumo.get("menor_prazo_identificacao", None)

    # assunto bem “executivo”
    subject = f"ACTs/Convênios — Monitoramento mensal ({data_exec}) | 180d:{alerta180} • 60d:{crit60}"

    linhas = []
    linhas.append("Relatório mensal de monitoramento de ACTs/Convênios (execução automática)")
    linhas.append("")
    linhas.append(f"Data de execução: {data_exec}")
    linhas.append("")
    linhas.append("SEMÁFORO DE PRAZOS (vigência/termino):")
    linhas.append(f"{fmt_bolinha('verde')} Confortável (>180 dias): {confort}")
    linhas.append(f"{fmt_bolinha('amarelo')} Alerta (61–180 dias): {alerta180}")
    linhas.append(f"{fmt_bolinha('vermelho')} Crítico (0–60 dias): {crit60}")
    if vencido:
        linhas.append(f"{fmt_bolinha('vermelho')} Vencido (<0 dias): {vencido}")
    if sem_data:
        linhas.append(f"{fmt_bolinha('cinza')} Sem data (inconsistência cadastral): {sem_data}")

    # opcional (eu recomendo manter, mas é 1 linha só)
    if menor_d is not None:
        linhas.append("")
        linhas.append(f"Menor prazo atual: {menor_d} dia(s) — {menor_id or '(sem identificação)'}")

    linhas.append("")
    linhas.append("Obs.: Os prazos são recalculados automaticamente a cada execução, com base na data do dia (GitHub Actions/UTC).")

    body = "\n".join(linhas)

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo()
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)

    print("[OK] E-mail enviado (sem anexos).")

if __name__ == "__main__":
    main()

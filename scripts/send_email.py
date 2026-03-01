#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESUMO = DATA / "resumo_execucao.json"


def must_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"[ERRO] Variável de ambiente ausente: {name}")
    return v


def fmt_bolinha(cor: str) -> str:
    cor = (cor or "").lower()
    if cor == "verde":
        return "🟢"
    if cor == "amarelo":
        return "🟡"
    if cor == "vermelho":
        return "🔴"
    return "⚪"


def parse_int(d: dict, key: str, default: int = 0) -> int:
    try:
        return int((d or {}).get(key, default) or default)
    except Exception:
        return default


def main() -> None:
    # SMTP (GitHub Actions)
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

    data_exec = resumo.get("data_execucao", "").strip() or "N/D"
    cats = (resumo.get("categorias") or {})
    al = (resumo.get("alertas") or {})

    # NOVA LÓGICA (sem 30 dias):
    # - confortável: >180d
    # - alerta: 61–180d (amarelo)
    # - crítico: ≤60d (vermelho)
    confort = parse_int(cats, "ok", 0)
    alerta180 = parse_int(al, "alerta_180", 0)
    crit60 = parse_int(al, "alerta_60", 0)

    sem_data = parse_int(cats, "sem_data", 0)
    vencido = parse_int(cats, "vencido", 0)

    total_base = int(resumo.get("total_base_painel", 0) or 0)
    ignorados = int(resumo.get("ignorados_arquivados", 0) or 0)
    concluidos = int(resumo.get("concluidos", 0) or 0)

    menor_d = resumo.get("menor_prazo_dias", None)
    menor_id = (resumo.get("menor_prazo_identificacao", "") or "").strip()

    # Assunto executivo (só 180/60)
    subject = f"Monitoramento Mensal de ACTs/Convênios — {data_exec} | 180d:{alerta180} • 60d:{crit60}"

    # Corpo formal (sem anexos)
    linhas = []
    linhas.append("Assunto: Monitoramento mensal de vigência de ACTs e Convênios")
    linhas.append("")
    linhas.append(f"Data de referência: {data_exec}")
    linhas.append("")
    linhas.append("Em cumprimento à rotina de monitoramento institucional das vigências dos instrumentos jurídicos vigentes, apresenta-se o seguinte panorama consolidado:")
    linhas.append("")
    linhas.append("BASE (sem arquivados):")
    linhas.append(f"- Total na base do painel: {total_base}")
    linhas.append(f"- Concluídos (marcados em status_execucao): {concluidos}")
    linhas.append(f"- Ignorados (arquivados): {ignorados}")
    linhas.append("")
    linhas.append("SITUAÇÃO DOS PRAZOS DE VIGÊNCIA:")
    linhas.append(f"{fmt_bolinha('verde')} Instrumentos em situação confortável (vigência superior a 180 dias): {confort}")
    linhas.append(f"{fmt_bolinha('amarelo')} Instrumentos em alerta de atenção (vigência entre 61 e 180 dias): {alerta180}")
    linhas.append(f"{fmt_bolinha('vermelho')} Instrumentos em situação crítica (vigência até 60 dias): {crit60}")

    if vencido:
        linhas.append(f"{fmt_bolinha('vermelho')} Instrumentos com vigência expirada: {vencido}")
    if sem_data:
        linhas.append(f"{fmt_bolinha('cinza')} Instrumentos sem registro válido de vigência: {sem_data}")

    if menor_d is not None:
        try:
            menor_d_int = int(menor_d)
            linhas.append("")
            linhas.append(f"Menor prazo identificado no período: {menor_d_int} dia(s) — {menor_id or 'Identificação não informada'}")
        except Exception:
            pass

    linhas.append("")
    linhas.append("Os prazos acima são recalculados automaticamente a cada execução do sistema, com base na data corrente.")
    linhas.append("Recomenda-se que os instrumentos enquadrados nas faixas de alerta sejam avaliados quanto à necessidade de prorrogação, renovação ou adoção das providências administrativas cabíveis.")
    linhas.append("")
    linhas.append("Relatório gerado automaticamente pelo sistema de monitoramento institucional.")

    body = "\n".join(linhas)

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content(body)

    # Envio SMTP (Gmail)
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo()
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)

    print("[OK] Email enviado (sem anexos) para:", tos)


if __name__ == "__main__":
    main()

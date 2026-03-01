#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

OUT_LOG = DATA_DIR / "resumo_execucao.json"
OUT_PRIORIDADES = DATA_DIR / "prioridades.csv"
OUT_ALERTA_30 = DATA_DIR / "alertas_30.csv"
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"

def attach_file(msg: EmailMessage, path: Path) -> None:
    if not path.exists():
        return
    ctype, encoding = mimetypes.guess_type(str(path))
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)

    data = path.read_bytes()
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

def main() -> int:
    email_user = os.environ.get("EMAIL_USER", "").strip()
    email_password = os.environ.get("EMAIL_PASSWORD", "").strip()

    # Modo TESTE CONTROLADO: só envia para TEST_EMAIL
    test_email = os.environ.get("TEST_EMAIL", "").strip()

    if not email_user or not email_password:
        raise SystemExit("ERRO: Secrets EMAIL_USER e/ou EMAIL_PASSWORD não definidos.")

    if not test_email:
        raise SystemExit("ERRO: TEST_EMAIL não definido. (modo teste controlado exige isso)")

    # Lê resumo (se existir)
    resumo = {}
    if OUT_LOG.exists():
        resumo = json.loads(OUT_LOG.read_text(encoding="utf-8"))

    subject = f"Relatório mensal ACTs — {resumo.get('data_execucao', 'sem-data')}"
    html = f"""
    <html>
      <body>
        <h2>Relatório mensal ACTs</h2>
        <p><b>Data execução:</b> {resumo.get('data_execucao', '-')}</p>
        <ul>
          <li><b>Total registros:</b> {resumo.get('total_registros', '-')}</li>
          <li><b>Prioridades:</b> {resumo.get('prioridades', '-')}</li>
          <li><b>Alerta 30 dias:</b> {resumo.get('alerta_30', '-')}</li>
          <li><b>Alerta 180 dias:</b> {resumo.get('alerta_180', '-')}</li>
        </ul>
        <p><i>Modo teste controlado:</i> enviado apenas para <b>{test_email}</b>.</p>
      </body>
    </html>
    """.strip()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_user
    msg["To"] = test_email
    msg.set_content("Seu cliente de e-mail não suporta HTML. Veja os anexos.")
    msg.add_alternative(html, subtype="html")

    # Anexos (se existirem)
    attach_file(msg, OUT_LOG)
    attach_file(msg, OUT_PRIORIDADES)
    attach_file(msg, OUT_ALERTA_30)
    attach_file(msg, OUT_ALERTA_180)

    # Gmail SMTP (TLS)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(email_user, email_password)
        server.send_message(msg)

    print(f"[OK] Email enviado (TESTE) para: {test_email}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

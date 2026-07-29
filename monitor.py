import argparse
import hashlib
import os
import sys
from pathlib import Path

import requests

PAGE_URL = "https://reclutamiento.defensa.gob.es/proceso-de-selecci%C3%B3n-oficiales-y-suboficiales/proceso-acceso/-/categories/2475270"
HASH_FILE = Path("page_hash.txt")
TIMEOUT_SECONDS = 30
USER_AGENT = "defensa-page-monitor/1.0 (+GitHub Actions)"


def write_github_output(name: str, value: str) -> None:
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")


def fetch_page() -> bytes:
    response = requests.get(
        PAGE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    if not response.content:
        raise RuntimeError("La pagina ha devuelto una respuesta vacia.")
    return response.content


def monitor() -> int:
    html = fetch_page()
    current_hash = hashlib.sha256(html).hexdigest()
    previous_hash = HASH_FILE.read_text(encoding="utf-8").strip() if HASH_FILE.exists() else ""

    if not previous_hash:
        HASH_FILE.write_text(current_hash + "\n", encoding="utf-8")
        status = "initialized"
        print("Hash inicial guardado. No se enviara aviso.")
    elif current_hash == previous_hash:
        status = "unchanged"
        print("La pagina no ha cambiado.")
    else:
        HASH_FILE.write_text(current_hash + "\n", encoding="utf-8")
        status = "changed"
        print("Cambio detectado. Hash actualizado.")

    write_github_output("status", status)
    write_github_output("hash", current_hash)
    return 0


def notify() -> int:
    bot_token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("Faltan los secretos BOT_TOKEN o CHAT_ID.")

    text = (
        "⚠️ La pagina de procesos de seleccion de Defensa ha cambiado.\n\n"
        f"Enlace: {PAGE_URL}"
    )
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rechazo el mensaje: {payload}")
    print("Aviso enviado a Telegram.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor sencillo de cambios por SHA256")
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Envia el aviso a Telegram sin volver a descargar la pagina.",
    )
    args = parser.parse_args()
    return notify() if args.notify else monitor()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as exc:
        print(f"Error de red o HTTP: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

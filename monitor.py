import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://reclutamiento.defensa.gob.es/proceso-de-selecci%C3%B3n-oficiales-y-suboficiales/proceso-acceso/-/categories/2475270"
STATE_FILE = Path("monitor_state.json")
CHANGE_FILE = Path("change_summary.json")
TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (compatible; DefensaSectionMonitor/2.0; +GitHub-Actions)"
TARGET_SECTIONS = (
    "Tandas y resultados de las pruebas",
    "Asignación de plazas",
)


def github_output(name: str, value: str) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def comparable_text(value: str) -> str:
    value = normalize_text(value).casefold()
    return "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def canonical_url(url: str) -> str:
    """Ignora parametros variables de Liferay, conservando la ruta real del PDF."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def download_html() -> str:
    response = requests.get(
        PAGE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-ES,es;q=0.9",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    if not response.content:
        raise RuntimeError("La pagina ha devuelto una respuesta vacia.")
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def find_section_table(soup: BeautifulSoup, section_name: str):
    wanted = comparable_text(section_name)
    candidates = soup.find_all(string=lambda text: text and wanted in comparable_text(str(text)))

    for text_node in candidates:
        element = text_node.parent
        # Recorre el DOM hasta la primera tabla, pero se detiene si comienza otra
        # seccion objetivo. Asi no asocia por error la tabla de la seccion siguiente.
        for node in element.next_elements:
            if getattr(node, "name", None) == "table":
                return node
            if isinstance(node, str):
                current = comparable_text(node)
                if any(
                    comparable_text(name) in current
                    for name in TARGET_SECTIONS
                    if name != section_name
                ):
                    break

    raise RuntimeError(f'No se encontro la tabla de la seccion: "{section_name}"')


def extract_documents(table) -> list[dict[str, str]]:
    documents = []
    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue
        link = row.find("a", href=True)
        if link is None:
            continue

        title = normalize_text(link.get_text(" ", strip=True))
        url = canonical_url(link["href"].strip())
        date = normalize_text(cells[-1].get_text(" ", strip=True)) if len(cells) >= 2 else ""
        if title and url:
            documents.append({"title": title, "date": date, "url": url})

    documents.sort(key=lambda item: (item["url"], item["title"], item["date"]))
    return documents


def collect_state(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    sections = {}
    for name in TARGET_SECTIONS:
        table = find_section_table(soup, name)
        sections[name] = extract_documents(table)

    # La primera seccion ya contiene documentos. Si aparece vacia, probablemente recibimos HTML incompleto.
    if not sections[TARGET_SECTIONS[0]]:
        raise RuntimeError(f'La seccion "{TARGET_SECTIONS[0]}" aparecio vacia; se conserva el estado anterior.')

    return {"page_url": PAGE_URL, "sections": sections}


def state_hash(state: dict) -> str:
    data = json.dumps(state["sections"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_state() -> dict | None:
    if not STATE_FILE.exists() or not STATE_FILE.read_text(encoding="utf-8").strip():
        return None
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def index_documents(documents: list[dict]) -> dict[str, dict]:
    return {item["url"]: item for item in documents}


def describe_changes(old: dict, new: dict) -> dict:
    result = {"sections": {}}
    for section in TARGET_SECTIONS:
        old_docs = index_documents(old["sections"].get(section, []))
        new_docs = index_documents(new["sections"].get(section, []))
        added = [new_docs[url] for url in sorted(new_docs.keys() - old_docs.keys())]
        removed = [old_docs[url] for url in sorted(old_docs.keys() - new_docs.keys())]
        modified = [
            {"before": old_docs[url], "after": new_docs[url]}
            for url in sorted(old_docs.keys() & new_docs.keys())
            if old_docs[url] != new_docs[url]
        ]
        if added or removed or modified:
            result["sections"][section] = {
                "added": added,
                "removed": removed,
                "modified": modified,
            }
    return result


def monitor() -> int:
    current = collect_state(download_html())
    previous = load_state()

    if previous is None:
        current["sha256"] = state_hash(current)
        save_json(STATE_FILE, current)
        CHANGE_FILE.unlink(missing_ok=True)
        status = "initialized"
        print("Estado inicial de las dos secciones guardado. No se enviara aviso.")
    elif previous.get("sections") == current["sections"]:
        CHANGE_FILE.unlink(missing_ok=True)
        status = "unchanged"
        print("Las dos secciones vigiladas no han cambiado.")
    else:
        changes = describe_changes(previous, current)
        current["sha256"] = state_hash(current)
        save_json(STATE_FILE, current)
        save_json(CHANGE_FILE, changes)
        status = "changed"
        print("Cambio real detectado en las secciones vigiladas.")
        print(json.dumps(changes, ensure_ascii=False, indent=2))

    github_output("status", status)
    return 0


def format_message(changes: dict) -> str:
    lines = ["⚠️ Cambio en Reclutamiento de Defensa"]
    count = 0
    limit = 10
    for section, details in changes.get("sections", {}).items():
        lines.extend(["", f"📌 {section}"])
        for item in details.get("added", []):
            if count >= limit:
                break
            lines.append(f"➕ {item['title']}")
            if item.get("date"):
                lines.append(f"Fecha: {item['date']}")
            lines.append(item["url"])
            count += 1
        for item in details.get("removed", []):
            if count >= limit:
                break
            lines.append(f"➖ Retirado: {item['title']}")
            count += 1
        for item in details.get("modified", []):
            if count >= limit:
                break
            after = item["after"]
            lines.append(f"✏️ Modificado: {after['title']}")
            if after.get("date"):
                lines.append(f"Fecha: {after['date']}")
            lines.append(after["url"])
            count += 1
    if count >= limit:
        lines.append("\nHay mas cambios. Consulta la pagina para verlos todos.")
    lines.extend(["", PAGE_URL])
    return "\n".join(lines)


def notify() -> int:
    token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Faltan BOT_TOKEN o CHAT_ID.")
    if not CHANGE_FILE.exists():
        raise RuntimeError("No existe el resumen de cambios para notificar.")

    changes = json.loads(CHANGE_FILE.read_text(encoding="utf-8"))
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": format_message(changes), "disable_web_page_preview": True},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rechazo el mensaje: {payload}")
    print("Aviso detallado enviado a Telegram.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notify", action="store_true")
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

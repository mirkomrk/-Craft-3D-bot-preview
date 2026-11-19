import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

DATA = Path("/data")
INBOX = DATA / "inbox"
PREVIEWS = DATA / "previews"
PROJECTS = DATA / "projects"
CATALOG = PROJECTS / "catalog.jsonl"

RENDER_URL = "http://craft3d-renderer:8080/render"

for directory in (INBOX, PREVIEWS, PROJECTS):
    directory.mkdir(parents=True, exist_ok=True)


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user is not None and str(user.id) == ADMIN_ID


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat = update.effective_chat
    message = update.effective_message

    if chat is None or message is None:
        return

    if chat.type == "private":
        if is_admin(update):
            text = (
                "Craft3D AI è collegato a Telegram.\n\n"
                "Accesso amministratore riconosciuto.\n"
                "Ricezione STL, 3MF, STEP, STP, GLB e GLTF; anteprime attivate."
            )
        else:
            text = (
                "Craft3D AI è attivo, ma questo account "
                "non è autorizzato alla gestione privata."
            )
    else:
        text = (
            "Craft3D AI è presente nel gruppo.\n"
            "Invia un file STL, 3MF, STEP, STP, GLB o GLTF come documento per "
            "archiviarlo e generare un'anteprima 3D."
        )

    await message.reply_text(text)


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    chat = update.effective_chat

    if message is None or chat is None:
        return

    if chat.type != "private" or not is_admin(update):
        await message.reply_text(
            "Comando riservato all'amministratore in chat privata."
        )
        return

    await message.reply_text(
        "Craft3D AI: processo attivo.\n"
        f"File archiviati: {sum(1 for p in INBOX.iterdir() if p.is_file())}\n"
        f"Anteprime presenti: {sum(1 for p in PREVIEWS.iterdir() if p.is_file())}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_stl(filename: str) -> dict:
    payload = json.dumps({"filename": filename}).encode("utf-8")
    request = Request(
        RENDER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=210) as response:
        result = json.loads(response.read().decode("utf-8"))

    if result.get("status") != "ok":
        raise RuntimeError("Il renderer non ha confermato il completamento.")

    return result


def append_catalog(record: dict) -> None:
    # Il file viene aperto in append: i record precedenti non vengono sostituiti.
    with CATALOG.open("a", encoding="utf-8") as catalog:
        catalog.write(json.dumps(record, ensure_ascii=False) + "\n")
        catalog.flush()
        os.fsync(catalog.fileno())


async def handle_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        return

    document = message.document
    if document is None:
        return

    original_name = document.file_name or "file_senza_nome"

    extension = Path(original_name).suffix.lower()
    if extension not in {".stl", ".3mf", ".step", ".stp", ".glb", ".gltf"}:
        return

    # Il nome originale è conservato nei metadati.
    # Il nome fisico univoco evita sovrascritture e nomi pericolosi.
    storage_name = f"{uuid.uuid4().hex}{extension}"
    destination = INBOX / storage_name
    preview_path = PREVIEWS / f"{Path(storage_name).stem}.png"

    await message.reply_text(
        f"Ricevuto {extension[1:].upper()}: {original_name}\n"
        "Archivio il file e preparo l'anteprima…"
    )

    try:
        telegram_file = await context.bot.get_file(document.file_id)
        file_path = Path(telegram_file.file_path or "")

        if file_path.is_absolute():
            if not file_path.is_file():
                raise FileNotFoundError(
                    "Il percorso del file restituito dal Bot API locale "
                    f"non è accessibile: {file_path}"
                )
            await asyncio.to_thread(shutil.copyfile, file_path, destination)
        else:
            await telegram_file.download_to_drive(
                custom_path=str(destination)
            )

        file_hash = await asyncio.to_thread(sha256_file, destination)

        record = {
            "id": Path(storage_name).stem,
            "stored_name": storage_name,
            "original_name": original_name,
            "sha256": file_hash,
            "size_bytes": destination.stat().st_size,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat.id,
            "chat_title": chat.title or chat.full_name or str(chat.id),
            "chat_type": chat.type,
            "user_id": user.id,
            "username": user.username,
            "telegram_file_id": document.file_id,
            "caption": message.caption,
        }

        # Archiviazione persistente prima del rendering.
        await asyncio.to_thread(append_catalog, record)

        try:
            result = await asyncio.to_thread(render_stl, storage_name)
            preview_name = result["preview"]
            preview_path = PREVIEWS / preview_name

            if not preview_path.is_file():
                raise RuntimeError("Il renderer non ha creato il PNG atteso.")

            with preview_path.open("rb") as image:
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=image,
                    caption=(
                        f"Anteprima 3D: {original_name}\n"
                        f"SHA-256: {file_hash[:16]}…"
                    ),
                    reply_to_message_id=message.message_id,
                )

        except Exception:
            logging.exception("Rendering non riuscito per %s", storage_name)
            await message.reply_text(
                f"Il file {original_name} è stato archiviato, "
                "ma non è stato possibile generare l'anteprima. "
                "Il file originale è conservato."
            )

    except Exception:
        logging.exception("Ricezione o archiviazione fallita")
        # Non eliminare un file già scaricato: potrebbe essere l'unica copia.
        await message.reply_text(
            "Errore durante la ricezione o l'archiviazione del file. "
            "Controllare i log del bot prima di ritentare."
        )


def main() -> None:
    if not TOKEN or not ADMIN_ID:
        raise RuntimeError(
            "Configurazione mancante: verificare "
            "TELEGRAM_BOT_TOKEN e ADMIN_TELEGRAM_ID nel file .env"
        )

    if not ADMIN_ID.isdigit():
        raise RuntimeError("ADMIN_TELEGRAM_ID deve essere numerico.")

    app = (
        Application.builder()
        .token(TOKEN)
        .base_url("http://telegram-bot-api:8081/bot")
        .base_file_url("http://telegram-bot-api:8081/file/bot")
        .local_mode(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    # Accetta documenti STL, 3MF, STEP e STP nei gruppi e nelle chat private.
    app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document)
    )

    logging.info("Avvio di Craft3D AI")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()

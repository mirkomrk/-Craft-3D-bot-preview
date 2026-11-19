#!/usr/bin/env python3
import json
import os
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = 8080
SOLIDCRAFT = os.environ.get("SOLIDCRAFT_CLI", "/opt/solidcraft/bin/solidcraft-cli")
INBOX = "/data/inbox"
PREVIEWS = "/data/previews"


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"status": "ok"})
        return self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/render":
            return self.send_json(404, {"error": "not_found"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                return self.send_json(400, {"error": "invalid_request_size"})

            data = json.loads(self.rfile.read(length))
            filename = data.get("filename", "")

            if (
                not isinstance(filename, str)
                or not re.fullmatch(
                    r"[A-Za-z0-9_. -]{1,180}\.(stl|3mf|step|stp|glb|gltf)",
                    filename,
                    re.I,
                )
                or filename in (".", "..")
            ):
                return self.send_json(400, {"error": "invalid_filename"})

            source = os.path.join(INBOX, filename)
            if not os.path.isfile(source):
                return self.send_json(404, {"error": "file_not_found"})

            output_name = os.path.splitext(filename)[0] + ".png"
            output = os.path.join(PREVIEWS, output_name)
            os.makedirs(PREVIEWS, exist_ok=True)

            suffix = os.path.splitext(filename)[1].lower()
            command = [
                SOLIDCRAFT, "snapshot",
                "--out", output,
                "--width", "1024",
                "--height", "768",
                "--view", "iso",
                "--no-grid",
                "--no-axes",
            ]

            if suffix in {".glb", ".gltf"}:
                # Apri il modello come design nello stesso processo dello snapshot.
                script = {
                    "commands": [{
                        "id": "doc.open",
                        "params": {"path": source, "up": "z"},
                    }]
                }
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", prefix="craft3d-glb-",
                    dir="/tmp", encoding="utf-8", delete=False
                ) as temporary:
                    json.dump(script, temporary)
                    script_path = temporary.name

                try:
                    command.insert(2, script_path)
                    # Forma: solidcraft-cli snapshot SCRIPT --out PNG ...
                    command = [
                        SOLIDCRAFT, "snapshot", script_path,
                        "--out", output,
                        "--width", "1024",
                        "--height", "768",
                        "--view", "iso",
                        "--no-grid",
                        "--no-axes",
                    ]
                    result = subprocess.run(
                        command, capture_output=True, text=True,
                        timeout=180, check=False,
                    )
                finally:
                    try:
                        os.unlink(script_path)
                    except FileNotFoundError:
                        pass
            else:
                command.extend(["--in", source])
                colors = {
                    ".stl": "#39FF14",
                    ".3mf": "#FF00B3",
                    ".step": "#00E5FF",
                    ".stp": "#00E5FF",
                }
                color = colors[suffix]

                evaluation = subprocess.run(
                    [SOLIDCRAFT, "eval", "--in", source],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=True,
                )
                model = json.loads(evaluation.stdout)

                for body in model.get("bodies", []):
                    name = body.get("name")
                    if name and ":" not in name and "\n" not in name:
                        command.extend(["--body", f"{name}:color={color}"])

                result = subprocess.run(
                    command, capture_output=True, text=True,
                    timeout=180, check=False,
                )

            if result.returncode != 0 or not os.path.isfile(output):
                print("Render failed:", result.stderr[-3000:], flush=True)
                return self.send_json(500, {"error": "render_failed"})

            return self.send_json(200, {
                "status": "ok",
                "preview": output_name,
            })

        except subprocess.TimeoutExpired:
            return self.send_json(504, {"error": "render_timeout"})
        except subprocess.CalledProcessError as exc:
            print("SolidCraft command failed:", exc.stderr[-3000:], flush=True)
            return self.send_json(500, {"error": "render_failed"})
        except Exception as exc:
            print("Request error:", repr(exc), flush=True)
            return self.send_json(500, {"error": "internal_error"})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


print(f"Craft3D renderer API listening on {HOST}:{PORT}", flush=True)
ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

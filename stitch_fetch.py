"""
Fetch Stitch project screens (images + HTML code) via the MCP endpoint.

This is a one-off utility. It calls tools/call -> get_screen for each screen,
then downloads the screenshot + htmlCode assets via curl -L (signed URLs).
"""
import json
import os
import subprocess
import sys

MCP_URL = "https://stitch.googleapis.com/mcp"
API_KEY = "AQ.Ab8RN6JEfMcWwSlIkYdk20dWgcYZm-Ojt19HV9b4CgoceyR-gg"
PROJECT = "4634514319149087268"

SCREENS = [
    ("e2fed7336941431db0f335d0801f8cad", "Main Ops Dashboard"),
    ("0ddfb149c65a4c9ebd2068b35a8002c6", "Human Review Queue"),
    ("82aad39a025c4e0eb29f141533e04406", "Tier Race View"),
    ("02bf54ab5cfc490298eefb03ed8b8fd1", "Rules Engine"),
    ("aef60b447b4f42c5afedbba0cf9fcb1c", "Chaos Test Harness"),
]

OUT = "stitch"
os.makedirs(OUT, exist_ok=True)


def mcp_get_screen(screen_id):
    name = f"projects/{PROJECT}/screens/{screen_id}"
    body = json.dumps({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_screen", "arguments": {"name": name}},
    }).encode()
    p = subprocess.run(
        ["curl.exe", "-s", "-X", "POST", MCP_URL,
         "-H", "Content-Type: application/json",
         "-H", "Accept: application/json, text/event-stream",
         "-H", f"X-Goog-Api-Key: {API_KEY}",
         "--data-binary", "@-"],
        input=body, capture_output=True,
    )
    d = json.loads(p.stdout.decode())
    return d["result"]["content"][0]["text"]


def download(url, dest):
    r = subprocess.run(["curl.exe", "-sL", url, "-o", dest], capture_output=True)
    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    return size


def main():
    manifest = []
    for sid, title in SCREENS:
        print(f"\n=== {title} ({sid}) ===")
        txt = mcp_get_screen(sid)
        obj = json.loads(txt)
        shot = obj.get("screenshot", {}).get("downloadUrl")
        code = obj.get("htmlCode", {}).get("downloadUrl")
        slug = title.lower().replace(" ", "_")

        png = os.path.join(OUT, f"{slug}.png")
        html = os.path.join(OUT, f"{slug}.html")

        if shot:
            sz = download(shot, png)
            print(f"  screenshot -> {png} ({sz} bytes)")
        if code:
            sz = download(code, html)
            print(f"  htmlCode  -> {html} ({sz} bytes)")

        manifest.append({"screen_id": sid, "title": title,
                         "png": png if shot else None, "html": html if code else None})

    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("\nSaved manifest -> stitch/manifest.json")


if __name__ == "__main__":
    main()

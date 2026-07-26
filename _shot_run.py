import subprocess, time, sys, os, signal
from playwright.sync_api import sync_playwright

ROOT = r"C:\Users\Avi_k\Downloads\aircraft"
os.chdir(ROOT)

errs = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 850})
        pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}"))
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR: {e}"))
        pg.goto("http://localhost:8501/", wait_until="load", timeout=15000)
        pg.wait_for_timeout(2500)
        # toggle 3D
        clicked = pg.evaluate("""() => {
            const el = document.getElementById('btn3d');
            if(!el) return 'no-btn3d';
            el.click();
            return el.classList.contains('on') ? 'on' : 'off';
        }""")
        print("3D toggle state:", clicked)
        time.sleep(5)  # let planes spawn + climb
        pg.screenshot(path=os.path.join(ROOT, "shot_3d.png"))
        print("saved shot_3d.png")
        # also dump some scene state
        state = pg.evaluate("""() => {
            return { iso3d: typeof iso3d!=='undefined'?iso3d:'undef',
                     planes: typeof planes!=='undefined'?planes.length:'undef',
                     W: typeof W!=='undefined'?W:'undef',
                     H: typeof H!=='undefined'?H:'undef' };
        }""")
        print("state:", state)
        b.close()
except Exception as e:
    print("EXC", e)

print("=== CONSOLE/PAGE ERRORS ===")
for e in errs:
    print(e)
print("=== END ===")

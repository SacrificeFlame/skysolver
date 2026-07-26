import urllib.request, sys, time
for _ in range(10):
    try:
        r = urllib.request.urlopen("http://localhost:8501/api/health", timeout=3)
        print("HEALTH:", r.read().decode())
        break
    except Exception as e:
        print("retry", e); time.sleep(1)
else:
    print("SERVER NOT RESPONDING")
    sys.exit(1)

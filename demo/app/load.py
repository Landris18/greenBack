import os
import time
import urllib.error
import urllib.request

TARGET = os.environ.get("TARGET_URL", "http://api:8080/work")
INTERVAL = float(os.environ.get("REQUEST_INTERVAL", "1.0"))

if __name__ == "__main__":
    print(f"generateur de charge vers {TARGET} toutes les {INTERVAL} s", flush=True)
    while True:
        try:
            with urllib.request.urlopen(TARGET, timeout=15) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"requete echouee : {error}", flush=True)
        time.sleep(INTERVAL)

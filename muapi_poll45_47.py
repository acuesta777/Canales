import json, urllib.request, time, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zoompan_clip import make_zoompan, ZOOMPAN_MASTER_DUR

MUAPI_KEY = open(pathlib.Path.home()/'.muapi_key').read().strip()
BASE = "https://api.muapi.ai/api/v1"
img_dir = pathlib.Path('familias/azcarraga/03-imagenes')

pending = {
    45: "a1aa69f7-72da-4fab-9554-d887c7ff5f20",
    47: "5c957388-406b-4a42-860f-1087091289d2"
}

for sid, task_id in pending.items():
    jpg = img_dir / f"flow_{sid:04d}.jpg"
    zp  = img_dir / f"flow_{sid:04d}_zp.mp4"
    print(f"[{sid}] polling...", flush=True)
    for _ in range(40):
        time.sleep(5)
        poll = urllib.request.Request(f"{BASE}/predictions/{task_id}/result",
               headers={"x-api-key": MUAPI_KEY})
        d = json.loads(urllib.request.urlopen(poll).read()).get("data", {})
        st = d.get("status")
        print(f"  {st}", flush=True)
        if st == "completed":
            url = d.get("outputs", [None])[0]
            urllib.request.urlretrieve(url, jpg)
            make_zoompan(jpg, zp, ZOOMPAN_MASTER_DUR, index=sid)
            print(f"  OK -> {zp.name}", flush=True)
            break
        if st == "failed":
            print(f"  FAIL: {d}", flush=True)
            break
    else:
        print(f"  TIMEOUT", flush=True)

print("Listo")

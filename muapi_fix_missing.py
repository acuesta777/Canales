import json, pathlib, urllib.request, time, sys

MUAPI_KEY = open(pathlib.Path.home()/'.muapi_key').read().strip()
BASE = "https://api.muapi.ai/api/v1"
IMG_W, IMG_H = 1376, 768

tl = json.load(open('familias/azcarraga/05-montaje/timeline.json'))
img_dir = pathlib.Path('familias/azcarraga/03-imagenes')

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zoompan_clip import make_zoompan, ZOOMPAN_MASTER_DUR

missing_ids = {45, 47, 50, 51, 52, 58, 62}
ia_segs = [s for s in tl['visual_timeline'] if s.get('animate') or s.get('zoompan')]
targets = [s for s in ia_segs if s['segment_id'] in missing_ids]

def gen(prompt):
    body = json.dumps({"prompt": prompt, "width": IMG_W, "height": IMG_H}).encode()
    req = urllib.request.Request(f"{BASE}/flux-schnell-image", data=body,
          headers={"Content-Type": "application/json", "x-api-key": MUAPI_KEY})
    resp = json.loads(urllib.request.urlopen(req).read())
    task_id = resp.get("request_id")
    if not task_id:
        raise RuntimeError(resp)
    for _ in range(40):
        time.sleep(5)
        poll = urllib.request.Request(f"{BASE}/predictions/{task_id}/result",
               headers={"x-api-key": MUAPI_KEY})
        d = json.loads(urllib.request.urlopen(poll).read()).get("data", {})
        if d.get("status") == "completed":
            return d.get("outputs", [None])[0]
        if d.get("status") == "failed":
            raise RuntimeError(d)
    raise TimeoutError("timeout")

for seg in targets:
    sid = seg['segment_id']
    zp = img_dir / f"flow_{sid:04d}_zp.mp4"
    if zp.exists() and zp.stat().st_size > 10000:
        print(f"[{sid}] ya existe, saltando")
        continue
    desc = seg.get('scene_description_es') or seg.get('ia_prompt', '')
    prompt = f"Cinematic hyperrealistic photo, {desc[:200]}, golden hour, 16:9"
    jpg = img_dir / f"flow_{sid:04d}.jpg"
    print(f"[{sid}] generando...", flush=True)
    try:
        url = gen(prompt)
        urllib.request.urlretrieve(url, jpg)
        make_zoompan(jpg, zp, ZOOMPAN_MASTER_DUR, index=sid)
        print(f"  ✓ {zp.name}", flush=True)
    except Exception as e:
        print(f"  ✗ {e}", flush=True)

print("Listo")

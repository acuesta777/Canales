#!/usr/bin/env python3
"""
Detecta clips donde aparece la protagonista (face similarity) y los renombra
para que salgan primero en el render.
Uso: python3 face_sort_clips.py riqueza/agnetha_faltskog/
"""

import sys
import shutil
import subprocess
import tempfile
import numpy as np
from pathlib import Path
from PIL import Image
import cv2

YUNET_MODEL = "/tmp/yunet.onnx"
SFACE_MODEL = "/tmp/sface.onnx"
FRAMES_PER_CLIP = 4
COSINE_THRESHOLD = 0.363   # umbral oficial SFace: >=0.363 = misma persona


def load_image_bgr(path: Path) -> np.ndarray:
    img = Image.open(str(path)).convert("RGB")
    arr = np.array(img)
    return arr[:, :, ::-1].copy()


def detect_faces(detector, img_bgr: np.ndarray):
    """Devuelve array de detecciones shape (N, 15) o None."""
    h, w = img_bgr.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img_bgr)
    return faces  # None si no detecta


def extract_frame_ffmpeg(clip_path: Path, t: float) -> np.ndarray | None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
         "-ss", str(t), "-i", str(clip_path), "-frames:v", "1", "-y", str(tmp)],
        capture_output=True
    )
    if tmp.exists() and tmp.stat().st_size > 0:
        try:
            img = Image.open(tmp).convert("RGB")
            arr = np.array(img)
            tmp.unlink(missing_ok=True)
            return arr[:, :, ::-1].copy()
        except Exception:
            pass
    tmp.unlink(missing_ok=True)
    return None


def clip_duration(clip_path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 5.0


def best_score_for_clip(clip_path: Path, ref_features: list,
                        detector, recognizer) -> float:
    dur = clip_duration(clip_path)
    best = 0.0
    for i in range(1, FRAMES_PER_CLIP + 1):
        t = dur * i / (FRAMES_PER_CLIP + 1)
        frame = extract_frame_ffmpeg(clip_path, t)
        if frame is None:
            continue
        faces = detect_faces(detector, frame)
        if faces is None:
            continue
        for face in faces:
            # Alinear cara
            aligned = recognizer.alignCrop(frame, face)
            feat = recognizer.feature(aligned)
            for ref_f in ref_features:
                score = recognizer.match(feat, ref_f, cv2.FaceRecognizerSF_FR_COSINE)
                if score > best:
                    best = score
    return best


def ref_features(ref_path: Path, detector, recognizer) -> list:
    img = load_image_bgr(ref_path)
    # Reducir si muy grande para acelerar
    h, w = img.shape[:2]
    if max(h, w) > 800:
        scale = 800 / max(h, w)
        img = cv2.resize(img, (int(w*scale), int(h*scale)))
    faces = detect_faces(detector, img)
    print(f"   Detección en referencia completada. Caras: {0 if faces is None else len(faces)}")
    if faces is None:
        print("⚠️  No se detectó cara en referencia — el script usará score 0 para todos")
        return []
    feats = []
    for face in faces:
        aligned = recognizer.alignCrop(img, face)
        feats.append(recognizer.feature(aligned))
    return feats


def sort_clips(persona_dir: Path):
    clips_dir = persona_dir / "clips"
    if not clips_dir.exists():
        print(f"❌ No existe {clips_dir}")
        sys.exit(1)

    ref_candidates = (list(persona_dir.glob("*.webp")) +
                      list(persona_dir.glob("*.jpg")) +
                      list(persona_dir.glob("*.png")))
    if not ref_candidates:
        print("❌ No se encontró foto de referencia en la carpeta del personaje")
        sys.exit(1)
    ref_path = ref_candidates[0]
    print(f"📸 Referencia: {ref_path.name}")

    # Crear detectores
    detector = cv2.FaceDetectorYN_create(YUNET_MODEL, "", (320, 320), 0.6, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF_create(SFACE_MODEL, "")

    ref_feats = ref_features(ref_path, detector, recognizer)
    if not ref_feats:
        print("Abortando — sin cara de referencia")
        sys.exit(1)
    print(f"   Caras en referencia: {len(ref_feats)}")

    clips = sorted(clips_dir.glob("*.mp4"), key=lambda p: int(p.stem) if p.stem.isdigit() else 9999)
    print(f"🎬 Analizando {len(clips)} clips (puede tardar ~5 min)...")

    scores = []
    for i, clip in enumerate(clips):
        score = best_score_for_clip(clip, ref_feats, detector, recognizer)
        match = score >= COSINE_THRESHOLD
        marker = "✅" if match else "  "
        if i % 30 == 0 or match:
            print(f"  {marker} [{i+1}/{len(clips)}] {clip.name}: {score:.3f}")
        scores.append((clip, score, match))

    protagonist_clips = [(c, s) for c, s, m in scores if m]
    other_clips       = [(c, s) for c, s, m in scores if not m]

    print(f"\n🎯 Clips con protagonista: {len(protagonist_clips)}")

    if not protagonist_clips:
        # Si nada supera el umbral, tomar top 10% por score
        print("⚠️  Sin matches — tomando top 10% por score como protagonistas")
        all_s = sorted(scores, key=lambda x: x[1], reverse=True)
        top_n = max(5, len(clips) // 10)
        protagonist_clips = [(c, s) for c, s, _ in all_s[:top_n]]
        other_clips       = [(c, s) for c, s, _ in all_s[top_n:]]
        print(f"   Top {top_n}: {[c.name for c, _ in protagonist_clips[:5]]}...")

    ordered = ([c for c, _ in sorted(protagonist_clips, key=lambda x: x[1], reverse=True)] +
               [c for c, _ in other_clips])

    print("\n🔄 Renombrando clips...")
    tmp_dir = clips_dir / "_sort_tmp"
    tmp_dir.mkdir(exist_ok=True)
    for i, clip in enumerate(ordered):
        shutil.copy2(clip, tmp_dir / f"{i:05d}.mp4")
    for clip in clips:
        clip.unlink()
    for i, _ in enumerate(ordered):
        shutil.move(str(tmp_dir / f"{i:05d}.mp4"), str(clips_dir / f"{i+1}.mp4"))
    tmp_dir.rmdir()

    print(f"\n✅ Listo. Primeros {len(protagonist_clips)} clips son de la protagonista.")
    print("   Corre el render:")
    print("   echo '' | python3 render.py riqueza/agnetha_faltskog/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 face_sort_clips.py riqueza/agnetha_faltskog/")
        sys.exit(1)
    persona_dir = Path(sys.argv[1])
    if not persona_dir.is_absolute():
        persona_dir = Path("/Users/anyelocuesta/Downloads/Canales") / persona_dir
    sort_clips(persona_dir)

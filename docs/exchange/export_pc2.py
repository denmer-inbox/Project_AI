"""PC-2 exporter: full export of OpenCode profiles using the app's own code path."""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(r"C:\Users\nickd\Downloads\Project_AI")
sys.path.insert(0, str(REPO))

import opencode_provider_manager as m  # noqa: E402


def main() -> int:
    cfg_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not cfg_path.exists():
        print("ERROR: config not found:", cfg_path)
        return 2

    cfg = m.load_config(cfg_path)
    coefs = m.load_coefficients(cfg_path)
    profiles = m.profiles_from_config(cfg, coefs)
    payload = m.build_export_payload(profiles, m.default_model_ref(cfg))

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = Path.home() / "Downloads"
    out = out_dir / ("opencode-profiles-PC2-%s.json" % stamp)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    import hashlib
    raw = out.read_bytes()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    ids = [str(p.get("id")) for p in parsed.get("profiles", [])]
    dupes = sorted({i for i in ids if ids.count(i) > 1})

    info = {
        "file": str(out),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "type": parsed.get("type"),
        "version": parsed.get("version"),
        "profiles_count": len(ids),
        "ids": ids,
        "duplicates": dupes,
        "models_count": {str(p.get("id")): len(p.get("models") or []) for p in parsed.get("profiles", [])},
        "default_model": parsed.get("default_model", ""),
        "config_providers": len(getattr(cfg.get("providers", {}) or {}, "keys", lambda: [])()),
        "config_path": str(cfg_path),
        "export_version_const": getattr(m, "EXPORT_VERSION", None),
        "export_type_const": getattr(m, "EXPORT_TYPE", None),
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

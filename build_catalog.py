# -*- coding: utf-8 -*-
"""
build_catalog.py — Tự động quét toàn bộ metadata game trong repository và tạo catalog.json chuẩn.
Chạy script này bất cứ khi nào thêm hoặc cập nhật game trong repository metadata-resource-games.
"""
from __future__ import annotations

import os
import sys
import json
import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(r"E:\0xshinky")))
try:
    import vault
except Exception:
    vault = None

_LANG_LABELS = {
    "english":    "English",
    "german":     "Deutsch (German)",
    "french":     "Français (French)",
    "koreana":    "한국어 (Korean)",
    "tchinese":   "繁體中文 (Traditional Chinese)",
    "schinese":   "简体中文 (Simplified Chinese)",
    "russian":    "Русский (Russian)",
    "polish":     "Polski (Polish)",
    "czech":      "Čeština (Czech)",
    "dutch":      "Nederlands (Dutch)",
    "japanese":   "日本語 (Japanese)",
    "spanish":    "Español (Spanish)",
    "brazilian":  "Português (Brazilian)",
    "italian":    "Italiano (Italian)",
    "hungarian":  "Magyar (Hungarian)",
    "portuguese": "Português (Portuguese)",
    "romanian":   "Română (Romanian)",
    "turkish":    "Türkçe (Turkish)",
    "thai":       "ไทย (Thai)",
    "bulgarian":  "Български (Bulgarian)",
    "ukrainian":  "Українська (Ukrainian)",
    "latam":      "Español Latinoamérica (LATAM)",
}


def _parse_game_info_from_json(data: dict, appid_str: str, repo_dir: Path) -> dict:
    """Trích xuất thông tin chuẩn của game từ file JSON metadata."""
    common = data.get("common", {})
    extended = data.get("extended", {})
    assoc = common.get("associations", {})
    dev = assoc.get("0", {}).get("name", "") if isinstance(assoc, dict) else extended.get("developer", "")
    pub = extended.get("publisher", "")

    # 1. Poster (Capsule) & Header Cover
    capsule_rel = None
    header_rel = None
    assets_full = common.get("library_assets_full", {})
    if isinstance(assets_full, dict):
        capsule_obj = assets_full.get("library_capsule", {}).get("image", {})
        if isinstance(capsule_obj, dict):
            capsule_rel = capsule_obj.get("english") or next(iter(capsule_obj.values()), None)
        header_obj = assets_full.get("library_header", {}).get("image", {})
        if isinstance(header_obj, dict):
            header_rel = header_obj.get("english") or next(iter(header_obj.values()), None)

    if not capsule_rel:
        la = common.get("library_assets", {})
        if isinstance(la, dict):
            c_val = la.get("library_capsule")
            if isinstance(c_val, str) and "/" in c_val:
                capsule_rel = c_val

    if not header_rel:
        hi = common.get("header_image", {})
        if isinstance(hi, dict):
            header_rel = hi.get("english") or next(iter(hi.values()), None)
        elif isinstance(hi, str):
            header_rel = hi

    if capsule_rel:
        poster_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid_str}/{capsule_rel}"
    else:
        poster_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid_str}/library_600x900.jpg"

    if header_rel:
        header_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid_str}/{header_rel}"
    else:
        header_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid_str}/header.jpg"

    # 2. Platforms
    osarch = str(common.get("osarch", "64"))
    if osarch == "64":
        platforms = ["Windows (64-bit)"]
    elif osarch == "32":
        platforms = ["Windows (32-bit)"]
    else:
        platforms = ["Windows (64-bit)", "Windows (32-bit)"]

    # 3. Depots & Base Depot Resolution
    depots_raw = data.get("depots", {})
    depot_base = 0
    if isinstance(depots_raw, dict):
        for did_str, dinfo in depots_raw.items():
            if not did_str.isdigit() or not isinstance(dinfo, dict):
                continue
            id_int = int(did_str)
            if 228980 <= id_int <= 228999:
                continue
            if dinfo.get("depotfromapp") or dinfo.get("sharedinstall") or dinfo.get("dlcappid"):
                continue
            cfg = dinfo.get("config", {})
            oslist = cfg.get("oslist", "")
            if "windows" in oslist and not cfg.get("language"):
                depot_base = id_int
                break
        if not depot_base:
            for did_str, dinfo in depots_raw.items():
                if not did_str.isdigit() or not isinstance(dinfo, dict):
                    continue
                id_int = int(did_str)
                if 228980 <= id_int <= 228999:
                    continue
                if dinfo.get("depotfromapp") or dinfo.get("sharedinstall") or dinfo.get("dlcappid"):
                    continue
                if not dinfo.get("config", {}).get("language"):
                    depot_base = id_int
                    break
    if not depot_base:
        depot_base = int(appid_str) + 1 if appid_str.isdigit() else 0

    # 4. Languages — STRICTLY from depots
    history = data.get("_history", [])
    lang_depots = {}
    if isinstance(depots_raw, dict):
        for did_str, dinfo in depots_raw.items():
            if did_str.isdigit() and isinstance(dinfo, dict):
                lang = dinfo.get("config", {}).get("language")
                if lang:
                    lang_depots[str(lang).lower()] = int(did_str)

    has_companion_lang_depots = len(lang_depots) > 0
    languages = []

    # Luôn tạo mục Default (id: 0, source: 'base') đại diện cho game gốc không kèm gói ngôn ngữ phụ
    languages.append({
        "id": 0,
        "key": "lang:default",
        "lang": "default",
        "label": "Default",
        "source": "base",
        "is_default": True,
    })

    for lang, did in lang_depots.items():
        if lang == "english":
            # Nếu depot english không hề có manifest trong bất kỳ build nào thì bỏ qua (vì Default đã bao trùm)
            has_any = any(str(did) in h.get("manifests", {}) for h in history if isinstance(h, dict))
            if not has_any:
                continue
        lbl = _LANG_LABELS.get(lang, lang.capitalize())
        languages.append({
            "id": did,
            "key": f"lang:{lang}",
            "lang": lang,
            "label": lbl,
            "source": "depot",
        })

    # 5. Metadata Vault Check
    vault_file = repo_dir / appid_str / "metadata"
    has_vault = vault_file.is_file() and vault_file.stat().st_size > 64
    vault_data = None
    if has_vault and vault:
        try:
            vault_data = vault.load_vault(str(vault_file))
        except Exception:
            pass

    branches = depots_raw.get("branches", {}) if isinstance(depots_raw, dict) else {}
    versions = []
    recommended_build_index = 0

    if isinstance(history, list) and history:
        for idx, h in enumerate(history):
            bid = str(h.get("buildId") or h.get("build_id") or "").strip()
            if not bid:
                continue
            branch = h.get("branch", "public")
            time_updated = h.get("timeUpdated") or h.get("timeupdated") or h.get("firstSeen") or 0
            date_str = ""
            if time_updated:
                try:
                    dt = datetime.datetime.fromtimestamp(int(time_updated))
                    date_str = dt.strftime("%m/%d/%Y")
                except Exception:
                    pass

            mfsts = h.get("manifests", {})
            manifest_depot_ids = [str(k) for k in mfsts.keys()] if isinstance(mfsts, dict) else []

            is_ready = False
            if vault_data:
                base_gid = mfsts.get(str(depot_base), {}).get("gid")
                if base_gid:
                    has_key = (depot_base in vault_data.get("keys", {})) or (str(depot_base) in vault_data.get("keys", {}))
                    combo = f"{depot_base}_{base_gid}"
                    has_manifest = combo in vault_data.get("manifests", {})
                    is_ready = bool(has_key and has_manifest)
                else:
                    is_ready = (idx == 0)
            elif has_vault:
                is_ready = bool(mfsts) or (idx == 0)
            else:
                is_ready = (idx == 0)

            if manifest_depot_ids:
                base_available = (str(depot_base) in manifest_depot_ids) or not depot_base
                build_languages = [
                    l for l in languages
                    if (l.get("source") == "base" and base_available) or
                       (l.get("source") == "depot" and str(l.get("id")) in manifest_depot_ids)
                ]
            else:
                build_languages = list(languages)

            if not build_languages:
                build_languages = list(languages)

            soon_suffix = "" if is_ready else " · Sắp có mặt (Update soon)"
            label_prefix = "Public - " if (idx == 0 or branch == "public") else ""
            formatted_date = f" ({date_str})" if date_str else ""
            label = f"{label_prefix}Build {bid}{formatted_date}{soon_suffix}"

            versions.append({
                "id": bid,
                "branch": branch,
                "label": label,
                "is_ready": is_ready,
                "is_recommended": (idx == recommended_build_index),
                "manifest_depots": manifest_depot_ids,
                "languages": build_languages,
            })

    if not versions:
        public_br = branches.get("public", {}) if isinstance(branches, dict) else {}
        public_build = str(public_br.get("buildid", "")).strip() or "latest"
        versions.append({
            "id": public_build,
            "branch": "public",
            "label": f"Public - Build {public_build}",
            "is_ready": True,
            "is_recommended": True,
            "manifest_depots": [],
            "languages": languages,
        })

    build_id = versions[0]["id"]
    config = data.get("config", {})
    installdir = config.get("installdir", common.get("name", ""))

    launch_cfg = config.get("launch", {})
    exes = []
    for e in launch_cfg.values():
        exe = e.get("executable", "")
        if exe and exe not in exes:
            exes.append(exe)
            base_n = Path(exe).name
            if base_n not in exes:
                exes.append(base_n)

    return {
        "id": f"game-{appid_str}",
        "appid": int(appid_str) if appid_str.isdigit() else 0,
        "name": common.get("name", f"App {appid_str}"),
        "developer": dev,
        "publisher": pub,
        "installdir": installdir,
        "launch_exes": exes,
        "build_id": build_id,
        "has_metadata": has_vault,
        "depot_base": depot_base,
        "poster_url": poster_url,
        "header_url": header_url,
        "platforms": platforms,
        "versions": versions,
        "languages": versions[0]["languages"] if (versions and "languages" in versions[0]) else languages,
        "all_languages": languages,
    }


def build_catalog(repo_dir: Path | None = None) -> list[dict]:
    """Quét tất cả thư mục appid và tạo danh sách catalog."""
    if repo_dir is None:
        repo_dir = Path(__file__).resolve().parent

    print(f"[*] Quét metadata trong: {repo_dir}")
    games = []
    # Tìm các thư mục có tên là số appid
    for item in sorted(repo_dir.iterdir()):
        if not item.is_dir() or not item.name.isdigit():
            continue
        aid = item.name
        json_file = item / f"{aid}.json"
        if not json_file.is_file():
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            info = _parse_game_info_from_json(data, aid, repo_dir)
            games.append(info)
            vault_status = "[+ Vault]" if info["has_metadata"] else "[No Vault]"
            print(f"  -> [{aid}] {info['name']} {vault_status} ({len(info['versions'])} builds)")
        except Exception as e:
            print(f"  [!] Lỗi khi nạp {aid}: {e}")

    out_file = repo_dir / "catalog.json"
    out_file.write_text(json.dumps(games, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Đã xuất {len(games)} game vào: {out_file} ({out_file.stat().st_size:,} bytes)")
    return games


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    build_catalog(base)

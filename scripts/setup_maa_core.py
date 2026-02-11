#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAA Core 下载与部署脚本
从 GitHub Release 下载预编译的 MAA Core 产物，部署 resource 到 assets、so 到 jniLibs。

usage:
    python scripts/setup_maa_core.py                    # 下载最新 release 并部署
    python scripts/setup_maa_core.py --tag v6.3.0       # 下载指定 tag
    python scripts/setup_maa_core.py --clean             # 清空目标目录后部署
    python scripts/setup_maa_core.py --skip-download     # 跳过下载，仅从缓存部署
"""

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
import urllib.error
from pathlib import Path

# 修复 Windows 控制台编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 配置 ──────────────────────────────────────────────
GITHUB_REPO = "Aliothmoon/MaaAssistantArknights"
API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"

# ABI 映射: release asset 关键字 -> jniLibs 子目录名
ABI_MAP = {
    "android-arm64": "arm64-v8a",
    "android-x64": "x86_64",
}

# 需要拷贝到 jniLibs 的 so 文件 (排除 libc++_shared.so)
EXCLUDE_SO = {"libc++_shared.so"}

# 忽略的文件扩展名
IGNORE_EXTENSIONS = {".h"}

# 目标路径 (相对于项目根目录)
ASSETS_RESOURCE_DIR = "app/src/main/assets/MaaSync/MaaResource"
JNILIBS_DIR = "app/src/main/jniLibs"
CACHE_DIR = ".maa-cache"


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "MaaMeow-Setup")
    # 支持 GITHUB_TOKEN 环境变量 (CI 或 rate limit)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dest: Path):
    print(f"  [DOWNLOAD] {dest.name}")
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/octet-stream")
    req.add_header("User-Agent", "MaaMeow-Setup")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=600) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    print(f"\r    {mb:.1f}/{total_mb:.1f} MB ({pct}%)", end="", flush=True)
        print()


def get_release_assets(tag: str = None) -> list:
    if tag:
        url = f"{API_BASE}/releases/tags/{tag}"
    else:
        url = f"{API_BASE}/releases/latest"
    print(f"[FETCH] 获取 release 信息: {url}")
    try:
        data = fetch_json(url)
    except urllib.error.HTTPError as e:
        print(f"[ERROR] 请求失败: {e.code} {e.reason}")
        sys.exit(1)
    tag_name = data.get("tag_name", "unknown")
    print(f"  Tag: {tag_name}")
    return tag_name, data.get("assets", [])


def find_android_assets(assets: list) -> dict:
    """找到 android-arm64 和 android-x64 的 tar.gz"""
    result = {}
    for asset in assets:
        name = asset["name"]
        if not name.endswith(".tar.gz"):
            continue
        for keyword, abi in ABI_MAP.items():
            if keyword in name:
                result[abi] = {
                    "name": name,
                    "url": asset["browser_download_url"],
                    "size": asset["size"],
                }
    return result


def extract_and_deploy(tarball: Path, abi: str, project_root: Path, clean: bool):
    assets_dir = project_root / ASSETS_RESOURCE_DIR
    jnilib_dir = project_root / JNILIBS_DIR / abi

    if clean:
        if jnilib_dir.exists():
            # 只删除 MAA 相关的 so，保留 libjnidispatch.so 等其他库
            for f in jnilib_dir.iterdir():
                if f.suffix == ".so" and f.name != "libjnidispatch.so":
                    f.unlink()
                    print(f"    [DELETE] {abi}/{f.name}")

    jnilib_dir.mkdir(parents=True, exist_ok=True)

    stats = {"resource": 0, "so": 0, "skipped": 0}

    print(f"  [EXTRACT] {tarball.name} -> {abi}")
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue

            name = Path(member.name).name
            parts = Path(member.name).parts

            # 忽略头文件
            if Path(name).suffix in IGNORE_EXTENSIONS:
                stats["skipped"] += 1
                continue

            # resource 目录 -> assets (只处理第一个 ABI 避免重复)
            if "resource" in parts:
                # 计算 resource 内的相对路径
                res_idx = list(parts).index("resource")
                rel_parts = parts[res_idx + 1:]
                if not rel_parts:
                    continue
                dest = assets_dir / Path(*rel_parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as src:
                    dest.write_bytes(src.read())
                stats["resource"] += 1
                continue

            # so 文件 -> jniLibs
            if name.endswith(".so"):
                if name in EXCLUDE_SO:
                    stats["skipped"] += 1
                    continue
                dest = jnilib_dir / name
                with tar.extractfile(member) as src:
                    dest.write_bytes(src.read())
                stats["so"] += 1
                continue

            stats["skipped"] += 1

    print(f"    resource: {stats['resource']} 文件, so: {stats['so']} 文件, 跳过: {stats['skipped']}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="下载并部署 MAA Core 预编译产物")
    parser.add_argument("--tag", "-t", help="指定 release tag (默认 latest)")
    parser.add_argument("--clean", "-c", action="store_true", help="清空目标目录后部署")
    parser.add_argument("--skip-download", "-s", action="store_true", help="跳过下载，使用缓存")
    parser.add_argument("--abi", choices=["arm64-v8a", "x64", "all"], default="all",
                        help="只处理指定 ABI (默认 all)")
    args = parser.parse_args()

    project_root = get_project_root()
    cache_dir = project_root / CACHE_DIR

    print("=" * 55)
    print("==> MAA Core 下载与部署脚本")
    print("=" * 55)

    # 清空 assets resource 目录
    if args.clean:
        assets_dir = project_root / ASSETS_RESOURCE_DIR
        if assets_dir.exists():
            print(f"[DELETE] 清空 resource 目录: {assets_dir}")
            shutil.rmtree(assets_dir)

    target_abis = list(ABI_MAP.values()) if args.abi == "all" else [args.abi]

    if not args.skip_download:
        tag_name, assets = get_release_assets(args.tag)
        android_assets = find_android_assets(assets)

        if not android_assets:
            print("[ERROR] 未找到 Android 产物，请检查 release 是否包含 android-arm64/android-x64 的 tar.gz")
            sys.exit(1)

        print(f"\n[INFO] 找到 {len(android_assets)} 个 Android 产物:")
        for abi, info in android_assets.items():
            size_mb = info["size"] / (1024 * 1024)
            print(f"  {abi}: {info['name']} ({size_mb:.1f} MB)")

        # 下载
        print(f"\n[DOWNLOAD] 下载到缓存: {cache_dir}")
        for abi, info in android_assets.items():
            if abi not in target_abis:
                continue
            dest = cache_dir / info["name"]
            if dest.exists() and dest.stat().st_size == info["size"]:
                print(f"  [CACHE] {info['name']} 已存在，跳过下载")
            else:
                download_file(info["url"], dest)
    else:
        print("[SKIP] 跳过下载，使用缓存")

    # 部署
    print(f"\n[DEPLOY] 部署产物...")
    resource_deployed = False
    for tarball in sorted(cache_dir.glob("*.tar.gz")):
        for keyword, abi in ABI_MAP.items():
            if keyword in tarball.name and abi in target_abis:
                extract_and_deploy(tarball, abi, project_root, args.clean)
                resource_deployed = True

    if not resource_deployed:
        print("[ERROR] 缓存中未找到 tar.gz 文件，请先运行不带 --skip-download 的命令")
        sys.exit(1)

    # 汇总
    print("\n" + "=" * 55)
    print("[DONE] 部署完成!")
    print("=" * 55)
    for abi in target_abis:
        jnilib_dir = project_root / JNILIBS_DIR / abi
        if jnilib_dir.exists():
            so_files = [f.name for f in jnilib_dir.iterdir() if f.suffix == ".so"]
            print(f"  {abi}/: {', '.join(sorted(so_files))}")
    assets_dir = project_root / ASSETS_RESOURCE_DIR
    if assets_dir.exists():
        file_count = sum(1 for f in assets_dir.rglob("*") if f.is_file())
        total_size = sum(f.stat().st_size for f in assets_dir.rglob("*") if f.is_file())
        print(f"  resource: {file_count} 文件, {total_size / (1024 * 1024):.1f} MB")


if __name__ == "__main__":
    main()

import asyncio
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

from astrbot.api import logger

FONT_MANIFEST_URL = "https://assets.foolsclub.xyz/astrbot/fonts/font_manifest.json"
FONT_MANIFEST_FILENAME = "font_manifest.json"
DOWNLOAD_TIMEOUT = 120
HASH_CHUNK_SIZE = 1024 * 1024


class FontManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.font_dir = data_dir / "fonts"
        self.manifest_path = data_dir / FONT_MANIFEST_FILENAME

    def read_local_manifest(self) -> dict | None:
        if not self.manifest_path.exists():
            return None
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.validate_manifest(manifest)
            return manifest
        except Exception as e:
            logger.warning(f"[QunAlbum] 读取本地字体 manifest 失败: {e}")
            return None

    def write_manifest(self, manifest: dict) -> None:
        self.font_dir.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def validate_manifest(self, manifest: dict) -> dict:
        if not isinstance(manifest, dict):
            raise ValueError("manifest 必须是 JSON object")
        if manifest.get("schema_version") != 1:
            raise ValueError("manifest schema_version 不受支持")
        fonts = manifest.get("fonts")
        if not isinstance(fonts, list) or not fonts:
            raise ValueError("manifest 缺少 fonts 列表")
        for font in fonts:
            for field in ("name", "version", "url", "sha256"):
                if not isinstance(font.get(field), str) or not font[field].strip():
                    raise ValueError(f"fonts[] 缺少或无效字段: {field}")
            size = font.get("size")
            if not isinstance(size, int) or size <= 0:
                raise ValueError("fonts[].size 无效")
        return manifest

    def fetch_manifest(self) -> dict:
        request = urllib.request.Request(
            FONT_MANIFEST_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "astrbot-plugin-qun-album/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            payload = response.read()
        manifest = json.loads(payload.decode("utf-8"))
        return self.validate_manifest(manifest)

    def is_update_required(
        self, remote_manifest: dict, local_manifest: dict | None
    ) -> bool:
        if not local_manifest:
            return True
        local_fonts = {f["name"]: f for f in local_manifest.get("fonts", [])}
        for remote_font in remote_manifest.get("fonts", []):
            local = local_fonts.get(remote_font["name"])
            if not local:
                return True
            for field in ("version", "sha256", "url"):
                if remote_font.get(field) != local.get(field):
                    return True
        return False

    def sha256_file(self, path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def safe_remove(self, path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"[QunAlbum] 清理临时文件失败: {path}, {e}")

    def download_font(
        self, url: str, dest_path: str, expected_sha256: str, expected_size: int
    ) -> None:
        if os.path.exists(dest_path):
            try:
                if self.sha256_file(dest_path) == expected_sha256.lower():
                    logger.debug(
                        f"[QunAlbum] 字体已存在且校验通过，跳过下载: {dest_path}"
                    )
                    return
            except Exception:
                pass

        self.font_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path + ".download"
        self.safe_remove(tmp_path)
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "astrbot-plugin-qun-album/1.0"},
            )
            with (
                urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response,
                open(tmp_path, "wb") as f,
            ):
                while True:
                    chunk = response.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)

            actual_size = os.path.getsize(tmp_path)
            if actual_size != expected_size:
                raise ValueError(
                    f"文件大小不匹配: expected={expected_size}, actual={actual_size}"
                )

            actual_sha256 = self.sha256_file(tmp_path)
            if actual_sha256 != expected_sha256.lower():
                raise ValueError("文件 SHA256 校验失败")

            os.replace(tmp_path, dest_path)
            logger.info(f"[QunAlbum] 字体下载完成: {dest_path}")
        except Exception:
            self.safe_remove(tmp_path)
            raise

    def download_fonts_sync(self, manifest: dict) -> None:
        for font in manifest["fonts"]:
            name = font["name"]
            url = font["url"]
            expected_sha256 = font["sha256"]
            expected_size = font["size"]
            dest = str(self.font_dir / name)
            self.download_font(url, dest, expected_sha256, expected_size)

    async def download_fonts(self, manifest: dict) -> None:
        await asyncio.to_thread(self.download_fonts_sync, manifest)

    async def ensure_fonts(self) -> bool:
        local_manifest = self.read_local_manifest()
        try:
            remote_manifest = await asyncio.to_thread(self.fetch_manifest)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            logger.error(f"[QunAlbum] 获取字体 manifest 失败: {e}")
            return local_manifest is not None
        except Exception as e:
            logger.error(f"[QunAlbum] 获取字体 manifest 时出现未预期异常: {e}")
            return local_manifest is not None

        if not self.is_update_required(remote_manifest, local_manifest):
            return True

        logger.info("[QunAlbum] 检测到字体更新，开始下载...")
        try:
            await self.download_fonts(remote_manifest)
        except Exception as e:
            logger.error(f"[QunAlbum] 自动下载字体失败: {e}")
            return local_manifest is not None

        self.write_manifest(remote_manifest)

        all_ok = True
        for font in remote_manifest["fonts"]:
            font_path = self.font_dir / font["name"]
            if not font_path.exists():
                all_ok = False
        if all_ok:
            logger.info("[QunAlbum] 全部字体下载并验证通过")
        return all_ok

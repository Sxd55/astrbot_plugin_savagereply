"""AstrBot 插件标准发布打包脚本。

严格保证包含 logo.png、metadata.yaml、字体资产与全部核心源码，
杜绝因正则或后缀通配符误杀导致 logo.png 丢失。
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

# 必须包含在发布包中的关键资产，缺一不可
MANDATORY_ENTRIES = (
    "astrbot_plugin_savagereply/logo.png",
    "astrbot_plugin_savagereply/metadata.yaml",
    "astrbot_plugin_savagereply/main.py",
    "astrbot_plugin_savagereply/requirements.txt",
    "astrbot_plugin_savagereply/_conf_schema.json",
    "astrbot_plugin_savagereply/assets/fonts/NotoSansSC-VF.ttf",
    "astrbot_plugin_savagereply/savagereply/t2i.py",
)

# 排除目录
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "data",
    "t2i_cache",
    "node_modules",
}

# 排除后缀
EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
}


def build_plugin_zip() -> Path:
    plugin_dir = Path(__file__).resolve().parent
    parent_dir = plugin_dir.parent
    output_zip = parent_dir / "astrbot_plugin_savagereply.zip"

    # 预检：根目录 logo.png 必须存在
    logo_file = plugin_dir / "logo.png"
    if not logo_file.is_file():
        raise FileNotFoundError(f"插件核心图标缺失: {logo_file}")

    if output_zip.exists():
        output_zip.unlink()

    print(f"正在打包插件: {plugin_dir.name} -> {output_zip.name} ...")

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_dir):
            # 过滤被排除的目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for f in files:
                # 排除编译字节码
                if any(f.endswith(ext) for ext in EXCLUDE_EXTS):
                    continue
                # 排除临时渲染的 card 测试图片
                if f.startswith("card_") and f.endswith(".png"):
                    continue

                file_path = Path(root) / f
                arcname = file_path.relative_to(parent_dir).as_posix()
                zf.write(file_path, arcname=arcname)

    # 校验生成包
    with zipfile.ZipFile(output_zip, "r") as zf:
        names = set(zf.namelist())
        for required in MANDATORY_ENTRIES:
            if required not in names:
                raise AssertionError(f"打包完整性校验失败，缺少关键文件: {required}")

    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"打包成功！文件数: {len(names)}, 大小: {size_mb:.2f} MB")
    print(f"已严格验证包含插件图标: logo.png (256x256)")

    # 如果存在备份目录，同步更新备份
    backup_zip = parent_dir.parent / "savage - 副本" / "astrbot_plugin_savagereply.zip"
    if backup_zip.parent.exists():
        shutil.copy2(output_zip, backup_zip)
        print(f"已同步更新备份包: {backup_zip}")

    return output_zip


if __name__ == "__main__":
    build_plugin_zip()

# [code_inspector.py/Soveranima]
#     Copyright (C) 2026  Toolspeter
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os

SKILL_MANIFEST = {
    "id": "code_inspector",
    "name": "程式碼檢視器",
    "description": "讓 AI 主動查看和檢視自己的程式碼，用於自我反思和升級",
    "version": "1.0.0",
    "capabilities": ["read_code", "list_files"],
    "priority": 100,
    "author": "Toolspeter"
}

def _get_all_evolvable_files():
    """取得所有可演化檔案列表（與 brain.py 邏輯一致）"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    core_files = ["brain.py", "main.py"]
    skills_dir = os.path.join(base_dir, "skills")

    all_files = []

    # 核心檔案
    for f in core_files:
        filepath = os.path.join(base_dir, f)
        if os.path.exists(filepath):
            all_files.append(f)

    # skills/ 目錄下的所有 .py 檔案（排除 __init__.py）
    if os.path.exists(skills_dir):
        for filename in os.listdir(skills_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                all_files.append(os.path.join("skills", filename))

    return all_files

def list_files():
    """列出所有可演化檔案"""
    try:
        files = _get_all_evolvable_files()
        if not files:
            return "目前沒有可演化的檔案。"

        result = "[可演化檔案列表]\n"
        result += "\n".join([f"- {f}" for f in files])
        return result
    except Exception as e:
        return f"列出檔案時發生錯誤：{e}"

def read_code(file_path=None):
    """
    讀取程式碼
    - 若 file_path 為 None：返回所有可演化檔案的程式碼
    - 若指定 file_path：只返回該檔案的程式碼
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if file_path is None:
            # 返回所有程式碼
            files = _get_all_evolvable_files()
            code_blocks = []
            for f in files:
                filepath = os.path.join(base_dir, f) if not os.path.isabs(f) else f
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        content = file.read()
                        code_blocks.append(f"=== {f} ===\n{content}")
                except Exception as e:
                    code_blocks.append(f"=== {f} ===\n無法讀取：{e}")
            return "\n\n".join(code_blocks)
        else:
            # 返回指定檔案
            # 安全檢查：只允許讀取可演化檔案
            all_files = _get_all_evolvable_files()
            if file_path not in all_files:
                return f"錯誤：'{file_path}' 不在可演化檔案列表中。請使用 list_files 查看可用檔案。"

            filepath = os.path.join(base_dir, file_path)
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
                return f"=== {file_path} ===\n{content}"
    except Exception as e:
        return f"讀取程式碼時發生錯誤：{e}"

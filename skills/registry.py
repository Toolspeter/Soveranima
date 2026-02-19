import os
import importlib.util
import inspect
import json

class SkillRegistry:
    _instance = None

    def __init__(self):
        self.skills = {}
        self.skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
        self.reload_skills()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload_skills(self):
        """掃描目錄並加載所有具備有效 Manifest 的技能"""
        self.skills = {}
        if not os.path.exists(self.skills_dir):
            return

        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".py") and not filename.startswith("__") and filename != "registry.py":
                try:
                    module_name = filename[:-3]
                    file_path = os.path.join(self.skills_dir, filename)
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    if hasattr(module, "SKILL_MANIFEST"):
                        manifest = module.SKILL_MANIFEST
                        if self._validate_manifest(manifest, filename):
                            skill_id = manifest["id"]
                            self.skills[skill_id] = {
                                "manifest": manifest,
                                "module": module
                            }
                except Exception as e:
                    print(f"⚠️ 加載技能 {filename} 失敗: {e}")

    def _validate_manifest(self, manifest: dict, filename: str) -> bool:
        """嚴格校驗 Manifest 格式與必要欄位"""
        required_fields = {
            "id": str,
            "name": str,
            "version": str,
            "capabilities": list
        }
        
        try:
            for field, expected_type in required_fields.items():
                if field not in manifest:
                    print(f"❌ 技能 {filename} 缺少必要欄位: {field}")
                    return False
                if not isinstance(manifest[field], expected_type):
                    print(f"❌ 技能 {filename} 欄位 {field} 型別錯誤 (預期 {expected_type.__name__})")
                    return False
            
            if not manifest["capabilities"]:
                print(f"❌ 技能 {filename} 未宣告任何 capabilities")
                return False
                
            return True
        except Exception as e:
            print(f"❌ 技能 {filename} Manifest 解析異常: {e}")
            return False

    def get_all_manifests(self):
        return [info["manifest"] for info in self.skills.values()]

    def _safe_call(self, func, **kwargs):
        """根據函式簽名過濾參數，避免傳入不支援的 keyword argument"""
        sig = inspect.signature(func)
        params = sig.parameters
        # 如果函式接受 **kwargs，直接全部傳入
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return func(**kwargs)
        # 否則只傳入函式實際接受的參數
        filtered = {k: v for k, v in kwargs.items() if k in params}
        return func(**filtered)

    def _find_func(self, module, capability, manifest):
        """在模組中查找對應 capability 的可呼叫函式"""
        # 1. 優先使用 Manifest 中的 capability_map 映射
        cap_map = manifest.get("capability_map", {})
        if capability in cap_map:
            func = getattr(module, cap_map[capability], None)
            if func and callable(func):
                return func
        # 2. 嘗試與能力同名的函式
        func = getattr(module, capability, None)
        if func and callable(func):
            return func
        # 3. 嘗試通用 execute 入口
        func = getattr(module, "execute", None)
        if func and callable(func):
            return func
        # 4. Fallback: 自動掃描模組中第一個非內建的 callable 函式
        for name in dir(module):
            if name.startswith("_") or name in ("SKILL_MANIFEST",):
                continue
            obj = getattr(module, name)
            if callable(obj) and not isinstance(obj, type) and getattr(obj, "__module__", None) == module.__name__:
                return obj
        return None

    def execute(self, capability, **kwargs):
        """根據能力名稱路由並執行對應技能，按 priority 排序，失敗自動嘗試下一個"""
        # 收集所有支援此 capability 的技能，按 priority 降序排列
        candidates = []
        for skill_id, info in self.skills.items():
            manifest = info["manifest"]
            if capability in manifest.get("capabilities", []):
                priority = manifest.get("priority", 0)
                candidates.append((priority, skill_id, info))

        candidates.sort(key=lambda x: x[0], reverse=True)

        for priority, skill_id, info in candidates:
            manifest = info["manifest"]
            module = info["module"]
            func = self._find_func(module, capability, manifest)
            if func:
                try:
                    result = self._safe_call(func, **kwargs)
                    if result is not None:
                        return result
                    # result 為 None，嘗試下一個技能
                    print(f"🔄 [SSP] {manifest.get('name', skill_id)} 無結果，嘗試下一個")
                except Exception as e:
                    print(f"🔄 [SSP] {manifest.get('name', skill_id)} 執行失敗: {e}，嘗試下一個")
        return None
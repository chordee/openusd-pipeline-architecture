import os
import sys
import unittest

# 模擬 hou 與 husd 模組以便在純 Python 環境下執行單元測試
import types

fake_hou = types.ModuleType("hou")
fake_text = types.ModuleType("hou.text")

def normpath(p):
    return os.path.normpath(p).replace('\\', '/')

def abspath(p, base):
    normalized_p = normpath(p)
    # 支援 POSIX ('/' 開頭) 與 Windows ('C:/' 或 'C:\' 開頭) 的絕對路徑判斷
    is_absolute = os.path.isabs(p) or (len(normalized_p) > 2 and normalized_p[1] == ':' and normalized_p[2] == '/')
    if is_absolute:
        return normalized_p
    return normpath(os.path.join(base, p))

def relpath(p, start_layer):
    start_dir = os.path.dirname(start_layer)
    return normpath(os.path.relpath(p, start_dir))

def expandString(s):
    return s

fake_text.normpath = normpath
fake_text.abspath = abspath
fake_text.relpath = relpath
fake_text.expandString = expandString

fake_hou.text = fake_text
fake_hou.hipFile = types.SimpleNamespace(path=lambda: "/projects/test.hip")
fake_hou.ParmTemplateGroup = lambda: types.SimpleNamespace(append=lambda x: None, asDialogScript=lambda: "")
fake_hou.StringParmTemplate = lambda *args, **kwargs: None
fake_hou.stringParmType = types.SimpleNamespace(FileReference="FileReference")
fake_hou.fileType = types.SimpleNamespace(Directory="Directory")

sys.modules["hou"] = fake_hou

fake_husd = types.ModuleType("husd")
fake_outputprocessor = types.ModuleType("husd.outputprocessor")

class FakeBaseOutputProcessor:
    def __init__(self):
        self._configs = {}
    def evalConfig(self, name, node, overrides, t):
        return self._configs.get(name)
    def beginSave(self, config_node, config_overrides, lop_node, t, stage_variables):
        pass

fake_outputprocessor.OutputProcessor = FakeBaseOutputProcessor
fake_husd.outputprocessor = fake_outputprocessor
sys.modules["husd"] = fake_husd
sys.modules["husd.outputprocessor"] = fake_outputprocessor

# 加入 tools/outputprocessors 到 sys.path
sys.path.insert(0, os.path.abspath("tools/outputprocessors"))

from portablereferences import PortableReferences
from projectrootvariable import ProjectRootVariable


# 使用當前平台原生絕對路徑作為測試基準根目錄
TEST_BASE_DIR = normpath(os.path.abspath("test_workspace/show_A"))


class TestPortableReferences(unittest.TestCase):

    def setUp(self):
        self.processor = PortableReferences()

    def test_auto_package_root_detection(self):
        # 模擬輸出檔案在 chair/v002/asset.usd
        lop_out = f"{TEST_BASE_DIR}/publish/assets/props/chair/v002/asset.usd"
        self.processor._configs = {
            'lopoutput': lop_out,
            'portablereferences_package_root': ''
        }
        self.processor.beginSave(None, None, None, 0, None)

        # 驗證自動推導出 Package Root 為 chair
        expected_root = f"{TEST_BASE_DIR}/publish/assets/props/chair"
        self.assertEqual(self.processor.package_root, expected_root)

    def test_package_root_sub_object_upward_relpath(self):
        # Issue #3 核心測試：chair/v002/asset.usd 參照 chair/modelDefault/v001/model.usd
        lop_out = f"{TEST_BASE_DIR}/publish/assets/props/chair/v002/asset.usd"
        self.processor._configs = {
            'lopoutput': lop_out,
            'portablereferences_package_root': ''
        }
        self.processor.beginSave(None, None, None, 0, None)

        referencing_layer = lop_out
        sub_object_path = f"{TEST_BASE_DIR}/publish/assets/props/chair/modelDefault/v001/model.usd"

        result = self.processor.processReferencePath(sub_object_path, referencing_layer, True)
        self.assertEqual(result, '../modelDefault/v001/model.usd')

    def test_package_root_subfolder_relpath(self):
        # 同目錄或子目錄參照 (如 layers/sub.usd)
        lop_out = f"{TEST_BASE_DIR}/publish/assets/props/chair/v002/asset.usd"
        self.processor._configs = {
            'lopoutput': lop_out,
            'portablereferences_package_root': ''
        }
        self.processor.beginSave(None, None, None, 0, None)

        referencing_layer = lop_out
        layer_path = f"{TEST_BASE_DIR}/publish/assets/props/chair/v002/layers/sub.usd"

        result = self.processor.processReferencePath(layer_path, referencing_layer, True)
        self.assertEqual(result, 'layers/sub.usd')

    def test_outside_package_root_remains_absolute(self):
        # 超出 Package Root (例如引用 table Asset) 保持絕對路徑
        lop_out = f"{TEST_BASE_DIR}/publish/assets/props/chair/v002/asset.usd"
        self.processor._configs = {
            'lopoutput': lop_out,
            'portablereferences_package_root': ''
        }
        self.processor.beginSave(None, None, None, 0, None)

        referencing_layer = lop_out
        outside_path = f"{TEST_BASE_DIR}/publish/assets/props/table/v001/table.usd"

        result = self.processor.processReferencePath(outside_path, referencing_layer, True)
        self.assertEqual(result, outside_path)

    def test_explicit_package_root(self):
        # 明確手動指定 Package Root
        pkg_root = f"{TEST_BASE_DIR}/custom_build"
        lop_out = f"{pkg_root}/output.usd"
        self.processor._configs = {
            'lopoutput': lop_out,
            'portablereferences_package_root': pkg_root
        }
        self.processor.beginSave(None, None, None, 0, None)
        self.assertEqual(self.processor.package_root, pkg_root)


class TestProjectRootVariable(unittest.TestCase):

    def setUp(self):
        self.processor = ProjectRootVariable()

    def test_rewrite_absolute_path_to_variable(self):
        self.processor._configs = {
            'projectrootvariable_project_root': TEST_BASE_DIR
        }
        self.processor.beginSave(None, None, None, 0, None)

        abs_path = f"{TEST_BASE_DIR}/publish/assets/props/table/v001/table.usd"
        result = self.processor.processReferencePath(abs_path, f"{TEST_BASE_DIR}/any/layer.usd", True)
        self.assertEqual(result, '`"${PROJECT_ROOT}/publish/assets/props/table/v001/table.usd"`')

    def test_ignore_relative_path(self):
        self.processor._configs = {
            'projectrootvariable_project_root': TEST_BASE_DIR
        }
        self.processor.beginSave(None, None, None, 0, None)

        rel_path = '../modelDefault/v001/model.usd'
        result = self.processor.processReferencePath(rel_path, f"{TEST_BASE_DIR}/any/layer.usd", True)
        self.assertEqual(result, '../modelDefault/v001/model.usd')


if __name__ == '__main__':
    unittest.main()


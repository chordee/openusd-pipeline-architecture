import unittest
import types
import json
import sys
import os

# 加入 tools/layerinspector 到 sys.path
sys.path.insert(0, os.path.abspath("tools/layerinspector"))


class FakeLayer:
    def __init__(self, identifier, anonymous=False, real_path=""):
        self.identifier = identifier
        self.anonymous = anonymous
        self.realPath = real_path
        self.customLayerData = {}
        self.subLayerPaths = []
        self.dirty = False
        self._prims = {}

    def GetDisplayName(self):
        if self.anonymous:
            return "LOP"
        return os.path.basename(self.identifier)

    def GetPrimAtPath(self, path):
        return self._prims.get(path)


class FakePrimSpec:
    def __init__(self, customData=None):
        self.customData = customData or {}


class FakeStage:
    def __init__(self, root_layer, session_layer=None):
        self._root_layer = root_layer
        self._session_layer = session_layer or FakeLayer("anon:session", anonymous=True)
        self._layers = [self._root_layer]
        self._used_layers = [self._root_layer]
        self._muted_layers = set()

    def GetRootLayer(self):
        return self._root_layer

    def GetSessionLayer(self):
        return self._session_layer

    def GetLayerStack(self, includeSessionLayers=True):
        if includeSessionLayers:
            return [self._session_layer, self._root_layer]
        return [self._root_layer]

    def GetUsedLayers(self, includeClipLayers=True):
        return [self._session_layer, self._root_layer] + self._used_layers[1:]

    def IsLayerMuted(self, identifier):
        return identifier in self._muted_layers


# 模擬 Sdf 與 Usd
class FakeAssetPath:
    def __init__(self, path, resolvedPath=""):
        self.path = path
        self.resolvedPath = resolvedPath

fake_pxr = types.ModuleType("pxr")
fake_sdf = types.ModuleType("pxr.Sdf")
fake_usd = types.ModuleType("pxr.Usd")

fake_sdf.Layer = FakeLayer
fake_sdf.AssetPath = FakeAssetPath
fake_usd.Stage = FakeStage

# FindRelativeToLayer mock
def find_relative(layer, path):
    if "missing" in path:
        return None
    return FakeLayer(path)

fake_sdf.Layer.FindRelativeToLayer = staticmethod(find_relative)
fake_pxr.Sdf = fake_sdf
fake_pxr.Usd = fake_usd

sys.modules["pxr"] = fake_pxr
sys.modules["pxr.Sdf"] = fake_sdf
sys.modules["pxr.Usd"] = fake_usd

from layer_inspector import LayerInspector, layers_to_json


class TestLayerInspector(unittest.TestCase):

    def setUp(self):
        self.root_layer = FakeLayer("D:/projects/show_A/shot.usd", real_path="D:/projects/show_A/shot.usd")
        self.session_layer = FakeLayer("anon:0x1234_session", anonymous=True)
        self.stage = FakeStage(self.root_layer, self.session_layer)

    def test_layers_includes_session_layer_by_default(self):
        inspector = LayerInspector(self.stage)
        layer_ids = [l.identifier for l in inspector.layers()]
        self.assertIn(self.session_layer.identifier, layer_ids)
        self.assertIn(self.root_layer.identifier, layer_ids)

    def test_layers_excludes_session_layer_when_requested(self):
        inspector = LayerInspector(self.stage, include_session_layers=False)
        layer_ids = [l.identifier for l in inspector.layers()]
        self.assertNotIn(self.session_layer.identifier, layer_ids)
        self.assertIn(self.root_layer.identifier, layer_ids)

    def test_describe_implicit_sop_layer(self):
        sop_layer = FakeLayer("anon:0x5678_sop", anonymous=True)
        sop_layer.customLayerData = {
            "HoudiniTreatAsSopLayer": True,
            "HoudiniCreatorNode": 42
        }
        inspector = LayerInspector(self.stage)
        desc = inspector.describe(sop_layer)

        self.assertTrue(desc["implicit"])
        self.assertTrue(desc["isSopLayer"])
        self.assertFalse(desc["willWriteFile"])
        self.assertIsNone(desc["savePath"])

    def test_describe_explicit_layer(self):
        explicit_layer = FakeLayer("D:/projects/show_A/layers/props.usd", real_path="D:/projects/show_A/layers/props.usd")
        explicit_layer.customLayerData = {
            "HoudiniSavePath": "./layers/props.usd",
            "HoudiniSaveControl": "Explicit"
        }
        inspector = LayerInspector(self.stage)
        desc = inspector.describe(explicit_layer)

        self.assertFalse(desc["implicit"])
        self.assertEqual(desc["savePath"], "./layers/props.usd")
        self.assertEqual(desc["saveControl"], "Explicit")
        self.assertTrue(desc["willWriteFile"])

    def test_describe_non_writing_save_control(self):
        for ctrl in ["Placeholder", "DoNotSave"]:
            layer = FakeLayer("D:/projects/test.usd")
            layer.customLayerData = {
                "HoudiniSavePath": "./test.usd",
                "HoudiniSaveControl": ctrl
            }
            desc = LayerInspector(self.stage).describe(layer)
            self.assertFalse(desc["willWriteFile"])

    def test_unresolved_sublayers(self):
        self.root_layer.subLayerPaths = ["./existing.usd", "./missing_layer.usd"]
        inspector = LayerInspector(self.stage)
        missing = inspector.unresolved_sublayers()

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["subLayerPath"], "./missing_layer.usd")
        self.assertEqual(missing[0]["parent"], self.root_layer.identifier)

    def test_full_report_and_to_json(self):
        inspector = LayerInspector(self.stage)
        report = inspector.full_report()

        self.assertIn("layers", report)
        self.assertIn("summary", report)
        self.assertEqual(report["summary"]["total"], 2)

        json_str = inspector.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["summary"]["total"], 2)

    def test_describe_is_file_from_disk_uses_real_path(self):
        # 即使沒有 HoudiniSavePath，只要有 realPath 就應列入寫盤清單
        disk_layer = FakeLayer("D:/projects/show_A/existing.usd", real_path="D:/projects/show_A/existing.usd")
        disk_layer.customLayerData = {
            "HoudiniSaveControl": "IsFileFromDisk"
        }
        desc = LayerInspector(self.stage).describe(disk_layer)
        self.assertTrue(desc["willWriteFile"])
        self.assertFalse(desc["implicit"])

        # 驗證 full_report 的 pendingWrites 包含 realPath
        self.stage._used_layers.append(disk_layer)
        report = LayerInspector(self.stage).full_report()
        self.assertIn("D:/projects/show_A/existing.usd", report["summary"]["pendingWrites"])

    def test_path_violations_detection(self):
        # 違規 1：相對路徑向上溢出
        bad_layer1 = FakeLayer("anon:bad_geo1", anonymous=True)
        bad_layer1.customLayerData = {
            "HoudiniSavePath": "../tmp/bad.usd",
            "HoudiniSaveControl": "Explicit",
        }
        desc1 = LayerInspector(self.stage).describe(bad_layer1)
        self.assertFalse(desc1["isPathValid"])

        # 違規 2：路徑穿越逃逸 (layers/../../tmp/a.usd)
        bad_layer2 = FakeLayer("anon:bad_geo2", anonymous=True)
        bad_layer2.customLayerData = {
            "HoudiniSavePath": "layers/../../tmp/a.usd",
            "HoudiniSaveControl": "Explicit",
        }
        desc2 = LayerInspector(self.stage).describe(bad_layer2)
        self.assertFalse(desc2["isPathValid"])

        # 違規 3：Explicit 但缺少 HoudiniSavePath (None 或空字串)
        bad_layer3 = FakeLayer("anon:bad_geo3", anonymous=True)
        bad_layer3.customLayerData = {
            "HoudiniSaveControl": "Explicit",
            # 無 HoudiniSavePath
        }
        desc3 = LayerInspector(self.stage).describe(bad_layer3)
        self.assertFalse(desc3["isPathValid"])

        bad_layer4 = FakeLayer("anon:bad_geo4", anonymous=True)
        bad_layer4.customLayerData = {
            "HoudiniSavePath": "   ",
            "HoudiniSaveControl": "Explicit",
        }
        desc4 = LayerInspector(self.stage).describe(bad_layer4)
        self.assertFalse(desc4["isPathValid"])

        # 違規 5：絕對路徑 (POSIX 根目錄或 Windows 磁碟機代號)
        bad_layer5 = FakeLayer("anon:bad_geo5", anonymous=True)
        bad_layer5.customLayerData = {
            "HoudiniSavePath": "/layers/geo.usd",
            "HoudiniSaveControl": "Explicit",
        }
        self.assertFalse(LayerInspector(self.stage).describe(bad_layer5)["isPathValid"])

        bad_layer6 = FakeLayer("anon:bad_geo6", anonymous=True)
        bad_layer6.customLayerData = {
            "HoudiniSavePath": "C:/layers/geo.usd",
            "HoudiniSaveControl": "Explicit",
        }
        self.assertFalse(LayerInspector(self.stage).describe(bad_layer6)["isPathValid"])

        # 合規路徑：./layers/、layers/sub/、sublayers/
        good_layer1 = FakeLayer("anon:good_geo1", anonymous=True)
        good_layer1.customLayerData = {
            "HoudiniSavePath": "./layers/geo.usd",
            "HoudiniSaveControl": "Explicit",
        }
        self.assertTrue(LayerInspector(self.stage).describe(good_layer1)["isPathValid"])

        good_layer2 = FakeLayer("anon:good_geo2", anonymous=True)
        good_layer2.customLayerData = {
            "HoudiniSavePath": "sublayers/nested/anim.usd",
            "HoudiniSaveControl": "Explicit",
        }
        self.assertTrue(LayerInspector(self.stage).describe(good_layer2)["isPathValid"])

        # 驗證 full_report
        self.stage._used_layers.extend([bad_layer1, bad_layer2, bad_layer3, good_layer1])
        report = LayerInspector(self.stage).full_report()
        self.assertTrue(report["summary"]["hasPathViolations"])
        # 找出違規項目，應有 3 個
        violations = report["pathViolations"]
        self.assertEqual(len(violations), 3)
        save_paths = [v["savePath"] for v in violations]
        self.assertIn("../tmp/bad.usd", save_paths)
        self.assertIn("layers/../../tmp/a.usd", save_paths)
        self.assertIn(None, save_paths)

        # 驗證 print_summary 執行不會丟出例外
        LayerInspector(self.stage).print_summary()

    def test_to_json_serializes_asset_path_object(self):
        # HoudiniSavePath 若為 Sdf.AssetPath 物件，to_json 不應丟出 TypeError
        asset_layer = FakeLayer("D:/projects/asset.usd")
        asset_layer.customLayerData = {
            "HoudiniSavePath": FakeAssetPath("./layers/asset.usd", "D:/projects/layers/asset.usd"),
            "HoudiniSaveControl": "Explicit"
        }
        self.stage._used_layers.append(asset_layer)
        inspector = LayerInspector(self.stage)
        json_output = inspector.to_json()
        parsed = json.loads(json_output)
        self.assertIn("layers", parsed)

    def test_implicit_determined_by_save_control(self):
        # 即使圖層 anonymous，只要有 Explicit 就不是 implicit
        anon_explicit = FakeLayer("anon:explicit", anonymous=True)
        anon_explicit.customLayerData = {
            "HoudiniSaveControl": "Explicit",
            "HoudiniSavePath": "./layers/geo.usd"
        }
        desc = LayerInspector(self.stage).describe(anon_explicit)
        self.assertFalse(desc["implicit"])

        # 即使有實體 realPath，只要無 SaveControl 就是 implicit (Houdini 預設 fold 入 parent)
        disk_implicit = FakeLayer("D:/projects/disk.usd", real_path="D:/projects/disk.usd")
        desc_disk = LayerInspector(self.stage).describe(disk_implicit)
        self.assertTrue(desc_disk["implicit"])


if __name__ == '__main__':
    unittest.main()

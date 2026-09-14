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

    def test_print_summary(self):
        import io
        from contextlib import redirect_stdout

        inspector = LayerInspector(self.stage)
        buf = io.StringIO()
        with redirect_stdout(buf):
            inspector.print_summary()
        output = buf.getvalue()

        self.assertIn("Houdini Solaris Layer Inspector", output)
        self.assertIn("總圖層數: 2", output)


if __name__ == '__main__':
    unittest.main()

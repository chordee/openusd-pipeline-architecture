"""Tests for point_cache_splitter.

Needs ``pxr``; run with hython or any interpreter that has USD available:

    hython -m unittest discover tools/pointcachesplitter/tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pxr import Gf, Sdf, Usd, UsdGeom, Vt  # noqa: E402

from point_cache_splitter import PointCacheSplitter, VaryingTopologyError  # noqa: E402

FRAME_1 = [Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)]
FRAME_2 = [Gf.Vec3f(0, 0, 0), Gf.Vec3f(10, 0, 0), Gf.Vec3f(0, 10, 0)]


def build_deforming_prop(path, animate_transform=True):
    """A fixed-topology mesh whose points deform, with a stale static extent."""
    stage = Usd.Stage.CreateNew(path)
    stage.SetMetadata("upAxis", "Y")
    stage.SetMetadata("metersPerUnit", 1.0)
    stage.SetTimeCodesPerSecond(24)
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(2)

    root = stage.DefinePrim("/ROOT", "Xform")
    stage.SetDefaultPrim(root)

    mesh = UsdGeom.Mesh.Define(stage, "/ROOT/Flag")
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    mesh.CreatePointsAttr().Set(Vt.Vec3fArray(FRAME_1), 1.0)
    mesh.CreatePointsAttr().Set(Vt.Vec3fArray(FRAME_2), 2.0)
    mesh.CreateVelocitiesAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0)] * 3), 1.0)
    # Deliberately stale: authored once, never updated for frame 2.
    mesh.CreateExtentAttr([Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 1, 0)])

    if animate_transform:
        op = UsdGeom.Xformable(mesh).AddTranslateOp()
        op.Set(Gf.Vec3d(0, 0, 0), 1.0)
        op.Set(Gf.Vec3d(5, 0, 0), 2.0)

    stage.Save()
    return stage


class PointCacheSplitterTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "prop.usda")
        self.geo_path = os.path.join(self.tmp, "geo.usda")
        self.xform_path = os.path.join(self.tmp, "xform.usda")

    def _split(self, **kwargs):
        stage = build_deforming_prop(self.src, **kwargs)
        splitter = PointCacheSplitter(stage)
        geo_layer, xform_layer = splitter.split(self.geo_path, self.xform_path)
        return stage, geo_layer, xform_layer

    # -- discovery ---------------------------------------------------------

    def test_discovers_deform_and_transform_attributes(self):
        stage = build_deforming_prop(self.src)
        animated = PointCacheSplitter(stage).animated_attributes()
        self.assertEqual(list(animated.keys()), [Sdf.Path("/ROOT/Flag")])
        self.assertEqual(sorted(animated[Sdf.Path("/ROOT/Flag")]),
                         ["points", "velocities", "xformOp:translate"])

    def test_rejects_varying_topology(self):
        """USD's schema allows per-frame topology, so it must be checked."""
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/M")
        mesh.CreateFaceVertexCountsAttr().Set([3], 1.0)
        mesh.CreateFaceVertexCountsAttr().Set([4], 2.0)
        mesh.CreatePointsAttr().Set(Vt.Vec3fArray(FRAME_1), 1.0)
        with self.assertRaises(VaryingTopologyError):
            PointCacheSplitter(stage).animated_attributes()

    # -- static layer ------------------------------------------------------

    def test_geo_layer_has_no_time_samples(self):
        _, geo_layer, _ = self._split()
        spec = geo_layer.GetPrimAtPath("/ROOT/Flag")
        for name in ("points", "velocities", "xformOp:translate", "extent"):
            attr = spec.properties.get(name)
            if attr is not None:
                self.assertFalse(attr.HasInfo("timeSamples"),
                                 "{} must not carry time samples".format(name))

    def test_geo_layer_keeps_bind_pose_and_matching_extent(self):
        _, geo_layer, _ = self._split()
        spec = geo_layer.GetPrimAtPath("/ROOT/Flag")
        self.assertEqual(list(spec.properties["points"].default), FRAME_1)
        self.assertEqual(list(spec.properties["extent"].default),
                         [Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 1, 0)])

    def test_geo_layer_keeps_topology(self):
        _, geo_layer, _ = self._split()
        spec = geo_layer.GetPrimAtPath("/ROOT/Flag")
        self.assertEqual(list(spec.properties["faceVertexIndices"].default), [0, 1, 2])

    def test_flatten_provenance_not_published(self):
        _, geo_layer, _ = self._split()
        self.assertFalse(geo_layer.pseudoRoot.HasInfo("documentation"))

    # -- time-sampled layer ------------------------------------------------

    def test_xform_layer_carries_the_samples(self):
        _, _, xform_layer = self._split()
        points = xform_layer.GetAttributeAtPath("/ROOT/Flag.points")
        self.assertEqual(sorted(points.GetInfo("timeSamples").keys()), [1.0, 2.0])
        self.assertIsNotNone(
            xform_layer.GetAttributeAtPath("/ROOT/Flag.xformOp:translate"))
        self.assertIsNotNone(xform_layer.GetAttributeAtPath("/ROOT/Flag.velocities"))

    def test_extent_is_recomputed_per_frame(self):
        """USD never derives extent from points; a stale one must not survive."""
        _, _, xform_layer = self._split()
        samples = xform_layer.GetAttributeAtPath("/ROOT/Flag.extent").GetInfo("timeSamples")
        self.assertEqual(list(samples[2.0]), [Gf.Vec3f(0, 0, 0), Gf.Vec3f(10, 10, 0)])

    # -- metadata ----------------------------------------------------------

    def test_stage_metadata_copied_to_both_layers(self):
        _, geo_layer, xform_layer = self._split()
        for layer in (geo_layer, xform_layer):
            self.assertEqual(layer.pseudoRoot.GetInfo("upAxis"), "Y")
            self.assertEqual(layer.pseudoRoot.GetInfo("timeCodesPerSecond"), 24)
            self.assertEqual(layer.defaultPrim, "ROOT")

    # -- round trip --------------------------------------------------------

    def test_recomposed_bound_follows_the_deformation(self):
        """The whole point: a stale extent would freeze the bound at frame 1."""
        _, geo_layer, xform_layer = self._split(animate_transform=False)
        composed = Usd.Stage.CreateInMemory()
        composed.GetRootLayer().subLayerPaths = [
            xform_layer.identifier, geo_layer.identifier]

        cache = UsdGeom.BBoxCache(2.0, [UsdGeom.Tokens.default_])
        bound = cache.ComputeWorldBound(
            composed.GetPrimAtPath("/ROOT/Flag")).ComputeAlignedRange()
        self.assertEqual(bound.GetMax(), Gf.Vec3d(10, 10, 0))

    def test_splits_geometry_arriving_by_reference(self):
        """Sdf.CopySpec sees no specs for referenced prims in the root layer."""
        inner = os.path.join(self.tmp, "inner.usda")
        build_deforming_prop(inner, animate_transform=False)

        outer = Usd.Stage.CreateNew(os.path.join(self.tmp, "outer.usda"))
        root = outer.OverridePrim("/ROOT")
        root.GetReferences().AddReference(inner, "/ROOT")
        outer.SetDefaultPrim(root)
        outer.Save()

        geo_layer, xform_layer = PointCacheSplitter(outer).split(
            self.geo_path, self.xform_path)
        self.assertIsNotNone(geo_layer.GetPrimAtPath("/ROOT/Flag"))
        self.assertEqual(
            sorted(xform_layer.GetAttributeAtPath(
                "/ROOT/Flag.points").GetInfo("timeSamples").keys()),
            [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()

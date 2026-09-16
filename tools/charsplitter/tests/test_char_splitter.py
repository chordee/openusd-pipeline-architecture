"""Tests for char_splitter.

Needs ``pxr``; run with hython or any interpreter that has USD available:

    hython -m unittest discover tools/charsplitter/tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt  # noqa: E402

from char_splitter import CharacterSplitter  # noqa: E402


def build_character(path, skinning_method="dualQuaternion", per_mesh_joints=None):
    """A minimal rigged character whose binding lives only on the SkelRoot.

    Authoring ``skel:skeleton`` / ``skel:animationSource`` on the ancestor is the
    namespace-inheritance case that a naive spec copy silently loses.
    """
    stage = Usd.Stage.CreateNew(path)
    stage.SetMetadata("upAxis", "Y")
    stage.SetMetadata("metersPerUnit", 1.0)
    stage.SetTimeCodesPerSecond(24)
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(10)

    root = UsdSkel.Root.Define(stage, "/ROOT")
    stage.SetDefaultPrim(root.GetPrim())

    skel = UsdSkel.Skeleton.Define(stage, "/ROOT/Skel")
    skel.CreateJointsAttr(["Hips", "Hips/Spine"])
    skel.CreateBindTransformsAttr([Gf.Matrix4d(1)] * 2)
    skel.CreateRestTransformsAttr([Gf.Matrix4d(1)] * 2)

    blend = UsdSkel.BlendShape.Define(stage, "/ROOT/Skel/BlendShapes/Smile")
    blend.CreateOffsetsAttr([Gf.Vec3f(0, 1, 0)])
    blend.CreatePointIndicesAttr([0])

    anim = UsdSkel.Animation.Define(stage, "/ROOT/AnimData")
    anim.CreateJointsAttr(["Hips", "Hips/Spine"])
    anim.CreateTranslationsAttr().Set([Gf.Vec3f(0, 0, 0)] * 2, 1.0)
    anim.CreateRotationsAttr().Set([Gf.Quatf(1)] * 2, 1.0)
    anim.CreateScalesAttr().Set([Gf.Vec3h(1)] * 2, 1.0)
    anim.CreateBlendShapesAttr(["Smile"])
    anim.CreateBlendShapeWeightsAttr().Set([0.5], 1.0)

    stage.DefinePrim("/ROOT/Geometry", "Xform")
    mesh = UsdGeom.Mesh.Define(stage, "/ROOT/Geometry/Body")
    mesh.CreatePointsAttr([Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0)])

    mesh_binding = UsdSkel.BindingAPI.Apply(mesh.GetPrim())
    mesh_binding.CreateJointIndicesPrimvar(False, 1).Set(Vt.IntArray([0, 1]))
    mesh_binding.CreateJointWeightsPrimvar(False, 1).Set(Vt.FloatArray([1.0, 1.0]))
    mesh_binding.CreateGeomBindTransformAttr(Gf.Matrix4d(1))
    mesh_binding.CreateSkinningMethodAttr(skinning_method)
    mesh_binding.CreateBlendShapesAttr(["Smile"])
    mesh_binding.CreateBlendShapeTargetsRel().SetTargets([blend.GetPath()])
    if per_mesh_joints:
        mesh_binding.CreateJointsAttr(per_mesh_joints)

    root_binding = UsdSkel.BindingAPI.Apply(root.GetPrim())
    root_binding.CreateSkeletonRel().SetTargets([skel.GetPath()])
    root_binding.CreateAnimationSourceRel().SetTargets([anim.GetPath()])

    stage.Save()
    return stage


class CharSplitterTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "char.usda")
        self.skel_path = os.path.join(self.tmp, "skel.usda")
        self.anim_path = os.path.join(self.tmp, "anim.usda")

    def _split(self, **kwargs):
        stage = build_character(self.src, **kwargs)
        splitter = CharacterSplitter(stage)
        skel_layer, anim_layer = splitter.split(self.skel_path, self.anim_path)
        return stage, skel_layer, anim_layer

    # -- discovery ---------------------------------------------------------

    def test_discovers_binding_authored_on_ancestor(self):
        stage = build_character(self.src)
        bindings = CharacterSplitter(stage).bindings()
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].skeleton_path, Sdf.Path("/ROOT/Skel"))
        self.assertEqual(bindings[0].anim_path, Sdf.Path("/ROOT/AnimData"))
        self.assertEqual(bindings[0].skinned_mesh_paths, [Sdf.Path("/ROOT/Geometry/Body")])
        self.assertEqual(bindings[0].blend_shape_paths,
                         [Sdf.Path("/ROOT/Skel/BlendShapes/Smile")])

    # -- static layer ------------------------------------------------------

    def test_skel_layer_binds_mesh_without_relying_on_inheritance(self):
        _, skel_layer, _ = self._split()
        mesh = skel_layer.GetPrimAtPath("/ROOT/Geometry/Body")
        rel = mesh.relationships.get("skel:skeleton")
        self.assertIsNotNone(rel, "skel:skeleton must be authored on the mesh itself")
        self.assertEqual(list(rel.targetPathList.explicitItems), [Sdf.Path("/ROOT/Skel")])
        self.assertIn("SkelBindingAPI", mesh.GetInfo("apiSchemas").explicitItems)

    def test_non_default_skinning_method_survives(self):
        _, skel_layer, _ = self._split(skinning_method="dualQuaternion")
        attr = skel_layer.GetAttributeAtPath(
            "/ROOT/Geometry/Body.primvars:skel:skinningMethod")
        self.assertEqual(attr.default, "dualQuaternion")

    def test_per_mesh_joint_remapping_survives(self):
        _, skel_layer, _ = self._split(per_mesh_joints=["Hips/Spine"])
        attr = skel_layer.GetAttributeAtPath("/ROOT/Geometry/Body.skel:joints")
        self.assertEqual(list(attr.default), ["Hips/Spine"])

    def test_element_size_survives(self):
        _, skel_layer, _ = self._split()
        attr = skel_layer.GetAttributeAtPath(
            "/ROOT/Geometry/Body.primvars:skel:jointIndices")
        self.assertEqual(attr.GetInfo("elementSize"), 1)

    def test_skel_layer_excludes_animation(self):
        _, skel_layer, _ = self._split()
        self.assertIsNone(skel_layer.GetPrimAtPath("/ROOT/AnimData"))

    def test_animation_source_is_repointed_not_cleared(self):
        _, skel_layer, _ = self._split()
        rel = skel_layer.GetPrimAtPath("/ROOT/Skel").relationships.get(
            "skel:animationSource")
        self.assertIsNotNone(rel)
        self.assertEqual(list(rel.targetPathList.explicitItems),
                         [Sdf.Path("/ROOT/AnimData")])

    # -- time-sampled layer ------------------------------------------------

    def test_anim_layer_holds_only_animation(self):
        _, _, anim_layer = self._split()
        self.assertIsNotNone(anim_layer.GetPrimAtPath("/ROOT/AnimData"))
        self.assertIsNone(anim_layer.GetPrimAtPath("/ROOT/Skel"))
        self.assertIsNone(anim_layer.GetPrimAtPath("/ROOT/Geometry/Body"))

    # -- metadata ----------------------------------------------------------

    def test_stage_metadata_copied_to_both_layers(self):
        _, skel_layer, anim_layer = self._split()
        for layer in (skel_layer, anim_layer):
            root = layer.pseudoRoot
            self.assertEqual(root.GetInfo("upAxis"), "Y")
            self.assertEqual(root.GetInfo("metersPerUnit"), 1.0)
            self.assertEqual(root.GetInfo("timeCodesPerSecond"), 24)
            self.assertEqual(layer.defaultPrim, "ROOT")

    # -- round trip --------------------------------------------------------

    def test_recomposition_resolves_full_binding(self):
        stage, skel_layer, anim_layer = self._split()
        composed = Usd.Stage.CreateInMemory()
        composed.GetRootLayer().subLayerPaths = [
            anim_layer.identifier,
            skel_layer.identifier,
            stage.GetRootLayer().identifier,
        ]

        cache = UsdSkel.Cache()
        root = UsdSkel.Root(composed.GetPrimAtPath("/ROOT"))
        cache.Populate(root, Usd.PrimDefaultPredicate)
        bindings = cache.ComputeSkelBindings(root, Usd.PrimDefaultPredicate)

        self.assertEqual(len(bindings), 1)
        skel_query = cache.GetSkelQuery(bindings[0].GetSkeleton())
        self.assertIsNotNone(skel_query.GetAnimQuery())
        self.assertEqual(skel_query.GetAnimQuery().GetPrim().GetPath(),
                         Sdf.Path("/ROOT/AnimData"))

        targets = bindings[0].GetSkinningTargets()
        self.assertEqual(len(targets), 1)
        mesh = targets[0].GetPrim()
        self.assertEqual(mesh.GetAttribute("primvars:skel:skinningMethod").Get(),
                         "dualQuaternion")


if __name__ == "__main__":
    unittest.main()

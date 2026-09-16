"""Split a composed character stage into static (``skel``) and time-sampled (``anim``) layers.

The character animation publish unit keeps two sub-objects whose boundary is
*static versus time-sampled*, not schema class (see ``docs/usd-publish-packaging.md``
範例 C):

``skel``
    ``Skeleton`` topology / bind / rest transforms, ``BlendShape`` bodies, and
    every skinned mesh's binding data (joint indices & weights, ``skel:joints``
    remapping, ``skinningMethod``, ``geomBindTransform``).

``anim``
    ``SkelAnimation`` prims only — joint transforms and blend shape weights
    over time.

Discovery is schema-based (``UsdSkel.Cache``), never path-guessing, so it does
not care where the exporter placed the Skeleton, Animation or BlendShape prims.

Needs only ``pxr``; no DCC required.
"""

from typing import List, Optional, Tuple

from pxr import Sdf, Usd, UsdSkel

#: Layer metadata that does not compose through ``subLayers`` and therefore
#: must be copied verbatim onto every layer written out.
_STAGE_METADATA = (
    "upAxis",
    "metersPerUnit",
    "timeCodesPerSecond",
    "framesPerSecond",
    "startTimeCode",
    "endTimeCode",
)

#: Per-mesh binding properties that a spec-level copy would otherwise drop.
_SKIN_PROPERTIES = (
    "primvars:skel:jointIndices",
    "primvars:skel:jointWeights",
    "primvars:skel:geomBindTransform",
    "primvars:skel:skinningMethod",
    "skel:joints",
    "skel:blendShapes",
)



def _prepend_api_schema(spec: Sdf.PrimSpec, schema: str) -> None:
    """Add ``schema`` to ``spec``'s applied API schemas without clobbering others.

    Prepend, never explicit: an explicit list op replaces the weaker layer's
    ``apiSchemas`` wholesale, silently dropping ``MaterialBindingAPI`` and every
    other API schema the geometry package applied.
    """
    existing = spec.GetInfo("apiSchemas") if spec.HasInfo("apiSchemas") else None
    prepended = list(existing.prependedItems) if existing else []
    if schema not in prepended:
        prepended.insert(0, schema)
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=prepended))


class SkelBinding:
    """One ``SkelRoot``'s resolved skeleton / animation / mesh / blendshape graph."""

    def __init__(self, skel_root_path, skeleton_path, anim_path,
                 skinned_mesh_paths, blend_shape_paths):
        self.skel_root_path = skel_root_path
        self.skeleton_path = skeleton_path
        self.anim_path = anim_path
        self.skinned_mesh_paths = skinned_mesh_paths
        self.blend_shape_paths = blend_shape_paths

    def __repr__(self):
        return ("SkelBinding(skeleton={}, anim={}, meshes={}, blendShapes={})".format(
            self.skeleton_path, self.anim_path,
            len(self.skinned_mesh_paths), len(self.blend_shape_paths)))


class CharacterSplitter:
    """Split ``stage`` into a static ``skel`` layer and a time-sampled ``anim`` layer."""

    def __init__(self, stage: Usd.Stage):
        self._stage = stage
        self._bindings: Optional[List[SkelBinding]] = None
        self._flat: Optional[Sdf.Layer] = None

    # -- discovery ---------------------------------------------------------

    def bindings(self) -> List[SkelBinding]:
        """Resolve every skinning binding on the stage, caching the result.

        ``UsdSkel.Cache`` silently skips skinning targets whose prim — or any
        ancestor between the ``SkelRoot`` and the mesh — is untyped, so a stage
        assembled from ``over``-only or typeless layers yields nothing here.
        Always run this against the *composed* stage.
        """
        if self._bindings is not None:
            return self._bindings

        cache = UsdSkel.Cache()
        found: List[SkelBinding] = []

        for prim in self._stage.Traverse():
            if not prim.IsA(UsdSkel.Root):
                continue
            skel_root = UsdSkel.Root(prim)
            cache.Populate(skel_root, Usd.PrimDefaultPredicate)

            for binding in cache.ComputeSkelBindings(skel_root, Usd.PrimDefaultPredicate):
                skeleton = binding.GetSkeleton()
                skel_query = cache.GetSkelQuery(skeleton)
                anim_query = skel_query.GetAnimQuery() if skel_query else None

                mesh_paths = [t.GetPrim().GetPath() for t in binding.GetSkinningTargets()]

                blend_shapes: List[Sdf.Path] = []
                for mesh_path in mesh_paths:
                    mesh_binding = UsdSkel.BindingAPI(self._stage.GetPrimAtPath(mesh_path))
                    for bs_path in mesh_binding.GetBlendShapeTargetsRel().GetTargets():
                        if bs_path not in blend_shapes:
                            blend_shapes.append(bs_path)

                found.append(SkelBinding(
                    skel_root_path=prim.GetPath(),
                    skeleton_path=skeleton.GetPrim().GetPath(),
                    anim_path=anim_query.GetPrim().GetPath() if anim_query else None,
                    skinned_mesh_paths=mesh_paths,
                    blend_shape_paths=blend_shapes,
                ))

        self._bindings = found
        return found

    # -- output ------------------------------------------------------------

    def split(self, skel_path: str, anim_path: str) -> Tuple[Sdf.Layer, Sdf.Layer]:
        """Write both layers and return them as ``(skel_layer, anim_layer)``."""
        return self.write_skel(skel_path), self.write_anim(anim_path)

    def write_skel(self, path: str) -> Sdf.Layer:
        """Write the static layer: Skeleton, BlendShape and per-mesh binding data."""
        layer = Sdf.Layer.CreateNew(path)
        self._copy_stage_metadata(layer)

        for binding in self.bindings():
            self._copy_subtree(layer, binding.skeleton_path)
            self._drop_animation(layer, binding.anim_path)
            self._repoint_animation_source(layer, binding)

            for bs_path in binding.blend_shape_paths:
                self._copy_subtree(layer, bs_path)
            for mesh_path in binding.skinned_mesh_paths:
                self._copy_mesh_binding(layer, mesh_path, binding.skeleton_path)

        layer.Save()
        return layer

    def write_anim(self, path: str) -> Sdf.Layer:
        """Write the time-sampled layer: ``SkelAnimation`` prims only."""
        layer = Sdf.Layer.CreateNew(path)
        self._copy_stage_metadata(layer)
        for binding in self.bindings():
            if binding.anim_path:
                self._copy_subtree(layer, binding.anim_path)
        layer.Save()
        return layer

    # -- internals ---------------------------------------------------------

    def _copy_stage_metadata(self, layer: Sdf.Layer) -> None:
        """Layer metadata does not compose through ``subLayers``; copy it verbatim."""
        source = self._stage.GetRootLayer().pseudoRoot
        for key in _STAGE_METADATA:
            if source.HasInfo(key):
                layer.pseudoRoot.SetInfo(key, source.GetInfo(key))
        if self._stage.GetRootLayer().defaultPrim:
            layer.defaultPrim = self._stage.GetRootLayer().defaultPrim

    def _ensure_ancestors(self, layer: Sdf.Layer, path: Sdf.Path) -> None:
        """Give every ancestor a ``def`` spec carrying its composed type name.

        ``Sdf.CopySpec`` needs the destination parent to exist, and an untyped
        ancestor makes ``UsdSkel.Cache`` skip everything beneath it — so the
        composed type is carried over rather than left blank.
        """
        for ancestor in reversed(list(path.GetAncestorsRange())):
            if ancestor.IsAbsoluteRootPath() or ancestor == path:
                continue
            spec = layer.GetPrimAtPath(ancestor) or Sdf.CreatePrimInLayer(layer, ancestor)
            spec.specifier = Sdf.SpecifierDef
            source = self._stage.GetPrimAtPath(ancestor)
            if source and source.GetTypeName():
                spec.typeName = source.GetTypeName()

    def _source_layer(self) -> Sdf.Layer:
        """The composed stage flattened into one layer, cached.

        ``Sdf.CopySpec`` is not composition-aware: it copies only the specs
        authored in the layer it is handed. A character whose skeleton or
        geometry arrives through a reference, payload, sublayer or variant has
        no such specs in the stage's root layer, and the copy raises "cannot
        copy unknown spec". Flattening first gives every composed prim a real
        spec at the same path.
        """
        if self._flat is None:
            self._flat = self._stage.Flatten()
        return self._flat

    def _copy_subtree(self, layer: Sdf.Layer, path: Sdf.Path) -> None:
        self._ensure_ancestors(layer, path)
        Sdf.CreatePrimInLayer(layer, path)
        if not Sdf.CopySpec(self._source_layer(), path, layer, path):
            raise RuntimeError("failed to copy spec at {}".format(path))

    def _drop_animation(self, layer: Sdf.Layer, anim_path: Optional[Sdf.Path]) -> None:
        """Remove the Animation prim the subtree copy dragged in — it belongs to anim.

        Keyed off the resolved ``anim_path`` rather than the Skeleton's direct
        children, so an Animation nested any number of levels down (say
        ``/ROOT/Skel/Rig/Anim``) is still removed.
        """
        if not anim_path:
            return
        spec = layer.GetPrimAtPath(anim_path)
        if spec:
            del spec.nameParent.nameChildren[spec.name]

    def _repoint_animation_source(self, layer: Sdf.Layer, binding: SkelBinding) -> None:
        """Retarget rather than clear ``skel:animationSource``.

        The target is a prim path in the shared namespace, not a reference to
        the anim file, so it reconnects automatically once anim is composed
        alongside and merely dangles harmlessly otherwise.
        """
        if not binding.anim_path:
            return
        spec = layer.GetPrimAtPath(binding.skeleton_path)
        # SkelBindingAPI may have been applied on an ancestor rather than the
        # Skeleton itself; without it here the relationship below is inert.
        _prepend_api_schema(spec, "SkelBindingAPI")
        rel = spec.relationships.get("skel:animationSource")
        if rel is None:
            rel = Sdf.RelationshipSpec(spec, "skel:animationSource", False)
        rel.targetPathList.explicitItems[:] = [binding.anim_path]

    def _copy_mesh_binding(self, layer: Sdf.Layer, mesh_path: Sdf.Path,
                           skeleton_path: Sdf.Path) -> None:
        """Copy one mesh's binding data, re-applying what namespace inheritance hid.

        ``skel:skeleton`` / ``skel:animationSource`` are namespace-inherited and
        ``SkelBindingAPI`` may live on an ancestor, so a spec-level copy of the
        mesh alone silently loses the binding. The schema is re-applied and the
        skeleton relationship written explicitly onto the mesh itself.
        """
        source = self._stage.GetPrimAtPath(mesh_path)
        self._ensure_ancestors(layer, mesh_path)

        spec = layer.GetPrimAtPath(mesh_path) or Sdf.CreatePrimInLayer(layer, mesh_path)
        spec.specifier = Sdf.SpecifierDef
        if source.GetTypeName():
            spec.typeName = source.GetTypeName()
        _prepend_api_schema(spec, "SkelBindingAPI")

        for name in _SKIN_PROPERTIES:
            attr = source.GetAttribute(name)
            if not attr or not attr.HasAuthoredValue():
                continue
            attr_spec = Sdf.AttributeSpec(spec, name, attr.GetTypeName(), Sdf.VariabilityVarying, False)
            attr_spec.default = attr.Get()
            for meta in ("elementSize", "interpolation"):
                value = attr.GetMetadata(meta)
                if value:
                    attr_spec.SetInfo(meta, value)

        rel = Sdf.RelationshipSpec(spec, "skel:skeleton", False)
        rel.targetPathList.explicitItems[:] = [skeleton_path]

        bs_rel = UsdSkel.BindingAPI(source).GetBlendShapeTargetsRel()
        targets = bs_rel.GetTargets() if bs_rel else []
        if targets:
            out_rel = Sdf.RelationshipSpec(spec, "skel:blendShapeTargets", False)
            out_rel.targetPathList.explicitItems[:] = list(targets)

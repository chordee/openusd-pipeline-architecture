"""Split a deforming-geometry stage into static (``geo``) and time-sampled (``xform``) layers.

The ``propAnim`` publish unit keeps two sub-objects on the same static/time-sampled
boundary as ``charAnim`` (see ``docs/usd-animation-layer.md``):

``geo``
    Topology, UVs and the bind-pose ``points`` — everything that does not change
    over time.

``xform``
    ``points`` (and companion ``velocities`` / ``normals`` / ``accelerations``)
    time samples, ``xformOp`` time samples, and a per-frame ``extent``.

Two things this handles that are easy to get silently wrong:

* **``extent`` does not follow ``points``.** USD never recomputes it, so moving
  animated points to another layer while leaving a static extent behind gives
  wrong frustum culling and wrong ``drawMode = "bounds"`` proxies — with no error.
* **Fixed topology is a pipeline constraint, not a schema guarantee.**
  ``faceVertexCounts`` / ``faceVertexIndices`` are *varying* in the schema, so USD
  happily accepts per-frame topology. It has to be checked, not assumed.

Needs only ``pxr``; no DCC required.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

#: Layer metadata that does not compose through ``subLayers``.
_STAGE_METADATA = (
    "upAxis",
    "metersPerUnit",
    "timeCodesPerSecond",
    "framesPerSecond",
    "startTimeCode",
    "endTimeCode",
)

#: Point-based attributes that must travel together — leaving ``velocities``
#: behind while ``points`` move gives a mismatched motion-blur velocity field.
_DEFORM_ATTRIBUTES = ("points", "velocities", "accelerations", "normals")

#: Never carried over from the source: topology is validated constant and folded
#: into the geo layer, and ``extent`` is always recomputed from ``points`` — copying
#: the source's would both duplicate the spec and preserve a possibly stale box.
#: Topology must not vary over time for a point cache to be meaningful.
_TOPOLOGY_ATTRIBUTES = (
    "faceVertexCounts",
    "faceVertexIndices",
    "holeIndices",
    "cornerIndices",
    "creaseIndices",
    "creaseLengths",
)

_EXCLUDED_ATTRIBUTES = frozenset(_TOPOLOGY_ATTRIBUTES) | {"extent"}


class VaryingTopologyError(ValueError):
    """Raised when a mesh's topology changes over time."""


def _time_samples(layer: Sdf.Layer, attr: Usd.Attribute) -> List[float]:
    spec = layer.GetAttributeAtPath(attr.GetPath())
    return list(spec.GetInfo("timeSamples").keys()) if spec and spec.HasInfo("timeSamples") else []


def _extent_of(points: Sequence) -> Optional[Vt.Vec3fArray]:
    if not len(points):
        return None
    lo = Gf.Vec3f(*(min(p[i] for p in points) for i in range(3)))
    hi = Gf.Vec3f(*(max(p[i] for p in points) for i in range(3)))
    return Vt.Vec3fArray([lo, hi])


class PointCacheSplitter:
    """Split ``stage`` into a static ``geo`` layer and a time-sampled ``xform`` layer."""

    def __init__(self, stage: Usd.Stage):
        self._stage = stage
        self._flat: Optional[Sdf.Layer] = None
        self._animated: Optional[Dict[Sdf.Path, List[str]]] = None

    # -- discovery ---------------------------------------------------------

    def animated_attributes(self) -> Dict[Sdf.Path, List[str]]:
        """Map each prim path to the names of its time-sampled attributes.

        Validates fixed topology on the way through: USD's schema marks
        ``faceVertexCounts`` / ``faceVertexIndices`` as varying, so per-frame
        topology composes without complaint and would silently mis-pair points
        with faces once split.
        """
        if self._animated is not None:
            return self._animated

        layer = self._source_layer()
        found: Dict[Sdf.Path, List[str]] = {}

        for prim in self._stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                self._assert_fixed_topology(prim, layer)

            # Every time-sampled attribute belongs in the xform layer, not just
            # the point-based ones: animated visibility or primvars left behind
            # would break the static layer's contract just as surely.
            # Topology is the exception — validated constant above, so it is
            # collapsed to a default in the geo layer rather than moved.
            names = [
                attr.GetName() for attr in prim.GetAttributes()
                if attr.GetName() not in _EXCLUDED_ATTRIBUTES
                and _time_samples(layer, attr)
            ]
            if names:
                found[prim.GetPath()] = names

        self._animated = found
        return found

    def _assert_fixed_topology(self, prim: Usd.Prim, layer: Sdf.Layer) -> None:
        for name in _TOPOLOGY_ATTRIBUTES:
            attr = prim.GetAttribute(name)
            if not attr:
                continue
            samples = _time_samples(layer, attr)
            if not samples:
                continue
            values = [attr.Get(t) for t in samples]
            if any(v != values[0] for v in values[1:]):
                raise VaryingTopologyError(
                    "point cache requires fixed topology; {} changes over time".format(
                        attr.GetPath()))

    # -- output ------------------------------------------------------------

    def split(self, geo_path: str, xform_path: str) -> Tuple[Sdf.Layer, Sdf.Layer]:
        """Write both layers and return them as ``(geo_layer, xform_layer)``."""
        return self.write_geo(geo_path), self.write_xform(xform_path)

    def write_geo(self, path: str) -> Sdf.Layer:
        """Write the static layer: the source with every time sample stripped."""
        layer = Sdf.Layer.CreateNew(path)
        self._copy_stage_metadata(layer)
        Sdf.CopySpec(self._source_layer(), Sdf.Path("/"), layer, Sdf.Path("/"))
        # Flatten() stamps a "Generated from Composed Stage" doc string; it is
        # provenance of the split, not of the published geometry.
        layer.pseudoRoot.ClearInfo("documentation")

        # Sweep the whole layer rather than only the prims discovery returned:
        # a mesh carrying nothing but constant topology samples never appears in
        # animated_attributes(), yet its samples would still reach the geo layer.
        self.animated_attributes()          # runs the fixed-topology check
        self._freeze_time_samples(layer)
        for prim_path in self._mesh_paths():
            self._restate_extent(layer, prim_path)

        layer.Save()
        return layer

    def write_xform(self, path: str) -> Sdf.Layer:
        """Write the time-sampled layer, including a per-frame ``extent``."""
        layer = Sdf.Layer.CreateNew(path)
        self._copy_stage_metadata(layer)

        for prim_path, names in self.animated_attributes().items():
            source = self._stage.GetPrimAtPath(prim_path)
            spec = self._define(layer, prim_path)

            for name in names:
                # CopySpec rather than a bare AttributeSpec: it carries the
                # source's metadata (interpolation, elementSize…) along with the
                # samples. Without interpolation a faceVarying normals array is
                # silently reinterpreted as vertex.
                attr_path = prim_path.AppendProperty(name)
                Sdf.CopySpec(self._source_layer(), attr_path, layer, attr_path)
                out = layer.GetAttributeAtPath(attr_path)
                out.ClearDefaultValue()

            self._copy_xform_op_order(layer, spec, source, names)
            self._write_animated_extent(layer, spec, source, names)

        layer.Save()
        return layer

    # -- internals ---------------------------------------------------------

    def _source_layer(self) -> Sdf.Layer:
        """The composed stage flattened into one layer, cached.

        ``Sdf.CopySpec`` is not composition-aware, so geometry arriving through a
        reference or payload has no spec in the root layer.
        """
        if self._flat is None:
            self._flat = self._stage.Flatten()
        return self._flat

    def _copy_stage_metadata(self, layer: Sdf.Layer) -> None:
        source = self._stage.GetRootLayer().pseudoRoot
        for key in _STAGE_METADATA:
            if source.HasInfo(key):
                layer.pseudoRoot.SetInfo(key, source.GetInfo(key))
        if self._stage.GetRootLayer().defaultPrim:
            layer.defaultPrim = self._stage.GetRootLayer().defaultPrim

    def _define(self, layer: Sdf.Layer, path: Sdf.Path) -> Sdf.PrimSpec:
        """Create ``path`` and its ancestors as typed ``def`` specs.

        Typed, not blank: an untyped ancestor makes several USD queries skip
        everything beneath it, and a pure ``over`` layer is invisible to the
        default stage traversal.
        """
        for current in reversed(list(path.GetAncestorsRange())):
            if current.IsAbsoluteRootPath():
                continue
            spec = layer.GetPrimAtPath(current) or Sdf.CreatePrimInLayer(layer, current)
            spec.specifier = Sdf.SpecifierDef
            source = self._stage.GetPrimAtPath(current)
            if source and source.GetTypeName():
                spec.typeName = source.GetTypeName()
        return layer.GetPrimAtPath(path)

    def _mesh_paths(self) -> List[Sdf.Path]:
        return [p.GetPath() for p in self._stage.Traverse() if p.IsA(UsdGeom.Mesh)]

    def _freeze_time_samples(self, layer: Sdf.Layer) -> None:
        """Fold every attribute's earliest sample into a default, layer-wide.

        The static layer's contract is that it holds no time samples at all, so
        this is driven by what the layer actually contains rather than by what
        discovery reported. Keeping the earliest sample as the value leaves the
        geo layer a complete, openable piece of geometry.
        """
        def visit(path):
            if not path.IsPropertyPath():
                return
            spec = layer.GetAttributeAtPath(path)
            if spec is None or not spec.HasInfo("timeSamples"):
                return
            samples = spec.GetInfo("timeSamples")
            if samples:
                spec.default = samples[min(samples)]
            spec.ClearInfo("timeSamples")

        layer.Traverse(Sdf.Path("/"), visit)

    def _copy_xform_op_order(self, layer: Sdf.Layer, spec: Sdf.PrimSpec,
                             source: Usd.Prim, names: Sequence[str]) -> None:
        """Carry ``xformOpOrder`` across whenever an ``xformOp`` is animated.

        It is uniform, so it never appears among the time-sampled attributes —
        but without it USD evaluates no transform ops at all. A propAnim unit
        composed straight over a published Asset has no other source for it, and
        the animation silently resolves to identity.
        """
        if not any(n.startswith("xformOp:") for n in names):
            return
        attr = source.GetAttribute("xformOpOrder")
        if not attr or attr.Get() is None:
            return
        out = Sdf.AttributeSpec(spec, "xformOpOrder", attr.GetTypeName(),
                                Sdf.VariabilityUniform)
        out.default = attr.Get()

    def _restate_extent(self, layer: Sdf.Layer, prim_path: Sdf.Path) -> None:
        """Give the static layer an extent matching its bind-pose points."""
        spec = layer.GetPrimAtPath(prim_path)
        points_spec = spec.properties.get("points")
        if points_spec is None or points_spec.default is None:
            return
        extent = _extent_of(points_spec.default)
        if extent is None:
            return
        extent_spec = spec.properties.get("extent")
        if extent_spec is None:
            extent_spec = Sdf.AttributeSpec(spec, "extent", Sdf.ValueTypeNames.Float3Array)
        extent_spec.ClearInfo("timeSamples")
        extent_spec.default = extent

    def _write_animated_extent(self, layer: Sdf.Layer, spec: Sdf.PrimSpec,
                               source: Usd.Prim, names: Sequence[str]) -> None:
        """Author ``extent`` per frame — USD never derives it from ``points``.

        Without this the bound stays frozen at whatever was authored statically,
        so frustum culling and ``drawMode = "bounds"`` both use the wrong box.
        """
        if "points" not in names:
            return
        points = source.GetAttribute("points")
        extent_spec = Sdf.AttributeSpec(spec, "extent", Sdf.ValueTypeNames.Float3Array)
        for t in _time_samples(self._source_layer(), points):
            extent = _extent_of(points.Get(t))
            if extent is not None:
                layer.SetTimeSample(extent_spec.path, t, extent)

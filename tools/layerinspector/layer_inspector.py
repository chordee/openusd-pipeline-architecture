"""USD layer inspector.

Surveys every ``Sdf.Layer`` a ``Usd.Stage`` uses and reports each layer's
Houdini save settings (``HoudiniSavePath`` / ``HoudiniSaveControl`` /
``HoudiniEditorNodes`` custom layer data), so it's easy to see which layers
will actually be written to disk and by which LOP nodes.

Entry point is :class:`LayerInspector`. Houdini is only required to resolve
``HoudiniEditorNodes`` session ids back to node paths (``resolve_nodes=True``,
the default) — with ``resolve_nodes=False`` this module needs only ``pxr``.
"""

import json
from pathlib import Path
from typing import Optional, Union

from pxr import Sdf, Usd

try:
    import hou
except ImportError:
    hou = None


def _jsonify(value):
    """Recursively convert Sdf/Vt values to plain JSON-safe Python types."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Sdf.AssetPath):
        return {"assetPath": value.path, "resolvedPath": value.resolvedPath}
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    try:
        return [_jsonify(v) for v in value]
    except TypeError:
        return str(value)


class LayerInspector:
    """Survey every layer a ``Usd.Stage`` uses, along with its Houdini save settings."""

    SAVE_PATH_KEY = "HoudiniSavePath"
    SAVE_CONTROL_KEY = "HoudiniSaveControl"
    EDITOR_NODES_KEY = "HoudiniEditorNodes"
    CREATOR_NODE_KEY = "HoudiniCreatorNode"
    SOP_LAYER_KEY = "HoudiniTreatAsSopLayer"
    META_PRIM = "/HoudiniLayerInfo"
    # Save-control tokens Houdini authors on /HoudiniLayerInfo, per its own
    # Scene Graph Layers panel (``scenegraphlayers/model.py``): ``Explicit``
    # writes to HoudiniSavePath and ``IsFileFromDisk`` overwrites the file the
    # layer was loaded from, while ``Placeholder`` and ``DoNotSave`` write
    # nothing. An absent token means "Implicit" — the layer is folded into its
    # parent's file rather than written on its own.
    WRITING_CONTROLS = frozenset({"Explicit", "IsFileFromDisk"})

    def __init__(
        self,
        stage: Usd.Stage,
        include_refs: bool = True,
        include_session_layers: bool = True,
        resolve_nodes: bool = True,
    ) -> None:
        self.stage = stage
        self.include_refs = include_refs
        self.include_session_layers = include_session_layers
        self.resolve_nodes = resolve_nodes

    # ---------- collect ----------

    def layers(self) -> list:
        """Layers the stage currently consumes, not every layer it could reach.

        With ``include_refs`` the local stack is extended by
        ``GetUsedLayers()``, which reports what composition actually traversed.
        A payload that is declared but not loaded (a stage opened with
        ``Usd.Stage.LoadNone``, or an unloaded prim) therefore does not appear —
        it contributes no opinions and Houdini writes nothing for it. Value
        clips do appear without sampling an attribute first, confirmed against
        Houdini's USD build.
        """
        stack = list(
            self.stage.GetLayerStack(
                includeSessionLayers=self.include_session_layers
            )
        )
        if not self.include_refs:
            return stack
        known = {layer.identifier for layer in stack}
        if not self.include_session_layers:
            # GetUsedLayers() always reports the session layer stack, so the
            # layers GetLayerStack() just omitted have to be excluded again.
            known.update(
                layer.identifier
                for layer in self.stage.GetLayerStack(includeSessionLayers=True)
            )
        extra = [
            layer
            for layer in self.stage.GetUsedLayers(includeClipLayers=True)
            if layer.identifier not in known
        ]
        return stack + extra

    def _houdini_meta(self, layer: Sdf.Layer) -> dict:
        meta = dict(layer.customLayerData or {})
        spec = layer.GetPrimAtPath(self.META_PRIM)
        if spec is not None:
            meta.update(dict(spec.customData or {}))
        return meta

    def _node_paths(self, ids) -> tuple:
        if not self.resolve_nodes or not ids or hou is None:
            return [], []
        found: list = []
        stale: list = []
        for sid in ids:
            n = hou.nodeBySessionId(int(sid))
            if n:
                found.append(n.path())
            else:
                stale.append(int(sid))
        return found, stale

    def _node_path(self, node_id) -> Optional[str]:
        if node_id is None:
            return None
        found, _ = self._node_paths([node_id])
        return found[0] if found else None

    def unresolved_sublayers(self) -> list:
        """Sublayer paths that a layer declares but can't actually be resolved (usually a missing file).

        Scans the same layers :meth:`layers` reports, so a layer pulled in by a
        reference, payload, or clip is checked too — not just the local stack.
        """
        missing: list = []
        for parent in self.layers():
            for sublayer_path in parent.subLayerPaths:
                if Sdf.Layer.FindRelativeToLayer(parent, sublayer_path) is None:
                    missing.append(
                        {"parent": parent.identifier, "subLayerPath": sublayer_path}
                    )
        return missing

    @staticmethod
    def _is_valid_explicit_path(path: Optional[Union[str, Sdf.AssetPath]]) -> bool:
        """檢查 Explicit Save Path 是否符合子目錄收斂規範（必須在 ./layers/ 或 ./sublayers/ 下）。"""
        if not path:
            return False
        raw = path.path if hasattr(path, "path") else str(path)
        norm = raw.replace("\\", "/")
        # 允許 ./layers/ 或 layers/ 或 ./sublayers/ 或 sublayers/ 開頭，不允許向上溢出 ../ 或根路徑 /
        return (
            norm.startswith("./layers/")
            or norm.startswith("layers/")
            or norm.startswith("./sublayers/")
            or norm.startswith("sublayers/")
        )

    # ---------- describe ----------

    def describe(self, layer: Sdf.Layer, index: int = -1) -> dict:
        meta = self._houdini_meta(layer)
        save_path = meta.get(self.SAVE_PATH_KEY)
        save_control = meta.get(self.SAVE_CONTROL_KEY)
        editor_nodes, stale_ids = self._node_paths(meta.get(self.EDITOR_NODES_KEY))
        creator_node = self._node_path(meta.get(self.CREATOR_NODE_KEY))

        # 判定是否會寫盤：Explicit 需有 save_path；IsFileFromDisk 需有 realPath (或 save_path)
        will_write = (
            (save_control == "Explicit" and bool(save_path))
            or (save_control == "IsFileFromDisk" and bool(layer.realPath or save_path))
        )

        # 判定路徑合規性：若為 Explicit 寫盤圖層，驗證其 save_path 是否位於子目錄內
        path_valid = True
        if save_control == "Explicit" and bool(save_path):
            path_valid = self._is_valid_explicit_path(save_path)

        return {
            "index": index,
            "identifier": layer.identifier,
            "displayName": layer.GetDisplayName(),
            "creatorNode": creator_node,
            "isSopLayer": bool(meta.get(self.SOP_LAYER_KEY)),
            "implicit": save_control is None,
            "realPath": layer.realPath or "",
            "savePath": save_path,
            "saveControl": save_control,
            "willWriteFile": will_write,
            "isPathValid": path_valid,
            "isRootLayer": layer == self.stage.GetRootLayer(),
            "isSessionLayer": layer == self.stage.GetSessionLayer(),
            "dirty": layer.dirty,
            "muted": self.stage.IsLayerMuted(layer.identifier),
            "editorNodes": editor_nodes,
            "staleEditorNodeIds": stale_ids,
            "customLayerData": _jsonify(meta),
        }

    def report(self) -> list:
        return [self.describe(layer, i) for i, layer in enumerate(self.layers())]

    def full_report(self) -> dict:
        layers = self.report()
        # 整理寫盤路徑 (savePath 優先，若為 IsFileFromDisk 且無 savePath 則使用 realPath)
        pending_writes = [
            d["savePath"] or d["realPath"]
            for d in layers
            if d["willWriteFile"]
        ]
        # 違規路徑清單 (Explicit 圖層但未收斂於子目錄)
        path_violations = [
            {"identifier": d["identifier"], "savePath": d["savePath"], "creatorNode": d["creatorNode"]}
            for d in layers
            if d["saveControl"] == "Explicit" and not d["isPathValid"]
        ]
        return {
            "layers": layers,
            "unresolvedSublayers": self.unresolved_sublayers(),
            "pathViolations": path_violations,
            "summary": {
                "total": len(layers),
                "implicit": sum(1 for d in layers if d["implicit"]),
                "explicit": sum(1 for d in layers if not d["implicit"]),
                "pendingWrites": pending_writes,
                "hasPathViolations": len(path_violations) > 0,
            },
        }

    def print_summary(self) -> None:
        """在終端或 Houdini Python Shell 列印易讀的圖層治理摘要報告。"""
        report = self.full_report()
        summary = report["summary"]
        layers = report["layers"]
        missing = report["unresolvedSublayers"]
        violations = report.get("pathViolations", [])

        print("=" * 70)
        print(" [Houdini Solaris Layer Inspector 治理檢測報告]")
        print("=" * 70)
        print(f"總圖層數: {summary['total']} | 顯式圖層: {summary['explicit']} | 隱式圖層: {summary['implicit']}")
        print(f"預計寫盤檔案數 (Pending Writes): {len(summary['pendingWrites'])}")
        for path in summary["pendingWrites"]:
            print(f"  -> {path}")

        # 檢測警示：未顯式化之 SOP / 隱式圖層
        sop_implicits = [d for d in layers if d["implicit"] and d.get("isSopLayer")]
        if sop_implicits:
            print("\n[!] 警告：發現未顯式化之 SOP 隱式圖層（可能導致非預期碎檔）：")
            for d in sop_implicits:
                creator = d.get("creatorNode") or "未知節點"
                print(f"  - 建立節點: {creator} (DisplayName: {d['displayName']})")
                print("    建議：請於該節點後方連接 Configure Layer 節點指定 Save Path (例如 ./layers/<geo>.usd)。")

        # 檢測警示：未依規範收斂於子目錄的 Explicit 路徑違規
        if violations:
            print("\n[!] 警告：發現未合規收斂於子目錄 (./layers/) 的 Explicit 圖層路徑：")
            for v in violations:
                creator = v.get("creatorNode") or "未知節點"
                print(f"  - 違規路徑: {v['savePath']} (節點: {creator})")
                print("    建議：請修改 Configure Layer 的 Save Path，將檔案收斂至 ./layers/ 子目錄內。")

        # 檢測壞鏈
        if missing:
            print("\n[!] 錯誤：發現無法解析的 Sublayer 壞鏈：")
            for m in missing:
                print(f"  - 父圖層: {m['parent']}")
                print(f"    缺失路徑: {m['subLayerPath']}")

        print("=" * 70)

    def to_json(self, indent: Optional[int] = 2) -> str:
        # 對完整的 full_report 套用 _jsonify，確保 Sdf.AssetPath 等型別均能安全轉為 JSON
        safe_data = _jsonify(self.full_report())
        return json.dumps(safe_data, indent=indent, ensure_ascii=False)


def layers_to_json(stage: Usd.Stage, indent: Optional[int] = 2, **kwargs) -> str:
    return LayerInspector(stage, **kwargs).to_json(indent=indent)

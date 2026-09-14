# Houdini Solaris USD Layer Inspector

本目錄存放用於 Houdini Solaris（LOP）場景輸出前置檢查（Pre-flight Check）的 USD 圖層盤點工具。

---

## 核心設計理念與架構角色

在 OpenUSD 生產 Pipeline 中，Houdini Solaris 網路節點（如 `SOP Create`、`SOP Modify`、`Merge`）在背後記憶體中即時生成虛擬的 **Implicit Layers（隱式圖層）**。

若發布前未經治理（參見架構手冊：[USD Solaris Implicit Layer 治理與輸出指南](../../docs/usd-solaris-implicit-layer.md)）：
- 輸出階段 Houdini 在拓撲分析時若無法打平，會自動具現化並隨機噴出數十個匿名 `.usd` 實體檔案。
- 這些碎檔往往散落在非預期的暫存或使用者目錄中，形成嚴重的髒檔外溢污染。

`layer_inspector.py` 是 Pipeline 的**第二防線（流程前置工具：Scene Checker / Layer Inspector）**：
1. **全面盤點 Stage 圖層**：遍歷記憶體中 LOP Stage 的 Layer Stack 與實際 Composition 消費到的圖層。
2. **識別 Implicit 與 Explicit 圖層**：精準偵測哪些圖層是未指派存檔路徑的隱式圖層，哪些是即將落盤的顯式圖層。
3. **反向追查肇因節點**：透過 `HoudiniCreatorNode` 與 `HoudiniEditorNodes`（`hou.nodeBySessionId`），精確還原是哪顆 LOP 節點建立了該隱式圖層，指引藝術家於該節點後方連接 `Configure Layer` 節點。
4. **掃描 Sublayer 壞鏈**：及早揪出已宣告但磁碟檔案缺失的無效 Sublayer 路徑。

---

## API 規格與說明

### `LayerInspector` 類別

```python
from layer_inspector import LayerInspector

inspector = LayerInspector(
    stage,
    include_refs=True,
    include_session_layers=False,
    resolve_nodes=True
)
```

| 參數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `stage` | (必填) | 要盤點的 `Usd.Stage`（例如 `hou.node("/stage/usd_rop").stage()`） |
| `include_refs` | `True` | 是否納入 Composition 實際消費到的圖層（Reference / Payload / Value Clip） |
| `include_session_layers` | `True` | 是否納入 Session Layer（**建議在 Solaris 中設為 `False`**，以過濾 Viewport State、Solo Lights 等視圖雜訊） |
| `resolve_nodes` | `True` | 是否透過 `hou.nodeBySessionId` 將節點 Session ID 還原為節點路徑字串（需要 `hou` 模組） |

### 主要方法

- **`print_summary()`**：在 Houdini Python Shell 或終端列印清楚易讀的排版報告，標註未顯式化的 SOP 圖層警告與壞鏈。
- **`full_report()`**：回傳完整的字典報告（包含 `layers`、`unresolvedSublayers` 與 `summary` 統計）。
- **`to_json(indent=2)`**：回傳格式化 JSON 字串，適合整合進 Studio 的自動化驗證 Hook 或 CI 流程。
- **`unresolved_sublayers()`**：回傳所有打不開的無效 Sublayer 清單。

---

## Houdini 存檔控制標記（`HoudiniSaveControl`）

Houdini 在內部 `/HoudiniLayerInfo` Prim 上記錄各圖層的存檔控制行為：

| Token | 是否會寫入實體檔案 (`willWriteFile`) | 行為說明 |
| :--- | :---: | :--- |
| `Explicit` | **是** | 依據 `HoudiniSavePath` 指定之路徑寫盤 |
| `IsFileFromDisk` | **是** | 覆寫來源實體 USD 檔案（Replace File） |
| `Placeholder` | **否** | 忽略（Ignore） |
| `DoNotSave` | **否** | 明確標記不存檔（Do Not Save） |
| *(未定義 / None)* | **否** | **Implicit 圖層**：輸出時嘗試打平併入父圖層，無法打平時將由 ROP 自動隨機具現化 |

---

## 使用範例

### 範例 A：在 Houdini Python Shell 中即時健檢

```python
import hou
from layer_inspector import LayerInspector

# 取得目標 LOP 節點的 stage
lop_node = hou.node("/stage/usd_rop")
stage = lop_node.stage()

# 建立檢查器 (過濾視圖用的 session layers)
inspector = LayerInspector(stage, include_session_layers=False)

# 終端快速排版輸出
inspector.print_summary()
```

輸出範例：
```text
======================================================================
 [Houdini Solaris Layer Inspector 治理檢測報告]
======================================================================
總圖層數: 4 | 顯式圖層: 2 | 隱式圖層: 2
預計寫盤檔案數 (Pending Writes): 1
  -> ./layers/hero_geo.usd

[!] 警告：發現未顯式化之 SOP 隱式圖層（可能導致非預期碎檔）：
  - 建立節點: /stage/sopcreate1 (DisplayName: LOP)
    建議：請於該節點後方連接 Configure Layer 節點指定 Save Path。
======================================================================
```

### 範例 B：整合至 USD ROP Pre-flight Hook

可在 USD ROP 輸出按鈕前或 Python Script 中進行阻擋校驗：

```python
inspector = LayerInspector(stage, include_session_layers=False)
report = inspector.full_report()

# 若存在未解析的壞鏈，嚴格阻擋發布
if report["unresolvedSublayers"]:
    raise RuntimeError(f"Stage 存在無法解析的 Sublayer 壞鏈，發布中止: {report['unresolvedSublayers']}")
```

---

## 單元測試

本模組包含純 Python 單元測試（支援無真實 Houdini/pxr 的隔離環境）：

```bash
python tools/layerinspector/tests/test_layer_inspector.py
```

# 道具動畫靜態／時序拆分工具

本目錄存放將**形變幾何 Stage** 拆分為 `geo`（靜態）與 `xform`（時序）兩個 sub 單元的工具。

---

## 核心設計理念與架構角色

`propAnim` 發布單元與 `charAnim` 走同一條軸——**靜態與時序二分**（參見架構手冊：[USD Animation Layer 動態架構設計](../../docs/usd-animation-layer.md)）：

| Sub 單元 | 承載內容 |
| :--- | :--- |
| `geo/` | 拓樸、UV 與 bind 姿態的 `points` |
| `xform/` | `points` 與其伴隨屬性的時間樣本、`xformOp` 時間樣本、逐幀 `extent` |

絕大多數剛體道具**不需要 `geo`**——幾何早已在 Asset 階段發布，單元只交付 `xform`。本工具處理的是幾何無法來自靜態 Asset 的情形：變形道具（旗幟、布幔、擠壓變形的球）。

---

## 三個會靜默出錯的環節

### 一、`extent` 不會跟隨 `points`

USD **從不**自動重算 `extent`。若將形變點位移至另一層而留下靜態 `extent`，包圍盒即凍結在寫入當下的那一幀：

```text
第 2 幀實際點位範圍 : (0,0,0) ~ (10,10,0)
已寫入的 extent     : [(0,0,0), (1,1,0)]      ← 只反映第 1 幀
BBoxCache 算出的    : [(0,0,0), (1,1,0)]      ← 沿用過期值
```

後果是 frustum culling 會在物件仍在畫面內時將其剔除，`drawMode = "bounds"` 的代理盒也是錯的尺寸——而且**完全不報錯**。工具因此在寫出 `xform` 時逐幀重算 `extent`。

### 二、固定拓樸是 Pipeline 約束，不是 Schema 保證

`faceVertexCounts` 與 `faceVertexIndices` 在 Schema 中的 variability 是 **varying**——USD 允許逐幀拓樸，不會有任何抱怨。拆分後點位與面的對應關係卻會錯亂，因此工具**主動驗證**並在拓樸隨時間改變時拋出 `VaryingTopologyError`。

拓樸確實需要逐幀改變的內容（碎裂、流體）不屬於動畫單元，應改由 [FX Element](../../docs/usd-fx-layer.md) 以 Value Clips 承載。

### 三、`xformOpOrder` 是 uniform，但少了它整組 Transform 不生效

`xformOpOrder` 不帶時間樣本，因此不會出現在「時序屬性」清單中——但 USD **沒有它就不評估任何 xformOp**。`propAnim` 的 `xform` 若直接疊在已發布的 Asset 之上（剛體道具的常見情形），Asset 並不知道動畫師加了哪些 op，合成後的 local transform 會靜默地解析為單位矩陣：

```text
缺 xformOpOrder : ( (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1) )   ← 位移完全消失
補上之後        : ( (1,0,0,0), (0,1,0,0), (0,0,1,0), (5,0,0,1) )
```

工具因此在有任何 `xformOp:*` 進入 `xform` 時，一併複製 `xformOpOrder`。

> [!NOTE]
> **靜態層不留任何時間樣本**
> 拆分的判準是「**是否帶時間樣本**」，而非屬性名單——動畫化的 `visibility` 或 primvar 同樣會破壞靜態層的契約。`geo` 因此以**全層掃描**凍結樣本，而非只處理 discovery 回報的 Prim：只帶恆定拓樸樣本的 Mesh 根本不會出現在 discovery 結果中，其樣本卻仍會抵達 `geo`。
>
> 兩項屬性從不由來源搬運：**拓樸**既已驗證恆定，折疊為 default 留在 `geo`；**`extent`** 一律由 `points` 重算——來源的 `extent` 可能本就是過期的，且複製它會與重算的規格同名衝突。
>
> 屬性以 `Sdf.CopySpec` 搬移而非重建，以保留來源的 `interpolation`、`elementSize` 等 metadata——缺少 `interpolation` 的 faceVarying `normals` 會被靜默當成 vertex 內插。

> [!NOTE]
> **伴隨屬性必須與 `points` 同行**
> `velocities`、`accelerations`、`normals` 若留在靜態層而 `points` 已移走，動態模糊會取用與實際位移不符的速度場。

---

## API 規格與說明

### `PointCacheSplitter` 類別

```python
from point_cache_splitter import PointCacheSplitter

splitter = PointCacheSplitter(stage)          # stage 須為「合成後」的 Stage
geo_layer, xform_layer = splitter.split("geo.usda", "xform.usda")
```

| 方法 | 說明 |
| :--- | :--- |
| `animated_attributes()` | 回傳 `{Prim 路徑: [時序屬性名]}`，並於過程中驗證固定拓樸（結果會快取） |
| `write_geo(path)` | 寫出靜態層：來源去除全部時間樣本，保留最早一幀作為 bind 姿態 |
| `write_xform(path)` | 寫出時序層，含逐幀重算的 `extent` |
| `split(geo_path, xform_path)` | 一次寫出兩者，回傳 `(geo_layer, xform_layer)` |

> [!IMPORTANT]
> **來源 Stage 會先 Flatten**
> `Sdf.CopySpec` 不具備 Composition 感知能力，經 Reference 或 Payload 帶入的幾何在 Root Layer 沒有對應 spec。工具內部先 `Stage.Flatten()`（結果快取）再複製，並清除 `Flatten()` 附加的 `documentation` ——那是拆分的來歷，不是發布幾何的說明。

Layer Metadata 不會透過 `subLayers` 向上傳遞，因此 `upAxis`、`metersPerUnit`、`timeCodesPerSecond` 等會逐項複製至兩個輸出層。

---

## 依賴與執行

僅需 `pxr`，不依賴任何 DCC。

```bash
hython -m unittest discover -s tools/pointcachesplitter/tests -v
```

測試共 17 項，涵蓋上述三個環節、經 Reference 帶入的幾何，以及一項**重新合成驗證**：將拆出的兩層疊回後，確認第 2 幀的 `BBoxCache` 結果確實跟隨形變——若 `extent` 未逐幀重算，此項即會失敗。

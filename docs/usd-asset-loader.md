# USD：Asset Loader 工具架構與全元素載入規範

在 USD 影視與動畫生產 Pipeline 中，**Environment、Layout、Lighting 與 FX 部門**需要頻繁載入海量發布元素來搭建與擺放場景。

傳統 DCC 工具常將「Asset 檢索」與「軟體內節點生成」緊密揉雜，甚至封裝出專有節點，導致跨 DCC 難以移植或破壞 USD 圖層結構。本架構旨在建立一套**「瀏覽檢索與載入行為分離」**、**「100% 依循 OpenUSD 原生組合弧」**、且具備**「自由命名掛載路徑」**與**「Class Inherits 標籤廣播」**的工業級 Asset Loader 規範。

---

> [!important] 30 秒架構核心原則
> 1. **Query 與 Load 兩段式分離**：
>    - **Query（檢索器）**：跨 DCC 的獨立瀏覽檢索工具，負責全專案發布庫的過濾、版本選擇與元數據預覽。
>    - **Load（載入器）**：所屬 DCC 內部的純粹執行者，透過標準 OpenUSD 組合弧將元素掛載進當前 Stage。
> 2. **全元素開放載入（Universal Element Loading）**：
>    - 載入對象不局限於 Component Asset，**凡全 Pipeline 發布過的任何合法單元元素皆可載入**——包含 Component Asset、Set Dressing Assembly、FX Element、以及 Pure USD Unit（如散佈點雲）。
> 3. **保持 OpenUSD 原生組合弧的純粹性**：
>    - 僅調用標準的 `Reference`、`Payload` 與 `Sublayer`，嚴禁引入非標準的私有自訂節點。
> 4. **靈活的目標掛載路徑（Target Prim Path）**：
>    - 允許藝術家自由指定載入進來的擺放層級與命名（除了 `Sublayer` 外），充分利用發布端 `/ROOT` 解耦優勢。
> 5. **Instanceable 原生實例化選項**：
>    - 高密度道具可勾選 `instanceable = true`，享受 USD Core 內部 Stage 結構共享。
> 6. **預設 Class Inherits 多重標籤分類機制**：
>    - 預設注入 `/__CLASS__/{專案註冊名稱}`，並允許藝術家追加或自訂 Class 標籤，達成跨物件的廣播式覆寫與分類管理。

---

## 1. 兩段式架構流程圖 (Query & Load Architecture)

```text
┌─────────────────────────────────────────────────────────────┐
│                 階段一：Query（獨立瀏覽檢索器）               │
│  - 跨 DCC 通用獨立 UI（或嵌於 DCC 面板）                    │
│  - 全專案發布目錄檢索（Asset, SetDressing, FX, Pure USD）    │
│  - 動態版本篩選（預設 latest.usd，支援歷史 v### 鎖定）        │
│  - 屬性預覽（Thumbnail, Variants 清單, Metadata）           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                      傳遞發布路徑與組態
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 階段二：Load（DCC 內載入行為）                │
│  1. 選擇組合弧類型：                                         │
│     ├── Payload (預設重型幾何/場景)                           │
│     ├── Reference (輕型道具/幾何)                            │
│     └── Sublayer (圖層級整體堆疊，不支援自訂路徑)               │
│  2. 指定擺放目標路徑（Target Prim Path，如 /ROOT/Props/Chair）│
│  3. 實例化開關：[✔] Instanceable (原生記憶體共享)             │
│  4. 繼承標籤（Class Inherits）：                             │
│     ├── 預設繼承：/__CLASS__/chair                           │
│     └── 追加標籤：/__CLASS__/indoor_props                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 階段一：Query（獨立瀏覽檢索器）

### 職責邊界
檢索器專注於「找到對的元素與對的版本」，與具體 DCC 解耦：
1. **全元素開放檢索**：
   - **Component Asset**（如 `assets/props/chair/`）
   - **Set Dressing Assembly**（如 `sets/livingroom/`）
   - **FX Element**（如 `fx/elements/explosion_hero/`）
   - **Pure USD Unit**（如 `shots/sq01/sh010/layout/scatter_forest/`）
2. **版本決策（Latest vs Version Pinning）**：
   - **預設選項**：`asset_latest.usd` / `element_latest.usd`（日常製作推薦，享受自動更新）。
   - **特定歷史版次**：下拉選單列出所有已凍結的歷史目錄（`v001`、`v002`...），供特定需求精確鎖定。
3. **Variant 探索**：
   - 預先解析該 USD 主檔案的 `variantSets`（如 `model` LOD、`look` 材質），讓藝術家在載入前或載入時一併設定初始變體。

---

## 3. 階段二：Load（DCC 內純粹 USD 組合行為）

### 1. 組合弧選擇（Composition Arcs）
載入器嚴格遵循 OpenUSD 標準，提供三種對應的掛載弧：

| 組合弧類型 | 適用情境 | Prim 路徑可自訂性 | 特性說明 |
| :--- | :--- | :--- | :--- |
| **`Payload` (推薦首選)** | 重型幾何、大型建築、複雜 Set Dressing、體積快取 | **自由自訂** | 支援延遲加載（Unloaded 狀態開啟），巨型場景開啟速度極快。 |
| **`Reference`** | 輕量道具、輔助標記、局部幾何組件 | **自由自訂** | 開啟場景即完整加載，不可單獨 Unload。 |
| **`Sublayer`** | 鏡頭分層堆疊、跨部門整層整合 | **不可自訂**<br>*(圖層級全場覆蓋)* | 參與 Stage 根層級 LIVRPS 意見仲裁，直接疊加整個圖層。 |

### 2. 自由指定目標擺放路徑（Target Prim Path）
在傳統軟體中，匯入檔案常強行依檔名產生節點（例如匯入 `chair.usd` 強制在 `/chair`）。但在本架構中：
- 所有被發布的元素，其內部根節點**一律同構解耦為 `/ROOT`**。
- **Loader 允許藝術家自由指定擺放路徑**：
  - 預設建議路徑：`/ROOT/Environment/Props/{asset_name}_01`
  - 藝術家自訂重構：`/ROOT/SetDressing/LivingRoom/Furniture/HeroArmChair`

```usda
# 藝術家將 chair 載入並重命名為 HeroArmChair，語意高度貼合場景
def Xform "HeroArmChair" (
    payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
)
{
    double3 xformOp:translate = (120, 0, 45)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}
```

---

## 4. Instanceable 原生實例化支援

對於需要大量複製的物件（如餐廳內的 80 把椅子、街道旁的 200 盞路燈），Loader 介面提供 **`[✔] Instanceable`** 勾選功能：

```usda
# 透過 Loader 載入之多個實例
def Xform "Chair_01" (
    instanceable = true
    payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
)
{
    double3 xformOp:translate = (0, 0, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}

def Xform "Chair_02" (
    instanceable = true
    payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
)
{
    double3 xformOp:translate = (150, 0, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}
```

### 核心架構效益
1. **Stage 記憶體共享**：所有 `instanceable = true` 且組合弧相同的 Prim，在 USD Core 內部僅保留一份 Prototype 記憶體結構，顯著釋放記憶體。
2. **與 PointInstancer 的定位互補**：
   - `PointInstancer`：適合數萬至數百萬個純粒子點雲驅動的自然散佈（樹林、落葉），無法各別微調 Transform。
   - `Instanceable Xform`：適合幾十到幾百個由藝術家手工擺放、需各別精準旋轉微調或獨立切換 Variant 的場景道具。

---

## 5. 預設 `inherit` 多重標籤分類機制（Class Inherits）

在複雜鏡頭中，下游部門（特別是 Lighting 與 Lookdev）常需對全場特定類別的 Asset 或元素進行**「批量屬性覆寫」**或**「全域分組控制」**。Loader 導入了標準的 **`inherit`** 標籤規範：

### 1. 預設規範：`/__CLASS__/{專案註冊名稱}`
當透過 Loader 載入名為 `chair` 的 Asset 時，Loader 預設自動在 Prim 上注入該 Asset 的 Class 繼承：

```usda
# Loader 產出的實體 Prim
def Xform "OfficeChair_01" (
    # 預設自動注入：/__CLASS__/chair
    inherits = </__CLASS__/chair>
    payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
) {}
```

### 2. 允許使用者追加與自訂（多重標籤分類）
Loader 介面提供「Inherit Classes / Tags」輸入欄，藝術家可追加更多業務標籤：

```usda
def Xform "OfficeChair_01" (
    # 藝術家追加多重標籤繼承
    inherits = [
        </__CLASS__/chair>,
        </__CLASS__/wooden_props>,
        </__CLASS__/interior_dressing>
    ]
    payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
) {}
```

### 3. Class Inherits 的廣播式覆寫能力（Broadcasting Overrides）
這套機制賦予了全 Pipeline 極為強大的批量治理能力：

```usda
# 在 lighting.usd 或 lookdev_override.usd 中定義 Class 屬性
class "_class_wooden_props"
{
    # 一次宣告，全場所有繼承 wooden_props 的桌椅同步獲得此材質綁定或渲染標記
    rel material:binding = </ROOT/Materials/M_GlobalWoodVarnish>
    bool primvars:karma:light:shadow = true
}
```

* **零侵入性**：燈光師不需要在場景中遍歷 100 把椅子逐一寫入 override，只需針對頂層 Class 定義一次，所有實例即刻生效。
* **高內聚分類**：Class 在 USD 中不佔用空間實體，也不干擾階層的 Transform 幾何運算，是純粹的語意標籤。

---

## 6. DCC 實作對照指引（以 Houdini Solaris 為例）

在 Solaris 中實作符合本架構的 Loader HDA 或 Python Script：

1. **節點底層核心**：
   - 推薦底層封裝 **`Reference LOP`** 或 **`Sublayer LOP`**。
   - `Reference LOP` 設定模式：`Reference Type = Payload`（預設），`Prim Path = <自訂路徑>`。
2. **參數面板設計**：
   - **Asset Picker（Query 按鈕）**：點擊開啟獨立 Qt 瀏覽器，回傳選定檔案路徑。
   - **Destination Path**：字串輸入框，預設自動代入 `/ROOT/Environment/Props/{asset_name}_01`。
   - **Composition Arc**：下拉選單（`Payload`、`Reference`、`Sublayer`）。
   - **Instanceable**：勾選按鈕（Toggle）。
   - **Inherit Classes**：字串陣列，預設包含 `/__CLASS__/{asset_name}`，可由使用者自由 `+` 追加。
3. **Python 回呼腳本範例**：
   ```python
   # Solaris Python Script / LOP Callback
   stage = hou.node(".").stage()
   prim_path = "/ROOT/Environment/Props/chair_01"
   asset_usd_path = "${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd"
   
   # 1. 建立 Prim 並指派 kind
   prim = stage.DefinePrim(prim_path, "Xform")
   Usd.ModelAPI(prim).SetKind(Kind.Tokens.component)
   
   # 2. 注入 Payload
   prim.GetPayloads().AddPayload(asset_usd_path, Sdf.Path("/ROOT"))
   
   # 3. 設置 Instanceable
   prim.SetInstanceable(True)
   
   # 4. 注入 Class Inherits
   inherits = prim.GetInherits()
   inherits.AddInherit(Sdf.Path("/__CLASS__/chair"))
   inherits.AddInherit(Sdf.Path("/__CLASS__/wooden_props"))
   ```

---

## 7. Pipeline 規範對照總表

| 模組維度 | 規範標準 | 技術細節與效益 |
| :--- | :--- | :--- |
| **架構架構** | Query（檢索器）與 Load（載入器）兩段分離 | 檢索瀏覽與 DCC 執行解耦，工具跨軟體高復用 |
| **載入範圍** | 全發布元素皆可載入 | 涵蓋 Asset、SetDressing Assembly、FX Element、Pure USD Unit |
| **USD 合成弧** | 嚴格維持原生 Composition Arcs | 僅使用 `Payload`、`Reference`、`Sublayer`，絕不搞專有節點 |
| **擺放路徑** | 自由自訂 Target Prim Path | 擺脫檔名強綁定，完美發揮發布端 `/ROOT` 解耦彈性 |
| **實例化** | 支援 `instanceable = true` | 達成 USD Core 內部 Stage 原生記憶體共享 |
| **繼承標籤** | 預設 `/__CLASS__/{name}`，允許自訂追加 | 達成廣播式屬性覆寫與多重語意標籤管理 |

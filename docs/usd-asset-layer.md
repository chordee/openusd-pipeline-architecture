# USD：Asset Layer 架構與 VariantSet 設計

在整體 USD Pipeline 架構中，**Asset Layer（Asset 圖層）** 是構建所有場景（Environment、Animation、FX）的最基礎單元。

Asset 架構的核心目標是「**模型與外觀解耦、統一命名空間、透過 VariantSet 提供多樣性切換**」。

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一 `/ROOT` 命名空間**：Asset 檔案內部所有模型與材質一律掛載在 `/ROOT` 底下（`defaultPrim = "ROOT"`，`kind = "component"`）。
> 2. **Asset 雙核心圖層組裝**：一個完整的 `asset.usd` 本身即是由 `model.usd`（幾何）與 `look.usd`（材質）兩者 Sublayer 組成。
> 3. **預設節點路徑**：
>    - 預設模型幾何：`/ROOT/ModelDefault`
>    - 預設材質外觀：`/ROOT/LookDefault`
> 4. **雙維度 VariantSet 切換**：
>    - **Model 變體**：如 `ModelDefault`、`ModelLow`、`ModelHigh`，透過 `model` variant set 切換幾何複雜度。
>    - **Look 變體**：如 `LookDefault`、`LookRed`、`LookBlue`，透過 `look` variant set 切換材質與著色效果。
> 5. **版本控管的架構取捨**：經事先考量與權衡，VariantSet 專用於形態與外觀變體，版本迭代則統一採用目錄進版與 `latest` 機制，避免回溯修改上層註冊檔。詳見專題筆記：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)。
> 6. **Purpose 對稱完整性與 ModelAPI DrawMode 治理**：
>    - **Purpose 齊全原則**：幾何若定義了 `purpose`，**`render` 與 `proxy` 必須兩者皆齊全**；若無對應代理網格則一律保持為 `default`，防止 Viewport 與渲染農場顯示不同步。
>    - **減輕 Viewport 壓力之首選為 DrawMode**：`purpose` 是全域性切換，而 **USD ModelAPI 的 `drawMode`** 可針對個別 Component / Assembly 獨立指定顯示模式（如 `bounds`、`cards`、`default`），提供更細緻的效能控制。
>    - **嚴格維護 `kind` 階層**：Pipeline 工具鏈必須在任何時候全力維護 Prim 的 `kind` 規則（`component`, `group`, `assembly`），確保基於 ModelAPI 的階層選取與 DrawMode 機制可正常啟動。

---

## 1. 同構目錄與 Asset 圖層結構樹（Isomorphic Asset Structure）

無論任何 Asset（如 `chair`、`table`、`car`），資料夾內部結構與核心檔案名稱完全同構固定。

最核心的架構原則是：**`modelDefault/`、`lookDefault/`、`textureDefault/` 是屬於單元物件 Asset 底下的 sub 物件，自身絕不設獨立的 `latest` 指標；其底下每次進版，均直接推進單元物件 Asset 進版，並由 Pipeline 在 Asset 根目錄自動維護唯一的 `asset_latest.usd`**。

```text
/projects/show_A/publish/assets/props/chair/               <-- 【Asset 目錄，只有此層名稱不同】
├── asset_latest.usd                                     <-- 全域唯一最新動態入口 (指向最新版 v002/asset.usd)
├── v001/                                                <-- Asset 總版次目錄
│   └── asset.usd                                        <-- 固定名稱！Sublayer 鎖定子物件特定版次
├── v002/
│   └── asset.usd                                        <-- 固定名稱！
│
├── modelDefault/                                        <-- 固定的幾何 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── modelDefault.usd                             <-- 幾何版本檔案
│   └── v002/
│       └── modelDefault.usd
│
├── lookDefault/                                         <-- 固定的材質 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── lookDefault.usd                              <-- 材質版本檔案
│   └── v002/
│       └── lookDefault.usd
│
└── textureDefault/                                      <-- 固定的貼圖 sub 物件目錄 (無 latest！)
    ├── v001/
    └── v002/

       ▼ 組裝與展開後在 Stage 的結構 ▼

/ROOT (Xform, kind = component)
├── ModelDefault/    <-- (或切換為 ModelLow / ModelHigh)
│   └── Mesh/
└── LookDefault/     <-- (或切換為 LookRed / LookBlue)
    ├── Materials/
    └── material:binding
```

---

## 2. 核心設計哲學：為什麼使用 `/ROOT` 而非 Asset 名稱？

在傳統 Asset 製作中，直覺常會將根節點命名為該 Asset 的名稱（如 `/Chair` 或 `/SedanCar`）。但在工業級 USD Pipeline 中，**Asset 內部一律以 `/ROOT` 為根節點**，關鍵原因如下：

### 1. 同一 Asset 在不同專案與情境下名稱各異（Cross-Project & Contextual Renaming）
* **跨專案共用**：同一個三維模型 Asset，在專案 A 可能被註冊為 `KitchenChair`，在專案 B 叫做 `OfficeChair`，在科幻專案被改稱為 `ControlRoomSeat`。
* **同場景多實例**：同一張椅子，在鏡頭環境中會同時扮演主角座駕（`HeroChair`）、背景道具（`BGChair_01`）或被擊碎的道具（`BrokenChair`）。
* **解耦性**：如果 Asset 內部把 Prim 硬編碼為 `/Chair`，Asset 就與特定的名稱產生了強耦合。使用抽象通用的 `/ROOT`，能讓 Asset 保持完全的中立性，適應任何專案與情境。

### 2. 消費端決定語意命名，避免命名空間污染
當鏡頭或場景（Consumer）引用該 Asset 時，由消費端全權決定該實例在場景樹中的語意路徑：
```usda
# 消費端場景完全自由命名，無縫接軌來源的 /ROOT
def Xform "OfficeChair_A" (
    references = @assets/props/chair/chair.usd@</ROOT>
) {}

def Xform "HeroSeat" (
    references = @assets/props/chair/chair.usd@</ROOT>
) {}
```
USD 的 Reference / Payload 機制會自動將來源檔的 `/ROOT` 映射為消費端指定的 Prim 名稱（如 `OfficeChair_A`），Asset 內部無需知道外部叫什麼，外部也無需妥協 Asset 內部的名稱。

### 3. 工具鏈與自動化腳本高度標準化（Predictable Tooling）
* 當全工作室所有 Asset 的根節點都是 `/ROOT`（且 `defaultPrim = "ROOT"`）時，所有自動化工具（如 LOD 自動產生器、材質發佈驗證工具、QC 檢查器、Bake 腳本）都可以直接鎖定 `/ROOT`。
* 腳本不需要動態解析「這個 Asset 叫什麼名字、根 Prim 叫什麼」，極大化簡化了 Pipeline 代碼的維護成本。

---

## 3. 幾何圖層 (`model.usd`) 與 Model VariantSet

模型部門獨立發佈幾何資料。當單一 Asset 需要提供不同精度（LOD）或外觀形態時，透過 `model` VariantSet 進行封裝：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT" (
    variants = {
        string model = "Default"
    }
    prepend variantSets = "model"
)
{
    variantSet "model" = {
        # 1. 預設模型 (ModelDefault)
        "Default" {
            def Scope "ModelDefault"
            {
                def Mesh "Body" { /* 標準中精度網格資料 */ }
            }
        }
        
        # 2. 低模 (ModelLow - 用於遠景或 Crowd 大量實例)
        "Low" {
            def Scope "ModelLow"
            {
                def Mesh "Body" { /* 精簡面數網格 */ }
            }
        }
        
        # 3. 高模 (ModelHigh - 用於近景特寫或置換烘焙)
        "High" {
            def Scope "ModelHigh"
            {
                def Mesh "Body" { /* 高解析度細分曲面網格 */ }
            }
        }
    }
}
```

* **實務優勢**：在 Shot 鏡頭組裝時，Layout 或 Crowd 部門可直接將 Asset 設為 `model = "Low"` 大幅提升 Viewport 效能，特寫鏡頭則切換為 `model = "High"`。

### Purpose 規範（Render 與 Proxy 對稱原則）

USD 提供了 `purpose` 屬性（`default`, `render`, `proxy`, `guide`）供 Viewport 與渲染器過濾幾何：

```usda
def Mesh "Body_Render" (
    purpose = "render"
) { /* 數百萬面高精模型，供離線渲染器使用 */ }

def Mesh "Body_Proxy" (
    purpose = "proxy"
) { /* 幾千面簡化網格，供 Viewport 即時預覽 */ }
```

> [!IMPORTANT]
> **Purpose 規範：兩者齊全否則 Default**
> 1. **必須對稱齊全**：若在 Asset 內部為幾何宣告了 `purpose`，**`render` 與 `proxy` 兩者必須同時具備**。
> 2. **嚴禁單邊缺失**：如果只建立了 `render` 而未提供 `proxy`，當 Viewport 切換至 Proxy 模式時該物件將完全隱形；反之若只有 `proxy`，渲染農場將算不到該幾何。
> 3. **無 Proxy 則一律 Default**：若該 Asset 製作上並未刻意拆分代理網格，幾何的 `purpose` **必須保持為 `default`（或不宣告）**，讓 Viewport 與渲染器皆能正確顯示，杜絕顯示不同步。

### Viewport 壓力釋放首選：USD ModelAPI DrawMode

雖然 `purpose` 提供了代理切換機制，但 **`purpose` 是全域性（Global）的**——在 Houdini Solaris 或 USDView 中切換為 Proxy，整個 Stage 的所有物件都會同時切換，無法精細化控制單一焦點或背景 Asset。

**減輕 Viewport 壓力的最主要且強大的工業級手段，是利用 USD `UsdGeomModelAPI` 的 `drawMode`**：

```usda
# 於鏡頭或組裝層中，針對特定 Component 或 Assembly 指定 drawMode
over "BG_Car_01" (
    prepend apiSchemas = ["GeomModelAPI"]
)
{
    uniform token model:drawMode = "cards"  # 可選: "origin", "bounds", "cards", "default"
    uniform token model:cardGeometry = "cross" # 卡片型態 (cross, box, fromTexture)
}
```

* **個別 Component 獨立處理**：
  - 前景主要角色保持完整的 `default` 幾何顯示。
  - 中景群眾道具切換為 `cards`（由貼圖或幾何投影構成的廣告牌卡片）。
  - 遠景大型建築或數千棵樹木切換為 `bounds`（純邊界盒 Bounding Box）或 `origin`（座標軸）。
* **極致輕量與零記憶體載入**：
  - 當設定為 `bounds` 或 `cards` 時，Hydra Viewport 甚至無需解壓縮底層繁重的 Mesh 頂點資料，直接繪製幾何包圍盒，瞬間釋放數十 GB 的顯存與記憶體頻寬。

### 核心基礎：嚴格維護 `usdkind` 規則

USD ModelAPI 的所有高級能力（包括階層選取、邊界盒計算、以及 `drawMode`）**完全依賴正確的 `kind` 元數據（Metadata）**：

| Kind 類型 | 適用層級 | 職責與 ModelAPI 行為 |
| :--- | :--- | :--- |
| **`component`** | 單一 Asset 根節點（如 `/ROOT`） | **ModelAPI 的最小葉節點**。宣告為 `component` 後，Viewport 的 Model Selection 才能一鍵選取整件 Asset，且 `drawMode` 能正確作用於該單元。 |
| **`group`** | 部門分支或邏輯分組（如 `/ROOT/Props`） | 聚合多個 Model 的容器，本身不包含幾何資料。 |
| **`assembly`** | 大型場景集合（如 Set Dressing `livingroom.usd`） | 跨鏡頭的重要複合單元，支援整體階層的 DrawMode 降級顯示。 |
| **`subcomponent`** | Asset 內部的細部組件（如椅子的一隻腳） | 供結構內部標記，通常不對外暴露。 |

> [!CAUTION]
> **Pipeline 工具鏈鐵律：盡力維護 `usdkind`**
> 若上游建模、綁定或發布工具遺失了 `kind` 宣告，或將幾何誤標在非 Model 容器下，USD 的 ModelAPI 將完全失效——導致 Viewport 無法以 Component 為單位選取物件，且 `drawMode = "bounds"` 也將無法啟動。因此，**Pipeline 輸出工具（Solaris ROP、Publish Hook、DCC 導出器）必須在任何時候，盡全力驗證並維護合規的 `kind` 標記！**

---

## 4. 材質圖層 (`look.usd`) 與 Look VariantSet

Lookdev 部門獨立發佈材質資料。透過 `look` VariantSet，可在不複製任何幾何快取的前提下，提供多種色彩或質感樣式：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT" (
    variants = {
        string look = "LookDefault"
    }
    prepend variantSets = "look"
)
{
    variantSet "look" = {
        # 1. 預設材質
        "LookDefault" {
            def Scope "LookDefault"
            {
                def Material "M_Base" { /* 標準灰黑色金屬材質 */ }
            }
            # 綁定至幾何
            rel material:binding = </ROOT/LookDefault/M_Base>
        }

        # 2. 紅色變體 (LookRed)
        "LookRed" {
            def Scope "LookRed"
            {
                def Material "M_Red" { /* 紅色烤漆材質 */ }
            }
            rel material:binding = </ROOT/LookRed/M_Red>
        }

        # 3. 藍色變體 (LookBlue)
        "LookBlue" {
            def Scope "LookBlue"
            {
                def Material "M_Blue" { /* 藍色霧面材質 */ }
            }
            rel material:binding = </ROOT/LookBlue/M_Blue>
        }
    }
}
```

* **實務優勢**：當場景需要 50 輛同款汽車時，Reference 同一份 Asset，只需在 Shot 層各別指派 `look = "LookRed"` 或 `look = "LookBlue"`，即可實現零成本的外觀多樣性（Variation）。

---

## 5. Asset 總裝圖層 (`v###/asset.usd` 與 `asset_latest.usd`)

### 1. 各版次不可變總裝圖層 (`v###/asset.usd`)
當任何子物件（如 `modelDefault/v002/`）進版時，Pipeline 自動推進生成全新的 `v###/asset.usd`，內部以不可變的相對路徑明確鎖定各子組件的具體版本：

```usda
# /projects/show_A/publish/assets/props/chair/v002/asset.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
    subLayers = [
        @../lookDefault/v001/lookDefault.usd@,   # 材質維持在驗收通過的 v001
        @../modelDefault/v002/modelDefault.usd@  # 幾何推進至最新發布的 v002
    ]
)

over "ROOT" (
    kind = "component"
)
{
}
```

### 2. 頂層唯一最新動態指標 (`asset_latest.usd`)
外部消費端（Environment、Layout、Animation）**一律且唯一引用頂層的 `asset_latest.usd`**。在 Asset 進版時，Pipeline 自動將其重定向指向最新的版次：

```usda
# /projects/show_A/publish/assets/props/chair/asset_latest.usd (Windows 包裝層或 Linux Symlink)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./v002/asset.usd@
    ]
)
```

### 為什麼採用 Sublayer 堆疊 modelDefault 與 lookDefault？
1. **平行 Pipeline 作業（Parallel Workflow）**：
   - 建模師專注在 `modelDefault/` 的拓撲修改與進版。
   - Lookdev 藝術家專注在 `lookDefault/` 的材質調校與進版。
   - 任何一方進版，直接驅動 Asset 整體發布新版本並更新 `asset_latest.usd`，雙方完全平行作業而不互相鎖檔。
2. **材質覆寫優先級**：
   - `lookDefault` 位於 `modelDefault` 之上，確保外觀部門的 `material:binding` 意見能正確壓過幾何內部可能的預設材質。

---

## 6. 在鏡頭（Shot）中的使用範例

當環境部門在 `environment.usd` 中引用此 Asset 時，透過 `${PROJ_ROOT}` 參照，並可同時自由組合兩組 Variant：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Environment"
    {
        def Scope "Props"
        {
            # 前景道具：高模 + 紅色材質
            def Xform "HeroChair" (
                references = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
                variants = {
                    string model = "High"
                    string look = "LookRed"
                }
            ) {}

            # 遠景道具：低模 + 藍色材質
            def Xform "BGChair_01" (
                references = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
                variants = {
                    string model = "Low"
                    string look = "LookBlue"
                }
            ) {}
        }
    }
}
```

---

## 7. Asset 架構規範對照表

| 規範項目 | 規則說明 | 範例 / 命名 |
| :--- | :--- | :--- |
| **根節點** | 一律為 `/ROOT`，標記 `kind = "component"` | `/ROOT` |
| **幾何預設路徑** | 預設模型 Primitive 名稱 | `/ROOT/ModelDefault` |
| **材質預設路徑** | 預設材質 Primitive 名稱 | `/ROOT/LookDefault` |
| **Model VariantSet** | 幾何精細度或形態切換集合 | `model` 集（`Default`, `Low`, `High`） |
| **Look VariantSet** | 外觀色彩、磨損度或 Shader 切換集合 | `look` 集（`LookDefault`, `LookRed`, `LookBlue`） |
| **Purpose 完整性** | `render` 與 `proxy` 必須兩者齊備，否則保持 `default` | 避免 Viewport 與渲染農場顯示不同步 |
| **Viewport 優化首選** | 透過 `UsdGeomModelAPI` 之 `drawMode` 進行個別降級 | `model:drawMode = "bounds"` / `"cards"` |
| **Asset 交付形式** | Sublayer `lookDefault`（上）與 `modelDefault`（下） | `asset_latest.usd` / `asset.usd` |

---

## 8. Asset 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

Asset 發布同樣必須遵守全 Pipeline 通用的封裝鐵律：
1. **目錄即包裝單元（同構內部結構）**：以 Asset 目錄（如 `publish/assets/props/chair/`）為獨立封裝單位，內部結構與檔名一律固定為 `asset_latest.usd`、`modelDefault/`、`lookDefault/`、`textureDefault/` 等，嚴禁在內部檔名摻雜個別 Asset 名稱。
2. **Solaris Implicit Layer 禁錮**：若 Asset 於 Solaris 產出，所有導出的隱式圖層必須限制在該目錄及其子目錄（如 `./layers/`）內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：各版次 `v###/asset.usd` 堆疊 `@../lookDefault/...@` 與 `@../modelDefault/...@` 一律採用相對路徑（向上跳一層仍在 Asset Package 邊界內），貼圖引用包內 `@../textureDefault/...@` 亦為相對路徑，保障整顆 Asset 資料夾可完整隨意搬遷。
   - **包外引用**：若引用全域共用材質庫或全域 HDRI，輸出時由 Solaris Output Processor 自動改寫為 `@${PROJ_ROOT}/...@`，保障專案可隨意遷移或跨公司交接。

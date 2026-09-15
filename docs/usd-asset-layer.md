# USD：Asset Layer 架構與 VariantSet 設計

在整體 USD Pipeline 架構中，**Asset Layer（Asset 圖層）** 是構建所有場景（Environment、Animation、FX）的最基礎單元。

Asset 架構的核心目標是「**模型與外觀解耦、統一命名空間、透過 VariantSet 提供多樣性切換**」。

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一 `/ROOT` 命名空間**：Asset 檔案內部所有模型與材質一律掛載在 `/ROOT` 底下（`defaultPrim = "ROOT"`，`kind = "component"`）。
> 2. **Asset 雙核心組裝**：一個完整的 `asset.usd` 本身即是由 Pipeline 以 **Reference** 將幾何包（`modelDefault/`）與材質包（`lookDefault/`）兩者嫁接至 `/ROOT` 而成；各 sub 物件包皆為自成一體的封裝單元，擁有自己的 `/ROOT`。
> 3. **預設節點路徑**：
>    - 預設模型幾何：`/ROOT/ModelDefault`
>    - 預設材質外觀：`/ROOT/LookDefault`
> 4. **雙維度 VariantSet 與按需自動啟動機制**：
>    - **基準態（Baseline）**：以 `ModelDefault` 與 `LookDefault` 的唯一性作為標準基準。在只有單一幾何或外觀時保持結構最簡，不強制包裝多餘的 VariantSet。
>    - **按需自動啟動**：一旦檢測到出現額外變體（如 `ModelLow`、`ModelHigh`，或 `LookRed`、`LookBlue`），Pipeline 自動化機制即刻啟動對應的 `model` 或 `look` VariantSet，並將既有的 `Default` 設為預設選取項，達成無感向下相容。
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
│   └── asset.usd                                        <-- 固定名稱！Reference 鎖定子物件特定版次
├── v002/
│   └── asset.usd                                        <-- 固定名稱！
│
├── modelDefault/                                        <-- 固定的幾何 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── modelDefault.usd                             <-- 幾何版本檔案
│   └── v002/
│       └── modelDefault.usd
├── modelLow/                                            <-- 按需出現的變體 sub 物件目錄
│   └── v001/modelLow.usd
│
├── lookDefault/                                         <-- 固定的材質 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── lookDefault.usd                              <-- 材質版本檔案
│   └── v002/
│       └── lookDefault.usd
├── lookRed/                                             <-- 按需出現的變體 sub 物件目錄
│   └── v001/lookRed.usd
│
└── textureDefault/                                      <-- 固定的貼圖 sub 物件目錄 (無 latest！)
    ├── v001/
    └── v002/

       ▼ 組裝與展開後在 Stage 的結構 ▼

/ROOT (Xform, kind = component)
├── material:binding             <-- 綁定一律寫在 /ROOT，向下繼承給全部幾何
├── ModelDefault/                <-- (或切換為 ModelLow / ModelHigh)
│   └── Mesh/                    <-- 幾何零材質、零綁定
└── LookDefault/                 <-- (或切換為 LookRed / LookBlue)
    └── Materials/
```

> [!NOTE]
> `material:binding` 刻意寫在 `/ROOT` 而非 `LookDefault` 底下：`/ROOT` 被引用進鏡頭後即映射為實例根 Prim，使下游的唯一覆寫點收斂於此。完整規範詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。

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

模型部門獨立發佈幾何資料。在 Pipeline 自動化架構中，幾何圖層遵循「**以 `ModelDefault` 唯一性為基準、按需自動啟動 VariantSet**」的設計：

### 1. 基準態：`ModelDefault` 的唯一性
- 在日常製作中，絕大多數一般道具（Props）僅需單一標準精度模型。
- **極簡優先**：此時 `model.usd` 內部僅包含 `/ROOT/ModelDefault`，不強制生成空的或只有單一選項的 VariantSet 結構，保持圖層與記憶體開銷的極致輕量。
- **預先對齊路徑**：即使尚未啟動 VariantSet，幾何 Prim 亦統一命名為 `ModelDefault`，為後續可能的升級預留錨點。

幾何部門交付的內容極其單純——一個自成一體的幾何包，內部只有自己的分支：

```usda
# modelDefault/v002/modelDefault.usd （建模部門交付的幾何 sub 物件包）
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "ModelDefault"
    {
        def Mesh "Body" { /* 標準中精度網格資料；零材質、零綁定 */ }
    }
}
```

> [!IMPORTANT]
> **幾何包不宣告 `kind`、不宣告 `variantSets`**
> 這兩者皆屬結構性宣告，一律由 Pipeline 於總裝層統一掌管；建模部門只需交付自身分支的幾何內容。詳見 [發布封裝篇 §2 `/ROOT` 鐵律](usd-publish-packaging.md)。
>
> 幾何包同時必須恪守「零材質、零綁定」鐵律——`Material` Prim 與 `material:binding` 皆不得出現，詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。

### 2. 按需自動啟動：`ModelLow` / `ModelHigh` 誕生
- 當鏡頭效能或特寫需求出現，建模師額外發布了非預設精度模型時（例如出現了 `modelLow/` 或 `modelHigh/`）：
- **各精度各自成包**：`modelLow/v001/modelLow.usd` 內部同樣為 `def Xform "ROOT" { def Scope "ModelLow" { ... } }`，結構與 `modelDefault` 完全同構。
- **自動觸發封裝**：Pipeline 發布工具檢測到多個精度組件並存，**於總裝層自動啟動 `model` VariantSet 封裝流程**，各 variant 以 Reference 指向對應的幾何包。
- **以 `Default` 為安全鎖定**：強制將 `variants = { string model = "Default" }` 設為預設選取項，既有鏡頭畫面 100% 不受影響。

> 📖 總裝層的 VariantSet 實際寫法，詳見本篇 [§6.2 變體啟動後的總裝寫法](#2-變體啟動後的總裝寫法)。

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

Lookdev 部門獨立發佈材質資料。材質層同樣貫徹「**以 `LookDefault` 唯一性為基準、按需自動啟動 VariantSet**」的設計：

### 1. 基準態：`LookDefault` 的唯一性
- 在未拆分色彩或塗裝變體前，Asset 僅有單一標準外觀。
- **無負擔綁定**：材質包僅定義 `/ROOT/LookDefault`，並在自身 `/ROOT` 寫出綁定，不強制生成空的 VariantSet。
- **唯一性基準**：以 `LookDefault` 作為預設材質與著色方案的絕對基準。

材質部門交付的同樣是一個自成一體的材質包：

```usda
# lookDefault/v001/lookDefault.usd （Lookdev 部門交付的材質 sub 物件包）
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "LookDefault"
    {
        def Material "M_Base" { /* 標準灰黑色金屬材質 */ }
    }

    # 綁定寫在材質包自身的 /ROOT，經 Reference 嫁接後即落在 Asset 的 /ROOT，
    # 向下繼承給 ModelDefault 底下全部幾何。
    # 幾何包恪守零綁定鐵律，故此繼承意見絕不會被後代蓋過。
    rel material:binding = </ROOT/LookDefault/M_Base>
}
```

> [!IMPORTANT]
> **綁定一律寫在材質包自身的 `/ROOT` 層級**
> 綁定宣告於材質包的 `/ROOT` 而非下探至個別 Mesh，此寫法的成立前提是幾何包恪守「零材質、零綁定」鐵律——詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。
>
> 其直接效益是：切換 `model` variant（`ModelDefault` / `ModelLow` / `ModelHigh`）時，由於綁定落在共同祖先 `/ROOT`，**任一精度的幾何都自動承接正確材質**，Look 與 Model 兩個維度得以真正正交、互不牽動。

### 2. 按需自動啟動：`LookRed` / `LookBlue` 誕生
- 當劇情、場景陳設或藝術指導要求提供多款塗裝時（例如發布了 `lookRed/` 或 `lookBlue/`）：
- **各塗裝各自成包**：`lookRed/v001/lookRed.usd` 內部同樣為 `def Xform "ROOT" { def Scope "LookRed" { ... }; rel material:binding = </ROOT/LookRed/M_Red> }`，結構與 `lookDefault` 完全同構。
- **自動觸發封裝**：Pipeline 自動化組裝工具檢測到多個 Look 組件並存，**於總裝層自動啟動 `look` VariantSet 封裝流程**，各 variant 以 Reference 指向對應的材質包。
- **以 `LookDefault` 為安全鎖定**：強制設定 `variants = { string look = "LookDefault" }`。既有鏡頭由於預設回落至 `LookDefault`，畫面外觀 100% 保持穩定，達成零風險的平滑升級。

> 📖 總裝層的 VariantSet 實際寫法，詳見本篇 [§6.2 變體啟動後的總裝寫法](#2-變體啟動後的總裝寫法)。

* **實務優勢**：當場景需要 50 輛同款汽車時，Reference 同一份 Asset，只需在 Shot 層各別指派 `look = "LookRed"` 或 `look = "LookBlue"`，即可實現零成本的外觀多樣性（Variation）。

---

## 5. 材質綁定契約（Material Binding Contract）

這是全 Pipeline 材質行為的基礎契約，Asset、Shot 部門覆寫、Loader 標籤廣播與 FX 元素皆一體適用。

> [!CAUTION]
> **Pipeline 材質鐵律：幾何零材質、零綁定**
> 1. **嚴禁幾何層攜帶材質**：任何幾何發布單元（`modelDefault/`、FX 的 `layers/`、動畫幾何快取…）**一律不得包含任何 `Material` 或 `Shader` Prim**。
> 2. **嚴禁幾何層宣告綁定**：幾何單元內**一律不得出現任何 `material:binding`**，`GeomSubset` 上的分面綁定亦不例外。
> 3. **職責徹底二分**：幾何只負責拓樸、UV、Primvar 與 `GeomSubset` 分割；**外觀 100% 交由 look / material 圖層全權決定**。

### 1. 為什麼這條鐵律是整套覆寫機制的地基

OpenUSD 的材質綁定解析規則是：**先找該 Prim 自身的 direct binding，找不到才往祖先層層上溯**。這意味著——

> **後代的 direct binding 恆強於祖先的 inherited binding，且此規則與圖層強弱（Layer Strength）完全無關。**

因此只要幾何層在 Mesh 上寫了 direct binding，上游無論站在多強的圖層、用多高的權限，在祖先 Prim 上寫的 binding 都會**靜默失效**——不報錯、不警告，只是畫面沒變。這正是多數 Pipeline 材質覆寫「寫了卻沒反應」的根因。

反過來說，**只要幾何層徹底維持零綁定，祖先的意見便沒有任何競爭對手**，覆寫能力即回歸單純的 LIVRPS 組合弧強弱秩序：

| 綁定來源 | 抵達 Prim 的組合弧 | 強度 | 典型用途 |
| :--- | :--- | :---: | :--- |
| Shot 部門圖層直接寫在**實例根 Prim** | **Local**（Shot 根圖層堆疊） | **最強** | Lighting 微調單一道具材質、FX 接管外觀 |
| Loader 注入的 `/__CLASS__/{name}` 標籤 | **Inherits** | 次強 | 全場同類物件批量廣播（見 [Asset Loader 篇](usd-asset-loader.md)） |
| Asset 自身 `lookDefault`（含 `look` variant） | **References / Payload** | 基礎 | Asset 出廠預設外觀 |
| 幾何層 | —— | **不參與** | 零 binding，不產生任何意見 |

依 LIVRPS 秩序（`Local > Inherits > Variants > References > Payloads > Specializes`），此三層自然形成「鏡頭覆寫 > 類別廣播 > Asset 預設」的正確優先序，**無需任何額外機制**。

### 2. `lookDefault` 的綁定寫法

綁定一律寫在 **Asset 根 Prim `/ROOT`** 上，靠命名空間繼承傳遞給底下全部幾何：

```usda
# lookDefault/v001/lookDefault.usd
over "ROOT"
{
    def Scope "LookDefault"
    {
        def Material "M_Base" { /* 標準材質 */ }
    }

    # 綁定寫在 /ROOT，向下繼承給 ModelDefault 底下所有 Mesh。
    # 幾何層零 binding，因此此繼承意見不會被任何後代蓋過。
    rel material:binding = </ROOT/LookDefault/M_Base>
}
```

**這個位置是刻意選擇的**：`/ROOT` 被 Reference 進鏡頭後會映射為實例根 Prim（如 `/ROOT/Environment/Props/Table_01`），使得下游的唯一覆寫點就落在該實例根上。Lighting 與 Loader 因此**完全不需要知道 Asset 內部的 Mesh 結構**，`model` variant 切換為 `ModelLow` / `ModelHigh` 時綁定也自動跟著生效。

### 3. 唯一的例外邊界：`GeomSubset` 分面綁定

單一 Mesh 需分面綁定多種材質時，職責切分如下：

- **幾何層負責**：發布 `GeomSubset` Prim 本身，包含 `elementType`、`familyName` 與 `indices`（這是拓樸分割資訊，屬於幾何）。
- **幾何層不負責**：`GeomSubset` 上的 `material:binding`。
- **look 層負責**：以 `over` 逐一對各 `GeomSubset` 寫出綁定。

```usda
# lookDefault/v001/lookDefault.usd
over "ROOT"
{
    over "ModelDefault"
    {
        over "Body"
        {
            over "seat_fabric"   { rel material:binding = </ROOT/LookDefault/M_Fabric> }
            over "frame_metal"   { rel material:binding = </ROOT/LookDefault/M_Metal> }
        }
    }
}
```

> [!WARNING]
> 這是本契約中**唯一**由 look 層下探至幾何內部路徑的情境，代價是 look 層與幾何的 subset 命名產生耦合。因此 `GeomSubset` 的名稱一經發布即視為**對外介面**，建模端不得隨意改名——改名會使 look 層的 `over` 靜默落空。QC 必須驗證 look 層每個 `over` 路徑都命中實際存在的 Prim。

### 4. 發佈期強制執行（Publish-time Enforcement）

Houdini、Maya 等 DCC 的 USD 匯出器**預設就會在 Mesh 上寫入 direct binding**，因此本鐵律無法僅靠人工紀律維持，必須由發布工具強制執行：

1. **幾何發布 Hook 主動剝除**：輸出 `modelDefault.usd` / FX `layers/` 時，自動移除所有 `material:binding`（含 `GeomSubset` 上的）與所有 `Material` / `Shader` Prim。
2. **Pre-flight QC 必檢項**（見 [發布封裝篇 §2 階段二](usd-publish-packaging.md)）：掃描幾何發布單元，發現任何殘留的 binding 或 Material Prim 即**中斷發布並報錯**。
3. **失效模式提醒**：只要有一顆 Asset 夾帶了 direct binding，該 Asset 的所有下游覆寫都會靜默失效。這種問題在畫面上難以歸因，務必守在發布關口。

### 5. 例外機制：不合規外部 Asset 的 Collection-Based Binding

外包交付、第三方資產庫或歷史遺留 Asset，可能無法滿足零綁定鐵律。此時**唯一**能從祖先壓過後代 direct binding 的機制，是 `UsdShadeMaterialBindingAPI` 的 collection-based binding：

```usda
over "Table_01" (
    prepend apiSchemas = ["MaterialBindingAPI", "CollectionAPI:allGeom"]
)
{
    uniform token collection:allGeom:expansionRule = "expandPrims"
    rel collection:allGeom:includes = </ROOT/Environment/Props/Table_01>

    rel material:binding:collection:allGeom = [
        </ROOT/Environment/Props/Table_01/LookDefault/M_Base>,
        </ROOT/Lighting/Materials/M_Table_Darker>
    ]
    # 關鍵：預設為 weakerThanDescendants，必須顯式改為 strongerThanDescendants
    # 才能壓過 Asset 內部 Mesh 自帶的 direct binding
    uniform token material:binding:collection:allGeom:bindMaterialAs = "strongerThanDescendants"
}
```

> [!IMPORTANT]
> 此機制是**例外而非常態**。每次動用都代表有一顆 Asset 未達發布標準，應同時在資產管理系統標記待整改，而非讓 collection binding 淪為繞過鐵律的常規手段。

### 6. 與 `instanceable` 的關係

`instanceable = true` 的 Prim，其內部（Prototype）**不可被 author 任何 opinion**。但本契約將全部綁定收斂在**實例根 Prim**上，而實例根位於 Prototype 之外，因此 Lighting 與 Loader 的整體外觀覆寫**不受 instancing 限制**。

> [!WARNING]
> **需在部署版本實測確認**：祖先綁定能否正確傳遞至 Instance Proxy 底下的 Mesh，屬於 `UsdShadeMaterialBindingAPI` 的解析行為細節。導入前務必在工作室實際使用的 OpenUSD 版本上驗證，不可預設可用。
>
> 另須注意：若需**分面或針對 Asset 內部個別 Mesh** 做覆寫（而非整體換材質），instancing 會使其完全不可行——該實例必須放棄 `instanceable`。

---

## 6. Asset 總裝圖層 (`v###/asset.usd` 與 `asset_latest.usd`)

### 1. 各版次不可變總裝圖層 (`v###/asset.usd`)
當任何子物件（如 `modelDefault/v002/`）進版時，Pipeline 自動推進生成全新的 `v###/asset.usd`，內部以不可變的相對路徑明確鎖定各子組件的具體版本：

```usda
# /projects/show_A/publish/assets/props/chair/v002/asset.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "ROOT" (
    kind = "component"

    # 以 Reference 將各 sub 物件包嫁接至 /ROOT。
    # 清單順序即意見強弱：越前面越強，故 lookDefault 恆強於 modelDefault。
    prepend references = [
        @../lookDefault/v001/lookDefault.usd@</ROOT>,   # 材質維持在驗收通過的 v001
        @../modelDefault/v002/modelDefault.usd@</ROOT>  # 幾何推進至最新發布的 v002
    ]
)
{
}
```

> [!IMPORTANT]
> **為什麼採用 Reference 而非 Sublayer 嫁接 sub 物件**
> 1. **`/ROOT` 的所有權得以徹底切分**：Sublayer 會讓所有 sub 圖層與總裝層共用同一個命名空間，部門輸出勢必直接在總裝的 `/ROOT` 上寫意見。改用 Reference 後，**每個 sub 物件包都是自成一體的封裝單元、擁有自己的 `/ROOT`**，由 Pipeline 決定嫁接位置，總裝層的 `/ROOT` 始終為 Pipeline 獨佔。
> 2. **VariantSet 得以由 Pipeline 在總裝層統一封裝**：`variantSets` 屬於結構性宣告，理應由 Pipeline 掌管。Sublayer 無法寫在 variant 區塊內，Reference 則可（見下方 3.），使變體封裝完全收攏至總裝層，部門只需單純交付各自的幾何或材質包。
> 3. **意見強弱依然明確**：同一 Prim 上的多筆 `references` 依清單順序定強弱（越前面越強），與原先 `subLayers` 的語意完全一致，`lookDefault` 覆寫 `modelDefault` 的能力不受影響。

### 2. 變體啟動後的總裝寫法

當 Pipeline 檢測到變體 sub 物件並存（如 `modelLow/`、`lookRed/`），即自動改以 VariantSet 形式封裝。**variant 區塊直接承載 Reference**，各變體對應各自的 sub 物件包：

```usda
# /projects/show_A/publish/assets/props/chair/v003/asset.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "ROOT" (
    kind = "component"

    # 清單順序決定 VariantSet 之間的強弱：look 恆強於 model
    prepend variantSets = ["look", "model"]
    variants = {
        string look = "LookDefault"     # 一律以 Default 為安全預設
        string model = "Default"
    }
)
{
    variantSet "look" = {
        "LookDefault" ( prepend references = @../lookDefault/v001/lookDefault.usd@</ROOT> ) {}
        "LookRed"     ( prepend references = @../lookRed/v001/lookRed.usd@</ROOT> ) {}
        "LookBlue"    ( prepend references = @../lookBlue/v001/lookBlue.usd@</ROOT> ) {}
    }

    variantSet "model" = {
        "Default" ( prepend references = @../modelDefault/v002/modelDefault.usd@</ROOT> ) {}
        "Low"     ( prepend references = @../modelLow/v001/modelLow.usd@</ROOT> ) {}
        "High"    ( prepend references = @../modelHigh/v001/modelHigh.usd@</ROOT> ) {}
    }
}
```

> [!NOTE]
> **這與「不以 VariantSet 控版」的架構取捨並不衝突**
> [發布封裝篇 §6](usd-publish-packaging.md) 反對的是**以 VariantSet 承載版本序列**——那會迫使每次加版都回溯修改上層主檔。此處的 VariantSet 只承載**形態與外觀變體**，且各版次 `asset.usd` 皆由 Pipeline 在進版時整份重新生成，歷史版本依然 100% 凍結不可變。

### 3. 頂層唯一最新動態指標 (`asset_latest.usd`)
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

### 4. 以 Reference 嫁接 modelDefault 與 lookDefault 的架構效益
1. **平行 Pipeline 作業（Parallel Workflow）**：
   - 建模師專注在 `modelDefault/` 的拓撲修改與進版。
   - Lookdev 藝術家專注在 `lookDefault/` 的材質調校與進版。
   - 任何一方進版，直接驅動 Asset 整體發布新版本並更新 `asset_latest.usd`，雙方完全平行作業而不互相鎖檔。
2. **每個 sub 物件皆為自成一體的封裝單元**：
   - 各 sub 物件包擁有自己的 `/ROOT`，在自身邊界內完整自洽，部門**無須、亦不得**知悉總裝層的存在。
   - 嫁接位置與 `kind` 全數由 Pipeline 在總裝層決定，`/ROOT` 的所有權因此徹底切分乾淨。詳見 [發布封裝篇 §2 `/ROOT` 鐵律](usd-publish-packaging.md)。
3. **職責邊界的結構化保障**：
   - `lookDefault` 位於 `references` 清單前方，確保外觀部門對 `/ROOT` 所寫的任何意見，恆強於幾何包的同名意見。
   - 但須特別澄清：**Asset 的材質正確性並非倚賴此清單順序**。依 OpenUSD 規則，後代 Prim 的 direct binding 恆強於祖先的繼承意見，**與組合弧強弱完全無關**；`lookDefault` 排在前面也壓不過 Mesh 自帶的綁定。
   - 真正的保障來自「幾何零材質、零綁定」鐵律——幾何包根本不產生任何競爭意見。詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。

---

## 7. 在鏡頭（Shot）中的使用範例

當環境部門在 `environment.usd` 中引用此 Asset 時，透過 `${PROJECT_ROOT}` 參照，並可同時自由組合兩組 Variant：

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
                references = @`"${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd"`@</ROOT>
                variants = {
                    string model = "High"
                    string look = "LookRed"
                }
            ) {}

            # 遠景道具：低模 + 藍色材質
            def Xform "BGChair_01" (
                references = @`"${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd"`@</ROOT>
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

## 8. Asset 架構規範對照表

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

## 9. Asset 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

Asset 發布同樣必須遵守全 Pipeline 通用的封裝鐵律：
1. **目錄即包裝單元（同構內部結構）**：以 Asset 目錄（如 `publish/assets/props/chair/`）為獨立封裝單位，內部結構與檔名一律固定為 `asset_latest.usd`、`modelDefault/`、`lookDefault/`、`textureDefault/` 等，嚴禁在內部檔名摻雜個別 Asset 名稱。
2. **Solaris Implicit Layer 禁錮**：若 Asset 於 Solaris 產出，所有導出的隱式圖層必須限制在該目錄及其子目錄（如 `./layers/`）內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：各版次 `v###/asset.usd` 堆疊 `@../lookDefault/...@` 與 `@../modelDefault/...@` 一律採用相對路徑（向上跳一層仍在 Asset Package 邊界內），貼圖引用包內 `@../textureDefault/...@` 亦為相對路徑，保障整顆 Asset 資料夾可完整隨意搬遷。
   - **包外引用**：若引用全域共用材質庫或全域 HDRI，輸出時由 Solaris Output Processor 自動改寫為 ``@`"${PROJECT_ROOT}/..."`@``，保障專案可隨意遷移或跨公司交接。

# USD：Asset Layer 架構與 VariantSet 設計

在整體 USD Pipeline 架構中，**Asset Layer（Asset 圖層）** 是構建所有場景（Environment、Animation、FX）的最基礎單元。

Asset 架構的核心目標是「**模型與外觀解耦、統一命名空間、透過 VariantSet 提供多樣性切換**」。

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一 `/ROOT` 命名空間**：Asset 檔案內部所有模型與材質一律掛載在 `/ROOT` 底下（`defaultPrim = "ROOT"`，`kind = "component"`）。
> 2. **Asset 雙核心組裝**：一個完整的 `asset.usd` 本身即是由 Pipeline 以 **Reference** 將幾何包（`modelDefault/`）與材質包（`lookDefault/`）兩者嫁接至 `/ROOT` 而成；各 sub 物件包皆為自成一體的封裝單元，擁有自己的 `/ROOT`。
> 3. **預設節點路徑**：
>    - 預設模型幾何：`/ROOT/Model`
>    - 預設材質外觀：`/ROOT/Look`
> 4. **雙維度 VariantSet 與按需自動啟動機制**：
>    - **基準態（Baseline）**：以 `Model` 與 `Look` 的唯一性作為標準基準。在只有單一幾何或外觀時保持結構最簡，不強制包裝多餘的 VariantSet。
>    - **按需自動啟動**：一旦檢測到出現額外變體（如 `ModelLow`、`ModelHigh`，或 `LookRed`、`LookBlue`），Pipeline 自動化機制即刻啟動對應的 `model` 或 `look` VariantSet，並將既有的 `Default` 設為預設選取項，達成無感向下相容。
>    - **Model 變體**：如 `Model`、`ModelLow`、`ModelHigh`，透過 `model` variant set 切換幾何複雜度。
>    - **Look 變體**：如 `Look`、`LookRed`、`LookBlue`，透過 `look` variant set 切換材質與著色效果。
> 5. **版本控管的架構取捨**：經事先考量與權衡，VariantSet 專用於形態與外觀變體，版本迭代則統一採用目錄進版與 `latest` 機制，避免回溯修改上層註冊檔。詳見專題筆記：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)。
> 6. **Purpose 對稱完整性與 ModelAPI DrawMode 治理**：
>    - **Purpose 齊全原則**：幾何若定義了 `purpose`，**`render` 與 `proxy` 必須兩者皆齊全**；若無對應代理網格則一律保持為 `default`，防止 Viewport 與渲染農場顯示不同步。
>    - **減輕 Viewport 壓力之首選為 DrawMode**：`purpose` 是全域性切換，而 **USD ModelAPI 的 `drawMode`** 可針對個別 Component / Assembly 獨立指定顯示模式（如 `bounds`、`cards`、`default`），提供更細緻的效能控制。
>    - **嚴格維護 `kind` 階層**：Pipeline 工具鏈必須在任何時候全力維護 Prim 的 `kind` 規則（`component`, `group`, `assembly`），確保基於 ModelAPI 的階層選取與 DrawMode 機制可正常啟動。

---

## 1. 同構目錄與 Asset 圖層結構樹（Isomorphic Asset Structure）

無論任何 Asset（如 `Chair`、`Table`、`car`），資料夾內部結構與核心檔案名稱完全同構固定。

最核心的架構原則是：**`modelDefault/`、`lookDefault/`、`textureDefault/` 是屬於單元物件 Asset 底下的 sub 物件，自身絕不設獨立的 `latest` 指標；其底下每次進版，均直接推進單元物件 Asset 進版，並由 Pipeline 在 Asset 根目錄自動維護唯一的 `asset_latest.usda`**。

```text
/projects/show_A/publish/assets/props/Chair/               <-- 【Asset 目錄，只有此層名稱不同】
├── asset_latest.usda                                    <-- 全域唯一最新動態入口 (指向最新版 v002/asset.usd)
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

/ROOT (Xform, kind = component)          <-- 其上不承載任何屬性
├── Model/                               <-- 分支名固定；由 model variant 決定引用哪一包
│   └── Body (Mesh)                      <-- 幾何零材質、零綁定
│         └── material:binding           <-- 由 Look 包以 over 寫入
└── Look/                                <-- 分支名固定；由 look variant 決定引用哪一包
    └── M_Base (Material)
```

> [!IMPORTANT]
> **分支名固定為 `Model` 與 `Look`，不隨 variant 改變**
> 三個層級的命名各司其職，不可混為一談：
>
> | 層級 | 命名 | 說明 |
> | :--- | :--- | :--- |
> | **VariantSet 名** | `model`、`look` | 兩個正交維度 |
> | **Variant 選項名** | `Default`、`Low`、`High` / `Default`、`Red`、`Blue` | 選項不重複維度名 |
> | **資料夾名** | `modelDefault/`、`modelLow/`、`lookDefault/`、`lookRed/` | 同層兄弟目錄，**必須帶維度前綴才能區別** |
> | **Prim 分支名** | `/ROOT/Model`、`/ROOT/Look` | **固定不變**，各 variant 包一律定義同名分支 |
>
> 分支名固定是材質包得以 `over "Model"` 寫入綁定、且**切換 `model` variant 仍然生效**的前提。若各精度包各用其名，look 的 `over` 一換 variant 即靜默落空。

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
    references = @assets/props/Chair/asset_latest.usda@</ROOT>
) {}

def Xform "HeroSeat" (
    references = @assets/props/Chair/asset_latest.usda@</ROOT>
) {}
```
USD 的 Reference / Payload 機制會自動將來源檔的 `/ROOT` 映射為消費端指定的 Prim 名稱（如 `OfficeChair_A`），Asset 內部無需知道外部叫什麼，外部也無需妥協 Asset 內部的名稱。

### 3. 工具鏈與自動化腳本高度標準化（Predictable Tooling）
* 當全工作室所有 Asset 的根節點都是 `/ROOT`（且 `defaultPrim = "ROOT"`）時，所有自動化工具（如 LOD 自動產生器、材質發佈驗證工具、QC 檢查器、Bake 腳本）都可以直接鎖定 `/ROOT`。
* 腳本不需要動態解析「這個 Asset 叫什麼名字、根 Prim 叫什麼」，極大化簡化了 Pipeline 代碼的維護成本。

---

## 3. 幾何圖層 (`model.usd`) 與 Model VariantSet

模型部門獨立發佈幾何資料。在 Pipeline 自動化架構中，幾何圖層遵循「**以 `Model` 唯一性為基準、按需自動啟動 VariantSet**」的設計：

### 1. 基準態：`Model` 的唯一性
- 在日常製作中，絕大多數一般道具（Props）僅需單一標準精度模型。
- **極簡優先**：此時 `model.usd` 內部僅包含 `/ROOT/Model`，不強制生成空的或只有單一選項的 VariantSet 結構，保持圖層與記憶體開銷的極致輕量。
- **預先對齊路徑**：即使尚未啟動 VariantSet，幾何 Prim 亦統一命名為 `Model`，為後續可能的升級預留錨點。

幾何部門交付的內容極其單純——一個自成一體的幾何包，內部只有自己的分支：

```usda
# modelDefault/v002/modelDefault.usd （建模部門交付的幾何 sub 物件包）
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "Model"
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
| **`assembly`** | 大型場景集合（如 Set Dressing `LivingRoom.usd`） | 跨鏡頭的重要複合單元，支援整體階層的 DrawMode 降級顯示。 |
| **`subcomponent`** | Asset 內部的細部組件（如椅子的一隻腳） | 供結構內部標記，通常不對外暴露。 |

> [!CAUTION]
> **Pipeline 工具鏈鐵律：盡力維護 `usdkind`**
> 若上游建模、綁定或發布工具遺失了 `kind` 宣告，或將幾何誤標在非 Model 容器下，USD 的 ModelAPI 將完全失效——導致 Viewport 無法以 Component 為單位選取物件，且 `drawMode = "bounds"` 也將無法啟動。因此，**Pipeline 輸出工具（Solaris ROP、Publish Hook、DCC 導出器）必須在任何時候，盡全力驗證並維護合規的 `kind` 標記！**

### Model Hierarchy 連續性：機制與取捨

`kind` 之所以必須謹慎維護，關鍵在於 OpenUSD 的 **Model Hierarchy 連續性規則**：

> **一顆 Prim 要被納入 Model Hierarchy，其「父層必須是 `group` 類（`group` / `assembly`）」。**

此規則是 USD 的底層行為，無法以任何設定繞過。其影響有兩種表現形式，但**本質是同一件事**——某顆 model 在什麼情況下會掉出 Model Hierarchy：

1. **祖先鏈中斷**：從根到某顆 `component` 之間，任一中間容器未標記 `group`，該 `component` 及其底下即掉出階層。
2. **置於 `component` 之下**：`component` 本身不是 `group`，因此任何放在 `component` 底下的 model 同樣掉出階層。

> [!IMPORTANT]
> **掉出階層是「能力喪失」，不是「格式錯誤」——而且經常正是所欲的結果**
> 掉出 Model Hierarchy 時 USD **不會報錯**，檔案完全合法；失去的只是該 Prim 的 Model 能力：`UsdPrim.IsModel()` 回傳 `False`、無法以 Component 為單位選取、`model:drawMode` 不生效。
>
> 而這在許多情境下**正是設計意圖**：
> - **Kitbash Asset**：一台由多顆已發布輪子 Asset 組成的車，概念上就是「一個東西」。標記為 `component` 時，下游選取到的是整台車——這正是想要的行為。內部的輪子掉出階層，避免了它們被各別選取。
> - **`PointInstancer` 的 `Prototypes` 分支**：原型本來就不該被單獨選取、也不需各別降級（降級由 Instancer 整體處理）。
>
> 反過來說，若強行要求「`component` 之下不得有 model」而把 kitbash 車輛改標為 `assembly`，選取粒度就會變成各別輪子，**反而破壞了它應有的行為**。
>
> 因此本架構**不強制階層連續**。真正該被攔阻的只有一種情況：**發布者期待某顆 model 具備 Model 能力，卻因階層斷裂而靜默失效**。

### 階層形狀由發布者決定，Pipeline 只負責報告

本架構**不預先規定容器的名稱與層數，也不強制階層連續**。Layout 的組織方式本就因專案、因場景而異，硬訂一套容器分類法屬於過度設計，也與 `/ROOT` 解耦哲學（語意命名交給消費端）相悖。

因此規範只描述**機制與取捨**，形狀完全留給使用者：

| 項目 | 規範 |
| :--- | :--- |
| **容器命名與層數** | **完全自由**。`Props`、`Furniture/Chairs`、`BG/Layer_A/...` 任意分層皆可 |
| **祖先鏈上的容器** | 希望其下的 model 保有 Model 能力時標記 `kind = "group"`（`Scope` 可直接帶 `kind`，無須改為 `Xform`）；不需要則可留空 |
| **`component` 的擺放位置** | **完全自由**，其底下亦可再有 model——該 model 會掉出 Model Hierarchy，此結果在 Kitbash 等情境下正是所欲 |
| **合規與否** | Pipeline 於發布時**報告**掉出階層的 model 清單，供發布者確認是否為預期；僅在發布者明確聲明需要該能力時才攔阻 |

### `kind` 的值由發布者依「選取粒度意圖」決定

`kind` 不可由發布工具無條件寫死——但判斷依據**不是「內部有沒有引用其他單元」這類實作細節，而是「希望下游以什麼粒度選取與降級」的意圖**：

| 希望下游的行為 | `kind` | 內部 model 的處置 |
| :--- | :--- | :--- |
| **整體視為一個單位**選取與降級（一般道具、Kitbash 車輛、單顆 FX 元素） | `component` | 內部 model 掉出 Model Hierarchy——**正是所欲**，避免被各別選取 |
| **內部各組件可各別選取／各別指定 `drawMode`**（Set Dressing、Environment Set、大型建築群） | `assembly` | 把祖先鏈補齊為 `group`，使各組件保有 Model 能力 |

> [!IMPORTANT]
> **職責劃分**：發布者「**決定**」，Pipeline「**寫入**」並「**報告**」
> - **決定**：由發布者依選取粒度意圖選定 `kind`。發布工具應提供合理預設並允許覆寫——執行 `PointInstancer` 的特效師最清楚自己的原型該如何歸類，該決定權交給他。
> - **寫入**：`kind` 一律由 **Pipeline 於總裝層寫入**，sub 物件包內嚴禁宣告。此為 [`/ROOT` 鐵律](usd-publish-packaging.md)之一部分，不因決定權下放而改變。
> - **報告**：發布前 QC 沿祖先鏈走一遍，**列出所有掉出 Model Hierarchy 的 model 及其斷點**，供發布者確認。**這是提示而非攔阻**——唯有發布者明確聲明該 Prim 需要 Model 能力（例如已為其指定 `drawMode`）卻實際失效時，才視為錯誤並中斷發布。

### 鏡頭級 `kind` 階層參考

鏡頭組裝同樣適用上述規則。以下為**參考範例而非強制形狀**，只要祖先鏈連續即合規：

```usda
# shot.usd（Pipeline 總裝層）
def Xform "ROOT" ( kind = "assembly" ) {}

# environment.usd（部門輸出，只經營自身分支）
over "ROOT"
{
    def Scope "Environment" ( kind = "group" )      # 部門分支
    {
        def Scope "Props" ( kind = "group" )        # 中間容器，命名與層數自由
        {
            def Xform "Table_01" (                  # component 由 Asset 帶入
                payload = @`"${PROJECT_ROOT}/publish/assets/props/WoodenTable/asset_latest.usda"`@</ROOT>
            ) {}
        }
    }
}
```

> [!NOTE]
> **部門分支的 `kind` 由該部門圖層宣告**
> `/ROOT` 本身的 `kind` 屬 Pipeline 總裝層（`shot.usd`）；而 `/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting` 等部門分支的 `kind = "group"`，由各部門圖層自行宣告——那是它自己的分支，不違反 `/ROOT` 鐵律。


---

## 4. 材質圖層 (`look.usd`) 與 Look VariantSet

Lookdev 部門獨立發佈材質資料。材質層同樣貫徹「**以 `Look` 唯一性為基準、按需自動啟動 VariantSet**」的設計：

### 1. 基準態：`Look` 的唯一性
- 在未拆分色彩或塗裝變體前，Asset 僅有單一標準外觀。
- **無負擔綁定**：材質包僅定義 `/ROOT/Look`，並在自身 `/ROOT` 寫出綁定，不強制生成空的 VariantSet。
- **唯一性基準**：以 `Look` 作為預設材質與著色方案的絕對基準。

材質部門交付的同樣是一個自成一體的材質包：

```usda
# lookDefault/v001/lookDefault.usd （Lookdev 部門交付的材質 sub 物件包）
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "Look"
    {
        def Material "M_Base" { /* 標準灰黑色金屬材質 */ }
    }

    # 以 over 進入幾何分支寫出綁定；/ROOT 上不留任何屬性
    over "Model"
    {
        over "Body" { rel material:binding = </ROOT/Look/M_Base> }
    }
}
```

> [!IMPORTANT]
> **材質包以 `over` 進入幾何分支寫出綁定，`/ROOT` 上不留任何意見**
> 此作法有一項決定性的理由：**`GeomSubset` 分面綁定只能寫在各 subset 上**。一顆 Mesh 需要分面綁多材質時，`/ROOT` 層級的綁定根本做不到。既然多材質情形非 `over` 不可，單材質情形也走同一條路，規則才一致——這亦與 [FX Element 的材質層](usd-fx-layer.md)完全同構。
>
> 前提是幾何包恪守「零材質、零綁定」鐵律，`over` 寫入的綁定才不會與既有意見競爭。詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。

> [!WARNING]
> **`over` 落空是靜默的**
> 材質包的 `over` 依賴幾何包的 Prim 名稱。若建模端改了 Mesh 名，該 `over` **不產生任何作用**——USD 不報錯，只渲染出無材質的結果。
>
> 因此 Mesh 名稱一經發布即視為**對外介面**，不得隨意更動；QC 亦須驗證材質層每個 `over` 路徑皆命中實際存在的 Prim。

### 2. 按需自動啟動：`LookRed` / `LookBlue` 誕生
- 當劇情、場景陳設或藝術指導要求提供多款塗裝時（例如發布了 `lookRed/` 或 `lookBlue/`）：
- **各塗裝各自成包**：`lookRed/v001/lookRed.usd` 內部同樣為 `def Xform "ROOT" { def Scope "LookRed" { ... }; rel material:binding = </ROOT/LookRed/M_Red> }`，結構與 `lookDefault` 完全同構。
- **自動觸發封裝**：Pipeline 自動化組裝工具檢測到多個 Look 組件並存，**於總裝層自動啟動 `look` VariantSet 封裝流程**，各 variant 以 Reference 指向對應的材質包。
- **以 `Look` 為安全鎖定**：強制設定 `variants = { string look = "Default" }`。既有鏡頭由於預設回落至 `Look`，畫面外觀 100% 保持穩定，達成零風險的平滑升級。

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

依 LIVRPS 秩序（`Local > Inherits > Variants > References > Payloads > Specializes`），組合弧的強弱關係為「鏡頭覆寫（Local）> 類別廣播（Inherits）> Asset 預設（References）」。

> [!CAUTION]
> **但組合弧強弱只在「同一顆 Prim」上才有意義**
> 綁定解析的實際規則是「**由該 Prim 向上尋找最近一個帶綁定的祖先**」。一旦意見分處不同深度，**較近的祖先無條件勝出**，與組合弧強弱完全無關：
>
> | 綁定所在 Prim | 來源 | 對 `…/Table_01/Model/Body` 而言 |
> | :--- | :--- | :--- |
> | `…/Table_01/Model/Body` | Asset 的 look 包（References） | **最近祖先，勝出** |
> | `…/Table_01` | Lighting 覆寫（Local） | 較遠，**落敗** |
>
> 由於本契約要求材質包以 `over` 進入幾何分支寫出綁定（見 §5.2），Asset 自身的綁定深度必然深於實例根。**下游若在實例根寫覆寫，將靜默落敗。**

### 2. 下游覆寫的兩種作法，由覆寫者依意圖選擇

上述深度規則並非缺陷，而是**兩種不同意圖的分野**。本架構不規定該用哪一種：

| 意圖 | 作法 | 是否需知悉 Asset 內部 |
| :--- | :--- | :---: |
| **整顆換材質**（這張桌子改用深色木） | 於實例根施加 **collection-based binding**，並設 `bindMaterialAs = "strongerThanDescendants"` | **否** |
| **局部或分面**（只有桌面要深，桌腳不動） | 往下 `over` 至該 Mesh 或 `GeomSubset` | 是——但此意圖本就必須指名目標 |

**整顆換材質**的慣用寫法：

```usda
over "Table_01" (
    prepend apiSchemas = ["MaterialBindingAPI", "CollectionAPI:allGeom"]
)
{
    uniform token collection:allGeom:expansionRule = "expandPrims"
    rel collection:allGeom:includes = </ROOT/Environment/Props/Table_01>

    rel material:binding:collection:allGeom = </ROOT/Lighting/Materials/M_Table_Darker>
    # 關鍵：預設為 weakerThanDescendants，必須顯式改為 strongerThanDescendants
    uniform token material:binding:collection:allGeom:bindMaterialAs = "strongerThanDescendants"
}
```

> [!IMPORTANT]
> **唯一的不變量：覆寫必須確實生效**
> 規範不限定形狀，只要求結果正確。可程式判定的條件是——**覆寫意見所在的深度，不得淺於既有綁定**：
>
> | Asset 綁在 | 下游覆寫在 | 結果 |
> | :--- | :--- | :--- |
> | `Model/Body` | `Model/Body`（同一顆） | Local 強於 References，**覆寫勝** ✓ |
> | `Model/Body` | `Model`（較淺） | 較遠的祖先，**靜默落敗** ✗ |
> | `Model/Body` | 實例根 ＋ collection binding | 機制專為此設計，**覆寫勝** ✓ |
>
> 中間那列是真正的坑：寫了、不報錯、畫面沒變。因此 QC 應**偵測並報告**覆寫意見淺於既有綁定之情形，詳見 [Pipeline 驗證篇](usd-pipeline-validation.md)。

### 3. 材質包的綁定寫法

材質包以 `over` 進入幾何分支寫出綁定，**`/ROOT` 上不留任何屬性**：

```usda
# lookDefault/v001/lookDefault.usd
def Xform "ROOT"
{
    def Scope "Look"
    {
        def Material "M_Base" { /* 標準材質 */ }
    }

    # over 進幾何分支；幾何包恪守零綁定鐵律，故此意見無競爭對手
    over "Model"
    {
        over "Body" { rel material:binding = </ROOT/Look/M_Base> }
    }
}
```

採此寫法的三項理由：

1. **分面綁定別無選擇**：`GeomSubset` 的綁定只能寫在各 subset 上（見 §5.4）。多材質情形非 `over` 不可，單材質亦走同一條路，規則才一致。
2. **`/ROOT` 保持乾淨**：`/ROOT` 只承載「這個單元是什麼」（`kind`、`variantSets`），不承載「它長什麼樣」。詳見 [`/ROOT` 鐵律](usd-publish-packaging.md)。
3. **與 FX 完全同構**：[FX Element 的材質層](usd-fx-layer.md)本即以 `over` 寫回體積與粒子，兩端規則統一。

> [!CAUTION]
> **分支名固定是此寫法成立的前提**
> `over "Model"` 之所以能跨 `model` variant 生效，是因為各精度包**一律定義同名的 `/ROOT/Model` 分支**（見 §1 的命名表）。若各包各用其名，切換 variant 時 look 的 `over` 即靜默落空。
>
> 同理，Mesh 名稱一經發布即為**對外介面**。建模端改名會使材質層的 `over` 失效——不報錯、只是沒有材質。

### 4. 唯一的例外邊界：`GeomSubset` 分面綁定

單一 Mesh 需分面綁定多種材質時，職責切分如下：

- **幾何層負責**：發布 `GeomSubset` Prim 本身，包含 `elementType`、`familyName` 與 `indices`（這是拓樸分割資訊，屬於幾何）。
- **幾何層不負責**：`GeomSubset` 上的 `material:binding`。
- **look 層負責**：以 `over` 逐一對各 `GeomSubset` 寫出綁定。

```usda
# lookDefault/v001/lookDefault.usd
over "ROOT"
{
    over "Model"
    {
        over "Body"
        {
            over "seat_fabric"   { rel material:binding = </ROOT/Look/M_Fabric> }
            over "frame_metal"   { rel material:binding = </ROOT/Look/M_Metal> }
        }
    }
}
```

> [!WARNING]
> **`GeomSubset` 名稱一經發布即為對外介面**
> 這是本契約中**唯一**由 look 層下探至幾何內部路徑的情境，代價是 look 層與幾何的 subset 命名產生耦合。因此 `GeomSubset` 的名稱一經發布即視為**對外介面**，建模端不得隨意改名——改名會使 look 層的 `over` 靜默落空。QC 必須驗證 look 層每個 `over` 路徑都命中實際存在的 Prim。

### 5. 發佈期強制執行（Publish-time Enforcement）

Houdini、Maya 等 DCC 的 USD 匯出器**預設就會在 Mesh 上寫入 direct binding**，因此本鐵律無法僅靠人工紀律維持，必須由發布工具強制執行：

1. **幾何發布 Hook 主動剝除**：輸出 `modelDefault.usd` / FX `layers/` 時，自動移除所有 `material:binding`（含 `GeomSubset` 上的）與所有 `Material` / `Shader` Prim。
2. **Pre-flight QC 必檢項**（見 [發布封裝篇 §2 階段二](usd-publish-packaging.md)）：掃描幾何發布單元，發現任何殘留的 binding 或 Material Prim 即**中斷發布並報錯**。
3. **失效模式提醒**：只要有一顆 Asset 夾帶了 direct binding，該 Asset 的所有下游覆寫都會靜默失效。這種問題在畫面上難以歸因，務必守在發布關口。

### 6. Collection-Based Binding 的兩種用途

`UsdShadeMaterialBindingAPI` 的 collection-based binding 搭配 `bindMaterialAs = "strongerThanDescendants"`，是**唯一**能從祖先壓過後代 direct binding 的機制。它在本架構中有兩種正當用途：

| 用途 | 情境 |
| :--- | :--- |
| **下游整顆換材質**（正規手段） | Lighting 要替換整顆 Asset 的外觀，又不願知悉其內部結構。見 §5.2 |
| **壓過不合規 Asset 的自帶綁定**（例外處置） | 外包交付、第三方 Asset 庫或歷史遺留 Asset 未能滿足零綁定鐵律 |

兩者語法相同，差別僅在**為何需要它**。

```usda
over "Table_01" (
    prepend apiSchemas = ["MaterialBindingAPI", "CollectionAPI:allGeom"]
)
{
    uniform token collection:allGeom:expansionRule = "expandPrims"
    rel collection:allGeom:includes = </ROOT/Environment/Props/Table_01>

    rel material:binding:collection:allGeom = </ROOT/Lighting/Materials/M_Table_Darker>
    # 關鍵：預設為 weakerThanDescendants，必須顯式改為 strongerThanDescendants
    uniform token material:binding:collection:allGeom:bindMaterialAs = "strongerThanDescendants"
}
```

> [!IMPORTANT]
> **僅第二種用途須登記待整改**
> 用於下游換材質時，它是**正規手段**，無須任何額外處置。
>
> 但若動用它的原因是「該 Asset 自帶了不該存在的 direct binding」，則每次動用都代表**有一顆 Asset 未達發布標準**，應同時在 Asset 管理系統標記待整改——否則不合規的 Asset 會一直留在庫中，每個下游都要重複處理一次。

### 7. 與 `instanceable` 的關係

`instanceable = true` 的 Prim，其內部（Prototype）**不可被 author 任何 opinion**。但本契約將全部綁定收斂在**實例根 Prim**上，而實例根位於 Prototype 之外，因此 Lighting 與 Loader 的整體外觀覆寫**不受 instancing 限制**。

> [!WARNING]
> **需在部署版本實測確認**：祖先綁定能否正確傳遞至 Instance Proxy 底下的 Mesh，屬於 `UsdShadeMaterialBindingAPI` 的解析行為細節。導入前務必在工作室實際使用的 OpenUSD 版本上驗證，不可預設可用。
>
> 另須注意：若需**分面或針對 Asset 內部個別 Mesh** 做覆寫（而非整體換材質），instancing 會使其完全不可行——該實例必須放棄 `instanceable`。

---

## 6. Asset 總裝圖層 (`v###/asset.usd` 與 `asset_latest.usda`)

### 1. 各版次不可變總裝圖層 (`v###/asset.usd`)
當任何子物件（如 `modelDefault/v002/`）進版時，Pipeline 自動推進生成全新的 `v###/asset.usd`，內部以不可變的相對路徑明確鎖定各子組件的具體版本：

```usda
# /projects/show_A/publish/assets/props/Chair/v002/asset.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
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
# /projects/show_A/publish/assets/props/Chair/v003/asset.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
)

def Xform "ROOT" (
    kind = "component"

    # 清單順序決定 VariantSet 之間的強弱：look 恆強於 model
    prepend variantSets = ["look", "model"]
    variants = {
        string look = "Default"     # 一律以 Default 為安全預設
        string model = "Default"
    }
)
{
    variantSet "look" = {
        "Default" ( prepend references = @../lookDefault/v001/lookDefault.usd@</ROOT> ) {}
        "Red"     ( prepend references = @../lookRed/v001/lookRed.usd@</ROOT> ) {}
        "Blue"    ( prepend references = @../lookBlue/v001/lookBlue.usd@</ROOT> ) {}
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
> [發布封裝篇 §8](usd-publish-packaging.md) 反對的是**以 VariantSet 承載版本序列**——那會迫使每次加版都回溯修改上層主檔。此處的 VariantSet 只承載**形態與外觀變體**，且各版次 `asset.usd` 皆由 Pipeline 在進版時整份重新生成，歷史版本依然 100% 凍結不可變。

### 3. 頂層唯一最新動態指標 (`asset_latest.usda`)
外部消費端（Environment、Layout、Animation）**一律且唯一引用頂層的 `asset_latest.usda`**。在 Asset 進版時，Pipeline 自動將其重定向指向最新的版次：

```usda
# /projects/show_A/publish/assets/props/Chair/asset_latest.usda （Sublayer 包裝圖層）
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
   - 任何一方進版，直接驅動 Asset 整體發布新版本並更新 `asset_latest.usda`，雙方完全平行作業而不互相鎖檔。
2. **每個 sub 物件皆為自成一體的封裝單元**：
   - 各 sub 物件包擁有自己的 `/ROOT`，在自身邊界內完整自洽，部門**無須、亦不得**知悉總裝層的存在。
   - 嫁接位置與 `kind` 全數由 Pipeline 在總裝層決定，`/ROOT` 的所有權因此徹底切分乾淨。詳見 [發布封裝篇 §2 `/ROOT` 鐵律](usd-publish-packaging.md)。
3. **職責邊界的結構化保障**：
   - `lookDefault` 位於 `references` 清單前方，確保外觀部門對 `/ROOT` 所寫的任何意見，恆強於幾何包的同名意見。
   - 但須特別澄清：**Asset 的材質正確性並非倚賴此清單順序**。依 OpenUSD 規則，後代 Prim 的 direct binding 恆強於祖先的繼承意見，**與組合弧強弱完全無關**；`lookDefault` 排在前面也壓不過 Mesh 自帶的綁定。
   - 真正的保障來自「幾何零材質、零綁定」鐵律——幾何包根本不產生任何競爭意見。詳見本篇 [§5 材質綁定契約](#5-材質綁定契約material-binding-contract)。

---

## 7. 角色 Asset 結構（Character Asset）

角色與一般道具的關鍵差異在於：**幾何材質與綁定分屬不同部門、不同審批週期，且幾何材質本身對下游具備獨立的消費價值**（可作為靜態道具擺放、製作破碎版本、或不綁定直接使用）。

依 [§6.4 的判準](#4-以-reference-嫁接-modeldefault-與-lookdefault-的架構效益)——**該單元是否對下游有獨立、正當的消費價值**——角色因此拆分為**兩個獨立發布單元**：

| 發布單元 | 內容 | 入口檔名 | 交付部門 |
| :--- | :--- | :--- | :--- |
| **幾何材質角色** | 標準 Asset 結構（`modelDefault/`、`lookDefault/`、`textureDefault/`） | `asset.usd` / `asset_latest.usda` | Model / Lookdev |
| **綁定角色** | `SkelRoot` 總成，引用上者並疊加骨架 | **`char.usd` / `char_latest.usda`** | Rigging |

> [!NOTE]
> **入口檔名的區分對齊審批邊界**
> 入口檔名刻意以 `char` 與 `asset` 區分：兩者在專案中對外是不同單元，鏡頭端引用的是**綁定角色**（`char_latest.usda`）。發布單元邊界因此對齊審批邊界——Model／Lookdev 驗收一次、Rigging 驗收一次，與製作管理系統中的 task 劃分同形。

### 1. 綁定角色的目錄結構

```text
<綁定角色目錄>/
├── char_latest.usda                 <-- 全域唯一最新動態入口
├── v001/
│   └── char.usd                     <-- 固定名稱！/ROOT 為 SkelRoot
├── v002/
│   └── char.usd
└── skel/                            <-- 固定的骨架 sub 物件目錄 (無 latest！)
    ├── v001/skel.usd
    └── v002/skel.usd
```

`skel/` **不設 latest**：單獨取用骨架而不要幾何的情境（如 Mocap retarget）通常仍需對應的 bind pose 幾何，引用完整的 `char_latest.usda` 更安全。因此角色完全沿用既有的 sub 物件規則，不需任何例外。

### 2. 總裝結構：`SkelRoot` 底下的三顆分支

```usda
# v001/char.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
)

def SkelRoot "ROOT" (
    kind = "component"
)
{
    # 1. 幾何材質：引用幾何材質角色的 /ROOT，一次帶入 Model 與 Look
    def Xform "Geometry" (
        prepend references = @`"${PROJECT_ROOT}/publish/assets/char/Hero/asset_latest.usda"`@</ROOT>
    ) {}

    # 2. 骨架：引用本包內的 skel sub 物件
    def Skeleton "Skel" (
        prepend references = @../skel/v001/skel.usd@</ROOT/Skel>
    ) {}
}
```

合成後的 Stage 結構：

```text
/ROOT (SkelRoot, kind = component)
├── Geometry/                <-- 幾何材質 Asset 的 /ROOT 映射至此
│   ├── material:binding     <-- 綁定落在此層，不觸及角色的 /ROOT
│   ├── Model/Body
│   └── Look/Materials
├── Skel (Skeleton)          <-- joints / bindTransforms / restTransforms
│   └── BlendShapes/         <-- BlendShape 本體（靜態形狀資料）
├── Controls/                <-- 選用：烘出的控制器，purpose = "guide"（見 §7.3）
└── AnimData (SkelAnimation) <-- 鏡頭層注入，發布包內不存在
```

> [!IMPORTANT]
> **`/ROOT` 型別破例為 `SkelRoot`**
> 這是全 Pipeline 唯一不使用 `def Xform "ROOT"` 的發布單元。原因是 **`SkelRoot` 是 Hydra 解算 Skinning 的邊界**——不在 `SkelRoot` 底下的 Mesh，即使完整套用了 `SkelBindingAPI` 也不會產生變形。將邊界置於 `/ROOT` 可確保角色無論被引用至鏡頭何處，其變形恆常有效。
>
> 合成上無虞：總裝層的 Local 型別意見強於各包經 Reference 帶入的 `Xform`，composed 型別即為 `SkelRoot`。但此型別競爭須為工具鏈所知，不可誤判為衝突。

> [!TIP]
> **綁定落在 `Geometry` 而非角色的 `/ROOT`**
> 幾何材質 Asset 的 `material:binding` 寫在它自己的 `/ROOT` 上，經 Reference 映射後落於 `Geometry`。因此**沒有任何 sub 包需要碰角色的 `/ROOT`**，[`/ROOT` 鐵律](usd-publish-packaging.md)的白名單例外在角色這邊完全用不到。
>
> 這同時解決了一個常見錯誤：若改為引用 `</ROOT/Model>` 以求「只取幾何」，`/ROOT` 上的綁定不會隨之帶入，角色將完全失去材質。**一律引用完整的 `</ROOT>`。**

### 3. Rig 與 Skel：USD 承載變形，不承載綁定邏輯

「Rig」是部門與工序的名稱。**USD 本身沒有 rig 格式**——沒有任何 Schema 或檔案型別提供綁定功能。Rig 實際存在於 Houdini／Maya 的場景檔中，動畫製作也一律是打開 DCC 場景進行，而非開啟 USD。

`UsdSkel` 承載的是 Rig 的**輸出**，具體說是變形層，完整表面即以下四者：

| Schema | 承載內容 |
| :--- | :--- |
| `Skeleton` | `joints`（拓樸）、`jointNames`、`bindTransforms`、`restTransforms` |
| `SkelBindingAPI` | `primvars:skel:jointIndices` / `jointWeights`、`geomBindTransform`、`skinningMethod` |
| `SkelAnimation` | `joints`、`translations`、`rotations`、`scales`、`blendShapes`、`blendShapeWeights` |
| `BlendShape` | `offsets`、`normalOffsets`、`pointIndices` |

**無法表達的是求值邏輯**：IK／FK 解算、約束圖、運算式、Driven Key、Space Switch、Deformer Stack。這些留在 DCC 場景裡，不跨越發布邊界。

> [!IMPORTANT]
> **無法表達綁定邏輯，不等於控制器放不進 USD**
> 控制器的 transform 只是矩陣，完全可以烘成一般的 `Xform` Prim 帶時序取樣，隨 `skel` 或 `anim` 一併發布。實務上這是常見且值得做的——理由見下。

#### 蒙皮變形沒有可供 constraint 的對象

> [!CAUTION]
> **`Skeleton` 的關節不是 Prim**
> `joints` 是 `Skeleton` 上的 `token[]` 屬性，命名空間裡**不存在對應的 Prim**：
>
> ```text
> /ROOT/Skel                  ← Skeleton Prim，存在
> /ROOT/Skel/Root/Hip/Hand_L  ← 不存在，GetPrimAtPath() 回傳 invalid null prim
> ```
>
> 這與 [PointInstancer 實例不具 Prim 身分](usd-environment-setdressing.md)是**同一類問題**：陣列元素無法被 `over`、無法被指名，也**無法成為 constraint 的目標**。

因此當下游需要讓道具跟著角色的手走時，蒙皮後的 Mesh 給不出任何可指名的對象——它只是一批每幀變形的點，「手」在命名空間裡並不存在。**烘出來的控制器 `Xform` 在此成為唯一可定址的把手**，即使它們絕大多數不參與最終算圖。

非算圖用途的控制器應宣告 `purpose = "guide"`，使其在算圖時自動排除、在 Viewport 中仍可選取：

```usda
def Xform "Controls" (
    kind = "group"
)
{
    token purpose = "guide"

    def Xform "CTRL_Hand_L"
    {
        matrix4d xformOp:transform.timeSamples = { ... }
        uniform token[] xformOpOrder = ["xformOp:transform"]
    }
}
```

> [!TIP]
> **USD 原生的精簡替代方案：`constraintTargets`**
> `UsdGeomModelAPI` 提供 `constraintTargets:<name>`（型別 `matrix4d`），專為「對外公開若干可供約束的座標」而設，無須搬運整套控制器階層：
>
> ```usda
> def Xform "ROOT" (
>     prepend apiSchemas = ["GeomModelAPI"]
>     kind = "component"
> )
> {
>     matrix4d constraintTargets:HandL.timeSamples = { ... }
> }
> ```
>
> 兩者取向不同、可並存：控制器帶著完整的製作語意與階層，適合需要貼近原始 Rig 的情境；`constraintTargets` 則是刻意精簡的對外介面，只承諾若干具名座標。惟須注意 `GetConstraintTargets()` **僅在該 Prim 具 model `kind` 時才列舉得到**。

#### 兩個詞各自的適用域

- **Rig** — 部門、工序、審批關卡與[分類目錄](usd-publish-packaging.md)（`publish/rig/<unit>/`）
- **Skel** — Prim 名與 Schema（`/ROOT/Skel`、`UsdSkelSkeleton`）

把 Prim 命名為 `Rig` 會讓人打開檔案去找解算邏輯，然後找不到——USD 裡沒有那種東西。

> [!IMPORTANT]
> **綁定角色是消費用產物**
> 發布出去的綁定角色**無法以原本的控制器重新動畫**——控制器縱使一併烘出，也只剩每幀的矩陣，背後的 IK 與約束網路並未隨行。下游能做的是透過 `SkelAnimation` 驅動 joints、改寫 `blendShapeWeights`，或**以控制器為錨點做約束**。
>
> 這正是 `AnimData` **不存在於發布包內、僅由鏡頭層注入**的原因——發布包沒有能產生它的東西。同理，[`skel/` 不設 `latest`](#1-綁定角色的目錄結構)的取捨亦受同一限制約束。

### 4. `skel/` 包的內容與蒙皮權重的 `over`

骨架包交付三樣東西：`Skeleton` 拓樸、`BlendShape` 本體，以及**以 `over` 寫回幾何的蒙皮資料**：

```usda
# skel/v001/skel.usd （Rigging 部門交付的骨架 sub 物件包）
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Skeleton "Skel"
    {
        uniform token[] joints = ["Hips", "Hips/Spine", "Hips/Spine/Chest"]
        uniform matrix4d[] bindTransforms = [ /* 世界空間 */ ]
        uniform matrix4d[] restTransforms = [ /* joint-local 空間 */ ]

        def Scope "BlendShapes"
        {
            def BlendShape "smile" { uniform vector3f[] offsets = [ /* ... */ ] }
        }
    }

    # 以 over 寫回幾何包的 Mesh，注入蒙皮資料
    over "Geometry"
    {
        over "Model"
        {
            over "Body" ( prepend apiSchemas = ["SkelBindingAPI"] )
            {
                rel skel:skeleton = </ROOT/Skel>
                rel skel:blendShapeTargets = [ </ROOT/Skel/BlendShapes/smile> ]
                uniform token[] skel:blendShapes = ["smile"]

                # elementSize 必須明確設定（每點影響的 joint 數，常見 4 或 8）
                int[] primvars:skel:jointIndices = [ /* ... */ ] ( elementSize = 4 )
                float[] primvars:skel:jointWeights = [ /* ... */ ] ( elementSize = 4 )
                matrix4d primvars:skel:geomBindTransform = ( /* ... */ )
            }
        }
    }
}
```

> [!IMPORTANT]
> **蒙皮權重歸骨架包，不歸幾何包**
> `primvars:skel:jointIndices` / `jointWeights` / `geomBindTransform` 雖然寫在 Mesh 上，卻是**綁定部門的產出**。若置於幾何包內，綁定師每次調權重都得推進幾何版本——即使拓樸一個點也沒動。
>
> 交由骨架包以 `over` 注入之後，權重與骨架同版進退，幾何包維持純幾何。此模式與 [`lookDefault` 以 `over` 寫回綁定](#5-材質綁定契約material-binding-contract)**完全同構**。
>
> 同理，`rel skel:skeleton` 也寫在這個 `over` 裡而非掛在 `SkelRoot` 上靠繼承——既然本來就要 over 每顆 Mesh，順帶多一條 rel 是零成本，換來 `/ROOT` 完全不被觸碰。

> [!CAUTION]
> **`elementSize` 未設定是最常見的致命錯誤**
> `jointIndices` / `jointWeights` 必須透過 `UsdGeomPrimvar.SetElementSize(n)` 明確宣告每點影響的 joint 數量，否則 imaging 端**無法切分每點影響數**，Skinning 結果錯亂。此項列為發布前 QC 必檢。詳見 [USD Skel 骨架動畫設定指南](usd-skel-guide.md)。

### 5. 跨包引用 `latest` 的取捨

`Geometry` 引用的是幾何材質角色的 **`asset_latest.usda`**（動態指標），而非鎖定的具體版次。這是刻意的選擇：

- **接受漂移**：建模一進版，既有的 `char/v001` 所看到的幾何即隨之更新。由於製作人員與流程本就存在時間差，拓樸變動導致的權重失效**必然會在畫面上顯現**，屬可被發現、可被修復的問題。
- **凍結交由 Resolver**：歷史可重現性由 [Asset Resolver 逆向鎖定](usd-publish-packaging.md)在送算與審批時達成，與全 Pipeline「日常漂移、關鍵時刻鎖定」的一貫精神一致。

> [!WARNING]
> **此取捨對 Resolver 快照提出硬性要求**
> 快照必須**遞移涵蓋整棵依賴樹**：鏡頭引用 `char_latest` → 鎖定至 `char/v002` 尚不足夠，必須一路鎖定其內部引用的 `assets/char/Hero/v003`。若僅鎖定直接引用的一層，跨包的可重現性即為虛假。
>
> 另建議：發布幾何材質角色時，若偵測到 point count 或 topology hash 變動，應**主動告警依賴它的綁定角色單元**。拓樸變更會使全部權重失效，下游必然重工，不應等動畫師發現角色炸裂才得知。

---

## 8. 在鏡頭（Shot）中的使用範例

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
                references = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
                variants = {
                    string model = "High"
                    string look = "LookRed"
                }
            ) {}

            # 遠景道具：低模 + 藍色材質
            def Xform "BGChair_01" (
                references = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
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

## 9. Asset 架構規範對照表

| 規範項目 | 規則說明 | 範例 / 命名 |
| :--- | :--- | :--- |
| **根節點** | 一律為 `/ROOT`，標記 `kind = "component"` | `/ROOT` |
| **幾何預設路徑** | 預設模型 Primitive 名稱 | `/ROOT/Model` |
| **材質預設路徑** | 預設材質 Primitive 名稱 | `/ROOT/Look` |
| **Model VariantSet** | 幾何精細度或形態切換集合 | `model` 集（`Default`, `Low`, `High`） |
| **Look VariantSet** | 外觀色彩、磨損度或 Shader 切換集合 | `look` 集（`Look`, `LookRed`, `LookBlue`） |
| **Purpose 完整性** | `render` 與 `proxy` 必須兩者齊備，否則保持 `default` | 避免 Viewport 與渲染農場顯示不同步 |
| **Viewport 優化首選** | 透過 `UsdGeomModelAPI` 之 `drawMode` 進行個別降級 | `model:drawMode = "bounds"` / `"cards"` |
| **Asset 交付形式** | Sublayer `lookDefault`（上）與 `modelDefault`（下） | `asset_latest.usda` / `asset.usd` |

---

## 10. Asset 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

Asset 發布同樣必須遵守全 Pipeline 通用的封裝鐵律：
1. **目錄即包裝單元（同構內部結構）**：以 Asset 目錄（如 `publish/assets/props/Chair/`）為獨立封裝單位，內部結構與檔名一律固定為 `asset_latest.usda`、`modelDefault/`、`lookDefault/`、`textureDefault/` 等，嚴禁在內部檔名摻雜個別 Asset 名稱。
2. **Solaris Implicit Layer 禁錮**：若 Asset 於 Solaris 產出，所有導出的隱式圖層必須限制在該目錄及其子目錄（如 `./layers/`）內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：各版次 `v###/asset.usd` 堆疊 `@../lookDefault/...@` 與 `@../modelDefault/...@` 一律採用相對路徑（向上跳一層仍在 Asset Package 邊界內），貼圖引用包內 `@../textureDefault/...@` 亦為相對路徑，保障整顆 Asset 資料夾可完整隨意搬遷。
   - **包外引用**：若引用全域共用材質庫或全域 HDRI，輸出時由 Solaris Output Processor 自動改寫為 ``@`"${PROJECT_ROOT}/..."`@``，保障專案可隨意遷移或跨公司交接。

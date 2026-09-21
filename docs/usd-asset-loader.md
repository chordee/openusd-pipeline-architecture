# USD：Asset Loader 工具架構與全元素載入規範

在 USD 影視與動畫生產 Pipeline 中，**Environment、Layout、Lighting 與 FX 部門**需要頻繁載入海量發布元素來搭建與擺放場景。

傳統 DCC 工具常將「Asset 檢索」與「軟體內節點生成」緊密揉雜，甚至封裝出專有節點，導致跨 DCC 難以移植或破壞 USD 圖層結構。本架構旨在建立一套「**瀏覽檢索與載入行為分離**」、「**100% 依循 OpenUSD 原生組合弧**」、且具備「**自由命名掛載路徑**」與「**Class Inherits 標籤廣播**」的工業級 Asset Loader 規範。

---

> [!IMPORTANT]
> **30 秒架構核心原則**
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
>    - **代價**：Instance 內部不可 author 任何 opinion，等同放棄一切內部覆寫能力（含 Class 廣播）。記憶體效益與可覆寫性無法兼得。
> 6. **預設 Class Inherits 多重標籤分類機制**：
>    - 預設注入 `/__CLASS__/{專案註冊名稱}`，並允許藝術家追加或自訂 Class 標籤，達成跨物件的廣播式覆寫與分類管理。
>    - **廣播意見一律往下走**，明確指向 Asset 內部目標 Prim，嚴禁直接寫在 Class 根 Prim 上（否則整顆 Asset 的材質層次將被抹平）。

---

## 1. 兩段式架構流程圖 (Query & Load Architecture)

```text
┌─────────────────────────────────────────────────────────────┐
│                 階段一：Query（獨立瀏覽檢索器）               │
│  - 跨 DCC 通用獨立 UI（或嵌於 DCC 面板）                    │
│  - 全專案發布目錄檢索（Asset, SetDressing, FX, Pure USD）    │
│  - 動態版本篩選（預設 *_latest.usda，支援歷史 v### 鎖定）     │
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
│     ├── 預設繼承：/__CLASS__/Chair                           │
│     └── 追加標籤：/__CLASS__/indoor_props                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 階段一：Query（獨立瀏覽檢索器）

### 職責邊界
檢索器專注於「找到對的元素與對的版本」，與具體 DCC 解耦：
1. **全元素開放檢索**：
   - **Component Asset**（如 `assets/props/Chair/`）
   - **Set Dressing Assembly**（如 `sets/LivingRoom/`）
   - **FX Element**（如 `fx/elements/ExplosionHero/`）
   - **Pure USD Unit**（如 `shots/sq01/sh010/layout/ScatterForest/`）
2. **版本決策（Latest vs Version Pinning）**：
   - **預設選項**：`asset_latest.usda` / `element_latest.usda`（日常製作推薦，享受自動更新）。
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
在傳統軟體中，匯入檔案常強行依檔名產生節點（例如匯入 `Chair.usd` 強制在 `/Chair`）。但在本架構中：
- 所有被發布的元素，其內部根節點**一律同構解耦為 `/ROOT`**。
- **Loader 允許藝術家自由指定擺放路徑**：
  - 預設建議路徑：`/ROOT/Environment/Props/{asset_name}_01`
  - 藝術家自訂重構：`/ROOT/SetDressing/LivingRoom/Furniture/HeroArmChair`

```usda
# 藝術家將 chair 載入並重命名為 HeroArmChair，語意高度貼合場景
def Xform "HeroArmChair" (
    payload = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
)
{
    double3 xformOp:translate = (1.2, 0, 0.45)
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
    payload = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
)
{
    double3 xformOp:translate = (0, 0, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}

def Xform "Chair_02" (
    instanceable = true
    payload = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
)
{
    double3 xformOp:translate = (1.5, 0, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}
```

### 核心架構效益
1. **Stage 記憶體共享**：所有 `instanceable = true` 且組合弧相同的 Prim，在 USD Core 內部僅保留一份 Prototype 記憶體結構，顯著釋放記憶體。
2. **與 PointInstancer 的定位互補**：
   - `PointInstancer`：適合數萬至數百萬個純粒子點雲驅動的自然散佈（樹林、落葉），無法各別微調 Transform。
   - `Instanceable Xform`：適合幾十到幾百個由藝術家手工擺放、需各別精準旋轉微調或獨立切換 Variant 的場景道具。

> [!CAUTION]
> **勾選 `instanceable` 放棄的是「逐實例覆寫」，不是全部的覆寫能力**
> Instance 內部為 Instance Proxy，**不可 author 任何 opinion**。一旦標記 `instanceable`：
> - 下游（Lighting、FX）**無法**以 `over` 進入 Asset 內部改單一 Mesh 的材質或可見度——`OverridePrim()` 會直接拋出編輯驗證錯誤，只能整顆實例開關。
> - **但 [§5.5 的 Class 廣播不受此限](#5-穿透-instanceableinherit-是唯一的覆寫途徑)**：`inherits` 的意見是 Prototype 組合的一部分，而非施加於 Instance Proxy 的外部覆寫，因此穿透生效。這是 Instanceable Asset **唯一**的內部覆寫途徑。
> - 代價是 `inherits` 參與 Prototype 識別：**攜帶意見的 Class 標籤會使 Prototype 分裂**，標籤組合越多、共享率越低。
>
> 因此 Loader 介面應如此提示取捨：需要「**只改這一顆**」的實例不得勾選；需要「**改全部同類**」則應勾選並改用 Class 廣播。

---

## 5. 預設 `inherit` 多重標籤分類機制（Class Inherits）

在複雜鏡頭中，下游部門（特別是 Lighting 與 Lookdev）常需對全場特定類別的 Asset 或元素進行「**批量屬性覆寫**」或「**全域分組控制**」。Loader 導入了標準的 **`inherit`** 標籤規範：

### 1. 預設規範：`/__CLASS__/{專案註冊名稱}`
當透過 Loader 載入名為 `Chair` 的 Asset 時，Loader 預設自動在 Prim 上注入該 Asset 的 Class 繼承：

```usda
# Loader 產出的實體 Prim
def Xform "OfficeChair_01" (
    # 預設自動注入：/__CLASS__/Chair
    inherits = </__CLASS__/Chair>
    payload = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
) {}
```

### 2. 允許使用者追加與自訂（多重標籤分類）
Loader 介面提供「Inherit Classes / Tags」輸入欄，藝術家可追加更多業務標籤：

```usda
def Xform "OfficeChair_01" (
    # 藝術家追加多重標籤繼承
    inherits = [
        </__CLASS__/Chair>,
        </__CLASS__/wooden_props>,
        </__CLASS__/interior_dressing>
    ]
    payload = @`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`@</ROOT>
) {}
```

### 3. Class Inherits 的廣播式覆寫能力（Broadcasting Overrides）
這套機制賦予了全 Pipeline 極為強大的批量治理能力。Class 的命名空間必須與 Loader 注入的 `inherits` 路徑完全一致（`/__CLASS__/{name}`）：

```usda
# 在 lighting.usd 或 lookdev_override.usd 中定義 Class
class "__CLASS__"
{
    class "wooden_props"
    {
        # 【正確】意見往下走，落在 Asset 內部的具體目標 Prim 上
        over "Model"
        {
            over "Frame"
            {
                # 一次宣告，全場所有繼承 wooden_props 的桌椅，其木框同步套用此材質
                rel material:binding = </ROOT/Lighting/Materials/M_GlobalWoodVarnish>
            }
        }
    }
}
```

> [!CAUTION]
> **廣播意見必須往下走，嚴禁直接寫在 Class 根 Prim 上**
> Class 根 Prim 的意見會落在**實例根 Prim**（如 `/ROOT/Environment/Props/OfficeChair_01`），亦即 Asset 自身 `lookDefault` 綁定所在的同一顆 Prim。若將 `material:binding` 直接寫在 Class 根上：
> 1. **整顆 Asset 的材質層次全數被抹平**：椅子的布面、金屬腳、木框會一律變成同一個 `M_GlobalWoodVarnish`。Asset 端辛苦拆分的多材質結構完全失效。
> 2. **Asset 自身外觀被無聲取代**：依綁定契約，Class 走 Inherits 弧、恆強於 Asset 的 References 弧。藝術家只會看到椅子突然整顆變成木紋，卻查不出是哪裡來的意見。
> 3. **失去與個別覆寫共存的空間**：Lighting 針對單一實例的微調同樣寫在實例根，兩者在同一顆 Prim 上正面競爭，無法分工。
>
> 因此廣播意見**一律往下走**，明確指向 Asset 內部的目標 Prim，才能達成「只改該改的部分」。

#### 採用往下走時必須一併考量的四項代價

> [!WARNING]
> **一、綁定優先序會被反轉——這是最需要警覺的一項**
> OpenUSD 的材質綁定解析是「**由該 Prim 向上尋找最近一個帶綁定的 ancestor**」，**組合弧強弱只在同一顆 Prim 上有意義**。因此當意見分處不同層級時：
>
> | 綁定所在 Prim | 來源 | 對 `/…/OfficeChair_01/Model/Frame` 而言 |
> | :--- | :--- | :--- |
> | `…/OfficeChair_01/Model/Frame` | Class 往下走 | **最近 ancestor，勝出** |
> | `…/OfficeChair_01` | Lighting 個別覆寫（Local） | 較遠，落敗 |
> | `…/OfficeChair_01` | Asset 自身 `lookDefault`（References） | 較遠，落敗 |
>
> 亦即：**Class 往下走之後，其意見會無條件壓過 Lighting 在實例根所做的個別微調**，與 [Asset Layer 篇 §5 材質綁定契約](usd-asset-layer.md#5-材質綁定契約material-binding-contract)所定的「鏡頭覆寫 > 類別廣播 > Asset 預設」優先序**恰好相反**。
>
> **因應原則**：Lighting 若需推翻某個實例的 Class 廣播，**必須在同一深度**（即該實例的 `Model/Frame`）寫出覆寫，靠 Local 強於 Inherits 取勝；不可期待在實例根覆寫就能壓過。此點必須明確告知燈光組，否則會出現「改了沒反應」的狀況。

> [!WARNING]
> **二、與 Asset 內部結構產生耦合**
> 往下走意味著 Class 必須知道 `Model/Frame` 這類路徑，這與 `/ROOT` 解耦哲學有所拉扯，且 `model` variant 切換為 `ModelLow` 時路徑即改變、廣播隨之落空。
>
> **因應原則**：廣播只應錨定於**架構保證存在的穩定路徑**（如規範明訂的 `Model` 分支），或改以 `GeomSubset` 的 `familyName` 等跨 Asset 一致的約定為目標。嚴禁錨定個別 Asset 的隨意命名。

> [!WARNING]
> **三、`over` 落空是靜默的**
> Class 內的 `over` 若在某顆 Asset 上找不到對應路徑（例如該桌子根本沒有 `Frame`），USD **不會報錯、不會警告**，該實例單純不受影響。廣播給 100 顆 Asset 時，可能只有 60 顆生效而無人察覺。
>
> **因應原則**：Loader 或 QC 工具須提供「廣播命中率檢查」——列出實際套用到的實例數與未命中的清單。

> [!CAUTION]
> **四、與 `instanceable` 完全互斥**
> `instanceable = true` 的 Prim，其內部為 Instance Proxy，**不可 author 任何 opinion**。Class 往下走的 `over` 全數落在 Prototype 內部，**完全無效**。
>
> 而本篇 §4 正好推薦高密度道具啟用 `instanceable`，兩者直接衝突。必須擇一：
> - **需要 Class 往下廣播** → 該實例**不得**標記 `instanceable`。
> - **需要 instancing 記憶體效益** → 廣播只能停留在實例根（整顆換材質），或改於 Asset 端以 `look` variant 解決。
>
> 另須注意：`inherits` 本身是組合弧，**會參與 Prototype 的識別**。§5.2 所鼓勵的「自由追加多重標籤」，每一種不同的標籤組合都會產生一份獨立 Prototype，直接侵蝕 instancing 的共享效益。Loader 應在介面上提示此代價。

* **零侵入性**：燈光師不需要在場景中遍歷 100 把椅子逐一寫入 override，只需針對頂層 Class 定義一次，所有實例即刻生效。
* **高內聚分類**：Class 在 USD 中不佔用空間實體，也不干擾階層的 Transform 幾何運算，是純粹的語意標籤。
* **Relationship 目標不重映射**：`inherits` 與 Reference 不同，屬同一命名空間內的組合弧，**Class 內的 relationship 目標路徑不會被重映射**。因此可直接指向鏡頭層級的共用材質（如 `/ROOT/Lighting/Materials/...`），這正是廣播機制得以運作的關鍵。

### 4. `/__CLASS__` 必須以 `class` 指示符宣告

Class 命名空間的根**一律以 `class` 指示符建立**，不得使用 `def` 或 `over`。Pipeline 應在 Stage 初始化時預設建立，使藝術家不會在任何情境下意外以 `def` 生成它：

```python
stage.CreateClassPrim("/__CLASS__")     # 指示符為 class，IsAbstract() == True
```

差別不只是語意。`class` 指示符使該 Prim 成為**抽象（Abstract）**，而 USD 預設的 Stage 走訪**直接跳過抽象 Prim**：

| 指示符 | `IsAbstract()` | 預設 `Stage.Traverse()` |
| :--- | :---: | :---: |
| `class` | `True` | **跳過** |
| `def` | `False` | 走訪 |

> [!CAUTION]
> **誤用 `def` 會讓 Class 成為真實場景內容**
> 一旦 `/__CLASS__` 以 `def` 宣告，它就是一顆貨真價實的 Prim：渲染器會走訪它、匯出工具會帶上它、QC 腳本會把它算進 Prim 統計、包圍盒計算會納入它的子階層，Outliner 中也會多出一棵與製作無關的樹。而 Class 底下掛的往往是 `over` 片段與材質綁定，被當成實體內容處理將產生難以歸因的錯誤。
>
> `class` 的抽象性在 Flatten 後依然保留，因此發布包中的 Class 不會汙染下游。

### 5. 穿透 Instanceable：`inherit` 是唯一的覆寫途徑

設為 `instanceable = true` 的 Prim，其 descendant 在命名空間中是 **Instance Proxy**——**唯讀，無法被 `over`**：

```python
stage.OverridePrim("/World/ChairA/Model/Frame")   # 拋出 _ValidateEditing 錯誤
```

但 `inherit` 的 Class 意見是**原型（Prototype）組合的一部分**，而非施加於實例代理的外部覆寫。因此它**穿透 Instanceable 生效**，且精準落在指定路徑上：

```usda
class "__CLASS__"
{
    class "wooden_props"
    {
        over "Model"
        {
            over "Frame"
            {
                token visibility = "invisible"   # 全場 wooden_props 的木框隱形
            }
        }
    }
}
```

實測結果：所有繼承 `wooden_props` 的椅子，其 `Model/Frame` 皆轉為 `invisible`，而同層的 `Model/Seat` 完全不受影響——即使這些椅子全都是 Instanceable。

> [!IMPORTANT]
> **這是 Instanceable Asset 唯一的內部覆寫途徑**
> 下游若需要調整 Instanceable Asset 的內部結構，唯一的合法手段就是編輯它所繼承的 Class。放棄 `instanceable` 以換取可覆寫性，代價是喪失整個 Asset 的實例化記憶體效益——絕大多數情境下，改用 Class 廣播才是正解。

> [!CAUTION]
> **標籤不是免費的：攜帶意見的標籤會使原型分裂**
> 原型的共用與否取決於實例的組合結構，`inherits` 清單即為其中一部分。實測三把 Instanceable 椅子：
>
> | 情境 | 原型數 |
> | :--- | :---: |
> | 三把標籤完全相同 | 1 |
> | 其中一把多掛一個**空的**標籤 | 1 |
> | 其中一把多掛一個**帶有意見的**標籤 | **2** |
>
> 換言之，標籤在尚未攜帶意見時幾乎無成本；一旦某個 Class 被寫入實質意見，掛載該標籤的實例即與其餘實例分屬不同原型。**實例化的記憶體效益會按實際生效的標籤組合數切分**——這是廣播式治理的真實代價，大規模場景中規劃標籤體系時必須納入考量。


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
   # Expression Variable 必須以反引號包裹字串運算式，否則不會展開
   asset_usd_path = '`"${PROJECT_ROOT}/publish/assets/props/Chair/asset_latest.usda"`'
   
   # 1. 建立 Prim 並指派 kind
   prim = stage.DefinePrim(prim_path, "Xform")
   Usd.ModelAPI(prim).SetKind(Kind.Tokens.component)
   
   # 2. 注入 Payload
   prim.GetPayloads().AddPayload(asset_usd_path, Sdf.Path("/ROOT"))
   
   # 3. 設置 Instanceable
   prim.SetInstanceable(True)
   
   # 4. 注入 Class Inherits
   inherits = prim.GetInherits()
   inherits.AddInherit(Sdf.Path("/__CLASS__/Chair"))
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
| **實例化** | 支援 `instanceable = true`，排除逐實例覆寫但不排除 Class 廣播 | 達成 Stage 原生記憶體共享；需逐顆覆寫者不得勾選，需整類覆寫者改走 Class |
| **繼承標籤** | 預設 `/__CLASS__/{name}`，允許自訂追加 | 達成廣播式屬性覆寫與多重語意標籤管理 |
| **廣播寫法** | 意見一律往下走至目標 Prim，嚴禁寫在 Class 根上 | 保留 Asset 自身材質層次；須留意綁定優先序因此反轉 |
| **Class 根宣告** | `/__CLASS__` 一律以 `class` 指示符建立，由 Pipeline 預設產生 | 抽象 Prim 不被預設 `Traverse()` 走訪，不汙染渲染、匯出與統計 |

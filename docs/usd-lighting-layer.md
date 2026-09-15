# USD：Lighting Layer 燈光層架構與最終仲裁權

在鏡頭的四大部門圖層中，**Lighting Layer（`lighting.usd`）** 位於 `/ROOT/Lighting`，是 `subLayers` 堆疊中權重最強的一層。

其餘三個部門各自面對「Asset 化、發布單元、巨量快取」的問題，Lighting 則不同——它幾乎不產生體積，卻**握有全場最終覆寫權**。因此本篇的重心不在資料管理，而在**權限的行使與節制**，以及 Lighting 獨有的兩項機制：**Light Linking** 與 **Light Rig 的跨鏡頭複用**。

---

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **權限最強，但行使必須節制**：Lighting 能蓋掉任何東西，不代表任何東西都該在 Lighting 蓋。**能在上游修正的，一律退回上游**——否則上游的錯誤將永遠不被修正，且每顆鏡頭都要重複修補一次。
> 2. **Light Linking 以 `UsdCollectionAPI` 實作**：光源上的 `collection:lightLink` 與 `collection:shadowLink` 兩組 collection，分別控制「照亮誰」與「為誰投射陰影」。
> 3. **排除優於列舉**：連結預設為「照亮全部」。實務上一律採 `includeRoot = true` 搭配 `excludes`，**不要逐一列舉要照亮的物件**——新增的 Asset 會自動被納入，而非默默漏掉。
> 4. **Light Rig 跨鏡頭複用**：Sequence 級的共用打光應獨立發布為 **Pure USD 單元**，由各鏡頭的 `lighting_base` 引用，鏡頭專屬調整走 `lighting_overrides`。
> 5. **HDRI 等貼圖路徑不適用 Expression Variable**：`inputs:texture:file` 為 asset 型屬性值，須由 Output Processor 於輸出時寫入已解析路徑。
> 6. **渲染設定位於 `/Render`**：由本層一併產出，但並非其中每一項都屬 Lighting 職權。詳見 [Shot Layers 篇 §4](usd-shot-layers.md)。

---

## 1. 最強層的行使準則

`usd-shot-layers.md` 已詳述 Lighting 具備跨部門覆寫一切的能力。但**能力與應然是兩回事**——這一節規範的是「什麼該在 Lighting 修、什麼不該」。

> [!CAUTION]
> **Pipeline 鐵律：能在上游修正的，一律退回上游**
> 「反正 Lighting 蓋得掉」是整套覆寫機制最危險的誤用。若把上游的錯誤一律在 Lighting 就地修補，將同時付出三項代價：
> 1. **錯誤永遠不會被修正**：Asset 的破面、錯誤的材質、跑掉的 Transform 依然留在發布庫中，下一顆鏡頭、下一部片仍會踩到。
> 2. **修補成本隨鏡頭數線性成長**：上游改一次即可解決的問題，變成每顆鏡頭都要修一次；而一套 Sequence 動輒數十顆鏡頭。
> 3. **覆寫層失去可讀性**：`lighting_overrides` 中混雜著「真正的藝術決策」與「替上游擦屁股」，日後無人能分辨哪些可以安全移除。

### 判準

| 情形 | 處置 |
| :--- | :--- |
| Asset 本身有缺陷（破面、UV 錯誤、材質參數失當） | **退回上游修正**，Lighting 不得就地補 |
| 跨鏡頭一致的問題（該 Asset 在所有鏡頭都太亮） | **退回上游**，或提升至 Sequence 級的 Light Rig 處理 |
| 本鏡頭專屬的藝術決策（這顆鏡頭的主角要更亮一點） | **Lighting 覆寫**，這正是覆寫機制的用途 |
| 本鏡頭專屬的穿幫（這個角度才會看到的遮擋物） | **Lighting 覆寫** |
| 急件、上游已收工、無法等待 | **Lighting 暫時覆寫，並同時回報上游**——修補是暫時的，不是結案 |

> [!TIP]
> **判準其實只有一句：這個修補在別顆鏡頭也需要嗎？**
> 答案為「是」，就代表問題在上游；答案為「否」，才是 Lighting 的正當職權。
>
> 最後一列的急件情形無可避免，但**必須留下回報記錄**，否則它與「就地修補」在結果上毫無差別。此原則與 [QC 的豁免機制](usd-pipeline-validation.md)一致：允許例外，但例外必須留痕。

---

## 2. Light Linking：控制「誰被照亮」

Light Linking 是 Lighting 獨有、且在實務中使用頻率極高的機制——主角要專屬的眼神光、體積特效不該被 Key Light 打亮、地面不該接收角色的陰影。

OpenUSD 以 **`UsdCollectionAPI`** 實作，每盞光源上有兩組獨立的 collection：

| Collection | 控制 |
| :--- | :--- |
| `collection:lightLink` | 這盞光**照亮**哪些幾何 |
| `collection:shadowLink` | 這盞光**為哪些幾何投射陰影** |

兩者**完全獨立**——可以讓一盞光照亮角色卻不產生陰影，或反之。

### 1. 實際寫法

```usda
def RectLight "KeyLight" (
    prepend apiSchemas = ["CollectionAPI:lightLink", "CollectionAPI:shadowLink"]
)
{
    float inputs:intensity = 5000.0

    # 照亮全場，但排除特效體積（避免煙霧被主光打爆）
    uniform bool collection:lightLink:includeRoot = 1
    uniform token collection:lightLink:expansionRule = "expandPrims"
    prepend rel collection:lightLink:excludes = </ROOT/FX/explosion_hero>

    # 為全場投射陰影，但主角除外（避免自身陰影破壞臉部打光）
    uniform bool collection:shadowLink:includeRoot = 1
    prepend rel collection:shadowLink:excludes = </ROOT/Anim/Characters/Hero>
}
```

### 2. 一律採「排除」而非「列舉」

> [!CAUTION]
> **嚴禁以 `includes` 逐一列舉要照亮的物件**
> 連結的預設行為是「**照亮全部**」。兩種寫法的差異在於**新增 Asset 時會發生什麼**：
>
> | 寫法 | 新增一顆 Asset 後 |
> | :--- | :--- |
> | `includeRoot = 1` + `excludes` | **自動被照亮**——符合預期 |
> | 逐一 `includes` | **默默不被照亮**——沒有任何警告 |
>
> Layout 在鏡頭中段補進一張桌子是日常操作。若燈光採列舉式連結，那張桌子會在畫面中**全黑出現**，而燈光師只會覺得「怎麼會這樣」——因為沒有任何一處報錯。
>
> 因此規範為：**一律 `includeRoot = true` 搭配 `excludes`**，讓「未被明確排除者恆被照亮」成為不變量。

> [!WARNING]
> **渲染器對 Light Linking 的支援程度需於部署環境驗證**
> `UsdCollectionAPI` 的語意由 OpenUSD 定義，但**實際生效與否取決於渲染器的 Hydra Delegate 實作**。各渲染器對 `expansionRule`、巢狀 collection 與 instance/`PointInstancer` 原型的處理不盡相同。
>
> 導入前應以實際使用的渲染器驗證下列情境：標準 Prim、`instanceable` 實例、`PointInstancer` 原型。**尤其後兩者，連結行為往往與直覺不同**。

### 3. 以單元自述的 collection 作為連結目標

上方範例的 `excludes` 直接寫死 `</ROOT/FX/explosion_hero>`——燈光層因此必須知道該元素被掛在哪、內部長什麼樣。更穩健的作法是**由單元自己宣告 collection**，燈光端指向語意單位而非手打路徑。

發布單元得在自身總裝層的 `/ROOT` 宣告 collection（此為 [`/ROOT` 白名單](usd-publish-packaging.md)的唯一項目）：

```usda
# fx/elements/explosion_hero/v002/element.usd
def Xform "ROOT" (
    kind = "component"
    prepend apiSchemas = ["CollectionAPI:fxVolumes"]
)
{
    uniform token collection:fxVolumes:expansionRule = "expandPrims"
    prepend rel collection:fxVolumes:includes = </ROOT>
}
```

經 Reference 嫁接後，**collection 的 target 會自動重映射至掛載位置**——`/ROOT` 變成 `/ROOT/FX/explosion_hero`，成員查詢隨之正確。單元內部改結構時由單元自己維護 collection，燈光端不受影響。

> [!CAUTION]
> **但 `excludes` 不支援指向另一個 collection**
> `collection:lightLink:excludes` 只能指向 **Prim 路徑**；指向另一個 collection（如 `…/explosion_hero.collection:fxVolumes`）**不會產生任何作用**——USD 不報錯，該元素照樣被照亮。
>
> 因此單元自述的 collection **無法直接串接為連結目標**，必須由工具接手：
>
> ```text
> FX 元素包     →  於自身 /ROOT 宣告 collection:fxVolumes（單元自述）
>       ↓ Reference
> 鏡頭合成      →  collection 自動重映射至 /ROOT/FX/explosion_hero
>       ↓
> Lighting 工具 →  讀取該 collection、展開為 Prim 路徑清單
>       ↓
> lighting.usd  →  將展開結果寫入 collection:lightLink:excludes
> ```
>
> 解耦效果仍然達成——**燈光師選的是「那顆 FX 元素」這個語意單位，而非手打路徑**；代價是多一道工具展開，而非純宣告式串接。

> [!NOTE]
> **Master 圖層無須宣告 collection**
> collection 屬於**知道自己內容的那一方**。`shot.usd` 僅是把各單元疊起來，沒有任何自述需求；各單元自己帶來的 collection 已經足夠。

### 4. 與 `PointInstancer` 的互動

承 [Set Dressing 篇的覆寫契約](usd-environment-setdressing.md)：`PointInstancer` 的個別實例不是 Prim，**無法被單獨連結或排除**。

連結只能施加於整顆 `PointInstancer`，或其**原型 Prim**。若需要「森林中只有這幾棵樹不被照亮」，唯一的作法是把它們拆成獨立的 Instancer 或獨立 Prim——這正是 Set Dressing 篇所述「需要下游逐顆覆寫者不應以 `PointInstancer` 承載」的又一具體理由。

---

## 3. Light Rig 的跨鏡頭複用

同一 Sequence 的鏡頭通常共用一套基礎打光（同一場景、同一時刻、同一光源配置）。若每顆鏡頭各自從零打光，不僅重複勞動，更會導致**同一場戲的鏡頭之間光感不一致**。

### 1. 發布為 Pure USD 單元

Light Rig 沒有幾何、沒有快取，內容純粹是光源與其參數——正符合 [Pure USD 單元](usd-publish-packaging.md)的定位：

```text
/projects/show_A/publish/shots/sq01/lightrig_interior/   <-- 【Pure USD 單元目錄】
├── lightrig_interior_latest.usda
├── v001/
│   └── lightrig_interior.usd
└── v002/
    └── lightrig_interior.usd
```

### 2. 由各鏡頭的 `lighting_base` 引用

```usda
# sq01/sh010/lighting/v003/layers/lighting_base.usd
over "ROOT"
{
    def Scope "Lighting" ( kind = "group" )
    {
        # 引用 Sequence 級共用 Light Rig
        def Scope "Rig" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/lightrig_interior/lightrig_interior_latest.usda"`@</ROOT/Lighting>
        ) {}

        # 本鏡頭專屬的補光
        def RectLight "ShotFill" { /* ... */ }
    }
}
```

### 3. 鏡頭專屬調整走 `lighting_overrides`

> [!IMPORTANT]
> **嚴禁為了單一鏡頭而修改共用 Light Rig**
> Light Rig 一經引用即為多顆鏡頭共有。若為了 `sh010` 的需求而調整 Rig 的參數，**其餘所有引用它的鏡頭都會同時改變**——且改動者多半不會察覺。
>
> 鏡頭專屬的調整一律寫在該鏡頭的 `lighting_overrides`，以 `over` 覆寫 Rig 帶入的光源：
>
> ```usda
> # lighting_overrides/sh010_key_tweak.usd
> over "ROOT" { over "Lighting" { over "Rig" {
>     over "KeyLight"
>     {
>         float inputs:intensity = 6200.0    # 本鏡頭主角較遠，補強主光
>     }
> } } }
> ```
>
> 唯有當某項調整**在該 Sequence 的所有鏡頭都需要**時，才回頭推進 Light Rig 的版本——判準與 §1 的「這個修補在別顆鏡頭也需要嗎」完全相同。

---

## 4. HDRI 與貼圖路徑治理

`DomeLight` 的環境貼圖是 Lighting 唯一會引用的外部二進位 Asset。

> [!CAUTION]
> **貼圖路徑不適用 Stage Expression Variable**
> `inputs:texture:file` 是 **asset 型屬性值**，而非組合弧的 asset path。Expression Variable 的展開發生於合成階段，**不涵蓋一般屬性值**（詳見 [發布封裝篇 §5](usd-publish-packaging.md)）。
>
> 因此 HDRI 路徑**不得**寫成運算式形式，而應由 **Output Processor 於輸出時寫入已解析的絕對路徑**：

```usda
def DomeLight "SkyDome"
{
    # 由 Output Processor 於輸出時寫入已解析路徑，不使用 Expression Variable
    asset inputs:texture:file = @/projects/show_A/assets/hdri/sunset_4k.exr@
    float inputs:intensity = 1.2
}
```

> [!TIP]
> **專案遷移時的因應**
> 既然無法倚賴 Expression Variable 一鍵切換，HDRI 路徑在專案搬遷時就需要另外的機制。兩種可行作法：
> - **交由 Asset Resolver 的 search path 處理**：路徑寫成相對於 HDRI 庫根目錄的形式，由 Resolver 負責定位。
> - **遷移時以腳本重寫**：由於 HDRI 引用數量遠少於 Asset 引用（通常每顆鏡頭僅一至兩處），批次重寫的成本可以接受。
>
> 兩者擇一即可，但**必須擇一並寫入專案規範**——否則專案一搬遷，所有鏡頭的環境光就會靜默壞鏈。

---

## 5. 圖層內部結構

Lighting 與其餘部門同樣採用 `Master → Overrides → Base` 三層結構（詳見 [Shot Layers 篇](usd-shot-layers.md)），但其 `overrides` 容器的使用強度遠高於其他部門——因為跨部門的稀疏覆寫幾乎都發生在這裡。

```text
lighting.usd (Master)
├── lighting_overrides.usd (容器，較強)
│    ├── sh010_key_tweak.usd          <-- 鏡頭專屬打光調整
│    ├── char_eye_highlight_fix.usd   <-- 角色眼神光補強
│    └── bg_prop_prune.usd            <-- 背景穿幫物件處理
└── lighting_base.usd (較弱)
     ├── /ROOT/Lighting/Rig           <-- 引用共用 Light Rig
     └── /ROOT/Lighting/ShotFill      <-- 本鏡頭專屬光源
     └── /Render                      <-- 渲染設定（見 Shot Layers 篇 §4）
```

> [!TIP]
> **一個修補檔只做一件事**
> `lighting_overrides` 底下的檔案應維持**單一意圖**——「補強眼神光」與「隱藏穿幫道具」不應混在同一個檔案裡。如此一來，日後要移除某項修補時，只需將該檔案自 `subLayers` 清單移除並發布新版容器，不必擔心誤刪其他意見。
>
> 此作法亦使多位燈光師得以完全平行作業：各自維護自己的修補檔，僅在容器層註冊，無檔案鎖爭奪。

---

## 6. Lighting 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

Lighting 交付發布時，同樣適用全 Pipeline 封裝標準：

1. **目錄即包裝單元（同構內部結構）**：以任務發布目錄（如 `publish/shots/sq01/sh010/lighting/`）為獨立封裝單位，內部結構固定為 `lighting_latest.usda`、各版次 `v###/lighting.usd`、子圖層（`layers/lighting_base.usd`、`layers/lighting_overrides.usd`）與各修補檔，檔名維持統一同構。
2. **`/ROOT` 鐵律**：`lighting.usd` 為部門輸出，對 `/ROOT` 僅得使用 `over "ROOT"` 作為純命名空間容器，不得寫入任何屬性或元數據。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：`lighting.usd` 堆疊包內的 base 與 overrides 一律使用相對路徑（`@./...@`）。
   - **包外引用**：引用共用 Light Rig 等外部發布單元時，輸出時由 Solaris Output Processor 自動改寫為 ``@`"${PROJECT_ROOT}/..."`@``。**惟 HDRI 等 asset 型屬性值不適用**，須寫入已解析的絕對路徑（見 §4）。

---

## 7. Pipeline 規範對照總表

| 維度 | 規範 |
| :--- | :--- |
| **權限行使** | 能在上游修正者一律退回上游；判準為「這個修補在別顆鏡頭也需要嗎」 |
| **急件例外** | 允許暫時覆寫，但**必須留下回報記錄**，修補是暫時的而非結案 |
| **Light Linking** | 以 `collection:lightLink` 與 `collection:shadowLink` 實作，兩者完全獨立 |
| **連結寫法** | **一律 `includeRoot = true` 搭配 `excludes`**，嚴禁逐一列舉 `includes` |
| **`PointInstancer`** | 個別實例無法單獨連結；只能施加於整顆 Instancer 或其原型 |
| **Light Rig** | Sequence 級共用打光發布為 Pure USD 單元，由各鏡頭 `lighting_base` 引用 |
| **鏡頭專屬調整** | 一律走 `lighting_overrides`，**嚴禁為單一鏡頭修改共用 Rig** |
| **HDRI 路徑** | 不適用 Expression Variable，須寫入已解析絕對路徑；遷移機制須另行擇定 |
| **修補檔粒度** | 一個檔案只做一件事，確保可獨立移除 |
| **渲染設定** | 由本層一併產出於 `/Render`，但解析度與影格範圍由 Pipeline 注入 |

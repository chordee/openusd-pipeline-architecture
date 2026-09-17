# USD：Animation Layer 動態架構設計

在鏡頭（Shot）的 USD 堆疊中，**Animation Layer（`anim.usd`）** 位於 `/ROOT/Anim`，權重高於 Environment、低於 FX 與 Lighting。

雖然 Animation Layer 呈現了整個鏡頭最複雜生動的表演（角色走動、表情、道具互動、鏡頭運動），但在工業級 USD Pipeline 中，**Animation Layer 實際輸出的硬碟佔用量極小（通常僅數 MB）**。這得益於 USD 將動態資料與實體幾何徹底解耦的設計。

> [!IMPORTANT]
> **30 秒核心架構觀念**
> 1. **兩大元素分類**：
>    - **骨架角色動畫（Skeletal Character Animation）**：發布為 `charAnim` 單元。
>    - **幾何 Transform 動畫（Rigid Transform / Prop Animation）**：發布為 `propAnim` 單元。
> 2. **所有動畫單元一律靜態／時序二分**：這是全篇貫穿的通則，兩類元素只是同一條軸上的兩個實例。
>
>    | 單元 | 靜態 sub | 時序 sub |
>    | :--- | :--- | :--- |
>    | `charAnim` | `skel`（關節拓樸、bind／rest、`BlendShape` 本體） | `anim`（joint transforms、`blendShapeWeights`） |
>    | `propAnim` | `geo`（拓樸、UV、靜態點位） | `xform`（`xformOp` 時間樣本、變形點位） |
>
>    靜態資料體積大而變動少，時序資料才是動畫師反覆迭代的對象——分開後重發動畫無須重寫靜態層。
> 3. **極致輕量的本質**：
>    - 幾何網格（Mesh）早已在 **Asset 階段**發佈完畢，剛體動畫絕不重複導出頂點快取。
>    - 骨架拓樸早已在 **Rig 階段**發佈完畢。
>    - Animator 僅需輸出數據量極小的 **Joint 時序旋轉/平移陣列** 或 **Transform TimeSamples**。

---

## 1. 元素類型一：骨架角色動畫（Skeletal Animation）

> 📖 關於 USD Skel Schema 之底層語法與陣列規範，請參見技術手冊：[USD Skel 骨架動畫設定指南](usd-skel-guide.md)。

每個帶有骨架變形的角色動畫，在 USD Pipeline 中均被嚴格拆分為三個獨立單元：

```text
【角色動畫三合一組裝架構】

           ┌── 1. Geometry ──► 由【Model / Lookdev】提供 (Mesh + 材質，靜態不變)
           │                    ※ 已封裝於綁定角色內
SkelRoot ──┼── 2. Skel ──────► 由【Rig 環節】提供 (骨架拓樸、BlendShape、蒙皮權重)
           │                    ※ 已封裝於綁定角色內
           └── 3. AnimData ──► 由【Animator 環節】輸出 (Joint 時序動態 + BlendShape 權重)
                                ※ 本層唯一產出
```

### 三大組成單元職責

| 組成單元 | 來源環節 | 內容特性 | 硬碟負擔 |
| :--- | :--- | :--- | :---: |
| **`Geometry`** | **Model / Lookdev 階段** | 角色幾何體、UV 與材質。以幾何材質 Asset 的形式發布，一次發佈、全片共用。 | 0 (純 Reference) |
| **`Skel` (Skeleton)** | **Rig 階段** | 關節拓樸、`bindTransforms`、`restTransforms` 與 `BlendShape` 本體；並以 `over` 將蒙皮權重寫回 `Geometry` 的 Mesh。無動畫時間樣本。 | 0 (純 Reference) |
| **`AnimData` (SkelAnimation)** | **Animation 階段** | **Animator 唯一輸出的檔案**。僅含各 Joint 隨時間變化的旋轉／位移／縮放陣列，以及 `blendShapeWeights`。 | **極小** (數十 KB ~ 數 MB) |

> [!IMPORTANT]
> **前兩者已於角色 Asset 階段組裝完畢，動畫層只交付第三者**
> `Geometry` 與 `Skel` 皆封裝在**綁定角色**（`char_latest.usda`）之內，其 `/ROOT` 即為 `SkelRoot`。動畫層只需**單次引用**該綁定角色，再疊上自己輸出的 `SkelAnimation` 即可——無須、也不應分頭引用幾何與骨架。
>
> 完整的角色 Asset 結構詳見 [Asset Layer 篇 §7 角色 Asset 結構](usd-asset-layer.md#7-角色-asset-結構character-asset)。

### 骨架角色動畫的兩層 USDA

這裡有**兩個不同的東西**，先前常被混為一談：**charAnim 單元自身**，以及**部門 Master 的 `base` 如何嫁接它**。

#### 一、charAnim 單元自身（`charAnim/<unit>/v###/charAnim.usd`）

與其他所有發布單元同構：**以 `/ROOT` 為自身的根，完全不知道自己會被掛到哪裡**。

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

# 以 Reference 嫁接綁定角色，一併帶入 Geometry（幾何＋材質）與 Skel（骨架）。
# /ROOT 的型別 SkelRoot 隨 Reference 帶入，此處無須重複宣告。
def "ROOT" (
    prepend references = @`"${PROJECT_ROOT}/publish/rig/Hero_rig/char_latest.usda"`@</ROOT>
)
{
    # 動畫師本鏡頭唯一實際輸出的動態資料
    def SkelAnimation "AnimData"
    {
        uniform token[] joints = ["Hips", "Hips/Spine", "Hips/Spine/Chest", ...]

        quatf[] rotations.timeSamples = {
            1: [(1, 0, 0, 0), (0.7, 0, 0.7, 0), ...],
            2: [(0.99, 0.01, 0, 0), (0.69, 0.02, 0.7, 0), ...]
        }
        float3[] translations.timeSamples = {
            1: [(0, 1.0, 0), (0, 0.15, 0), ...],
            2: [(0, 1.01, 0.005), (0, 0.15, 0), ...]
        }

        # BlendShape 權重亦由動畫層輸出（形狀本體在綁定角色的 Skel 內）
        uniform token[] blendShapes = ["smile"]
        float[] blendShapeWeights.timeSamples = {
            1: [0.0],
            2: [0.35]
        }
    }

    # 綁定關係下探至 Skel，不寫在 /ROOT 上。
    # skel:skeleton 已由綁定角色寫在各 Mesh 上，此處只需掛上動畫來源。
    over "Skel" (
        prepend apiSchemas = ["SkelBindingAPI"]
    )
    {
        rel skel:animationSource = </ROOT/AnimData>
    }
}
```

> [!IMPORTANT]
> **`animationSource` 為何下探至 `Skel` 而非寫在 `/ROOT`**
> `skel:*` 屬於 `SkelBindingAPI`，寫在 `/ROOT` 上會違反 [`/ROOT` 鐵律](usd-publish-packaging.md)——該處白名單僅含 `collection`。下探至 `Skel` 既合規，效果亦相同（綁定關係本就是命名空間繼承的，寫在 Skeleton 自身是最直接的位置）。
>
> 單元的 `/ROOT` 因此**除了 Reference 之外零寫入**：無屬性、無 `kind`、無 `variantSets`、無 `apiSchemas`。

#### 二、部門 Master 的 `base` 如何嫁接（`anim_base.usd`）

單元的落點由**消費端**決定，與 FX Element、Prop、Set 完全同構——一律 Reference 並重映射 `</ROOT>`：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    # 部門分支由本部門定義；Prim 名即單元名，無須轉換
    def Scope "Anim" ( kind = "group" )
    {
        def "BoyWalking" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/anim/charAnim/BoyWalking/charAnim_latest.usda"`@</ROOT>
        ) {}

        def "GirlRunning" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/anim/charAnim/GirlRunning/charAnim_latest.usda"`@</ROOT>
        ) {}
    }
}
```

合成後，單元內部的所有路徑隨 Reference 自動重映射：

```text
/ROOT/Anim/BoyWalking            (SkelRoot，型別來自綁定角色)
├── Geometry/                    <-- 幾何＋材質，來自幾何材質 Asset
├── Skel                         <-- 骨架，來自綁定角色；此處掛上 animationSource
└── AnimData                     <-- 本單元唯一實際輸出
```

單元內寫的 `</ROOT/AnimData>` 在此解析為 `/ROOT/Anim/BoyWalking/AnimData`——**單元始終無須知悉自己的掛載位置**。


## 2. 元素類型二：幾何 Transform 動畫（Rigid / Prop Animation）

第二類是剛體或無骨架物件的空間動態，常見於：
- 道具動態（手持武器、咖啡杯、手機）
- 載具動態（汽車、飛機軌跡）
- 鏡頭動態（`ShotCam` 平移、旋轉、焦距變化）

### 運作模式：引用 Asset＋覆寫時序 Transform
動畫師在鏡頭中**引用（Reference）已發佈的 Asset**，只在其身上輸出隨影格變化的空間 Transform 數據。

以下呈現的是**部門 Master 的 `base` 合成後的樣貌**（與 §1 的第二段同一層級）。若該內容獨立成發布單元，其自身層一律比照 [§1 的第一段](#一charanim-單元自身charanimunitvcharanimusd)：以 `/ROOT` 為根、不知悉掛載位置，由 `base` 以 Reference 決定落點。

```usda
# anim_base.usd 合成後的樣貌
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim" ( kind = "group" )
    {
        # 1. 鏡頭攝影機動態
        def Scope "Cameras" ( kind = "group" )
        {
            def Camera "ShotCam"
            {
                # 焦距與光圈的單位恆為「scene unit 的十分之一」；本專案為公尺制，
                # 故十分之一即 10cm：35mm = 0.035m = 0.35    50mm = 0.05m = 0.5
                float2 clippingRange = (0.01, 10000)
                float horizontalAperture = 0.20955        # Academy 光圈 20.955mm
                float focalLength.timeSamples = {
                    1: 0.35,
                    50: 0.5
                }
                float focusDistance.timeSamples = {
                    1: 5.0,                               # 對焦距離為 world unit（公尺）
                    50: 3.2
                }
                double3 xformOp:translate.timeSamples = {
                    1: (0, 1.5, 3),
                    50: (0.2, 1.55, 2.5)
                }
                float3 xformOp:rotateXYZ.timeSamples = {
                    1: (-10, 5, 0),
                    50: (-8, 12, 0)
                }
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
            }
        }

        # 2. 道具剛體動畫 (引用已發佈 Asset，只輸出矩陣時序)
        def Scope "Props" ( kind = "group" )
        {
            def Xform "HeroGun" (
                references = @`"${PROJECT_ROOT}/publish/assets/props/weapons/Blaster/asset_latest.usda"`@</ROOT>
            )
            {
                double3 xformOp:translate.timeSamples = {
                    1: (0.152, 1.105, 0.45),
                    2: (0.158, 1.12, 0.462)
                }
                float3 xformOp:rotateXYZ.timeSamples = {
                    1: (0, 45, 10),
                    2: (2, 48, 12)
                }
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
            }
        }
    }
}
```

### `propAnim` 單元的兩個 sub

與 `charAnim` 同構，`propAnim` 亦為靜態／時序二分：

```text
anim/propAnim/<unit>/
├── propAnim_latest.usda
├── v001/
│   └── propAnim.usd          <-- 總裝：以 /ROOT 為根，不知悉掛載位置
├── geo/                      <-- 【靜態】拓樸、UV、靜態點位；無 latest
│   └── v001/geo.usd
└── xform/                    <-- 【時序】xformOp 時間樣本；無 latest
    └── v001/xform.usd
```

**絕大多數道具不需要 `geo`**。剛體道具的幾何早已在 Asset 階段發布，單元只需 Reference 該 Asset 並交付 `xform`——這正是前一段範例的情形，也是 `propAnim` 輕量的來源。

`geo` 存在，是為了**幾何無法來自靜態 Asset** 的情形：

| 情境 | 為何需要 `geo` |
| :--- | :--- |
| 變形道具（旗幟、布幔、擠壓變形的球） | 形變無法以 `xformOp` 表達，靜態 Asset 給不出每幀的形狀 |
| 動畫階段才產生的臨時幾何 | 尚未、也不會進入 Asset 流程 |
| 拓樸與已發布 Asset 不同的替身 | 無法以覆寫嫁接回原 Asset |

> [!IMPORTANT]
> **變形道具的拆法：靜態拓樸進 `geo`，逐幀點位進 `xform`**
> `Mesh` 的拓樸（`faceVertexCounts`、`faceVertexIndices`）、UV 與 bind 姿態的 `points` 屬於**靜態**，歸 `geo`；隨時間變化的 `points` 時間樣本屬於**時序**，與 `xformOp` 同歸 `xform`。
>
> 此拆法要求**拓樸在整段時間內固定不變**（fixed topology）。拓樸若逐幀改變，兩側的對應關係即告瓦解，該內容不屬於動畫單元，應改由 [FX Element](usd-fx-layer.md) 以 Value Clips 承載。


---

## 3. 點位快取的正確定位：手段選型，而非好壞之分

傳統流程的動畫檔常高達數十 GB，USD 卻能壓在數 MB——差別**不在於點位快取本身是落後手段**，而在於是否被誤用在能以更廉價方式表達的內容上。

以角色為例，對照的是同一份表演的兩種表達：

| 比較維度 | 全幾何點位快取 | 骨架時序（`charAnim`） |
| :--- | :--- | :--- |
| **儲存方式** | 每一格都將角色 50 萬頂點的 `(x, y, z)` 座標完整烘焙寫入磁碟。 | 幾何留在 Asset；每格僅儲存 80 個骨架 Joint 的旋轉向量。 |
| **磁碟佔用 (100 格)** | 約 **5 GB ~ 15 GB**。 | 約 **2 MB ~ 8 MB**（節省 99% 以上）。 |
| **修改與重新發佈** | 稍微修改動作就必須重新烘焙巨型快取，網路傳輸極慢。 | Animator 秒級輸出幾 MB 的動態檔案，發佈與審閱無負擔。 |
| **下游使用靈活性** | 幾何已死鎖，下游難以拆解骨架或替換 Mesh 拓樸。 | 下游可隨時替換高低模（Model Variant），骨架動態完全通用。 |

這張表要說的是：**凡能以骨架或 `xformOp` 表達者，烘點位是純粹的浪費**——上表每一列都是代價，換不到任何東西。

但反過來也成立：**真正的形變無法以骨架或 `xformOp` 表達**。旗幟在風中翻捲、布幔垂墜、球體撞擊時的擠壓，這些內容沒有等價的廉價表達，逐幀點位就是它唯一的載體。此時烘點位不是退步，而是唯一正確的手段。

### 選型判準

| 內容 | 手段 | 落點 |
| :--- | :--- | :--- |
| 位置／旋轉／縮放變化 | `xformOp` 時間樣本 | `propAnim` 的 `xform` |
| 關節驅動的角色變形 | `SkelAnimation` | `charAnim` 的 `anim` |
| 表情等具名形狀混合 | `blendShapeWeights` | 同上 |
| **固定拓樸的真形變** | **逐幀 `points`** | **`propAnim` 的 `xform`** |
| 逐幀拓樸改變（碎裂、流體） | Value Clips | [FX Element](usd-fx-layer.md) |

判準只有一句：**先問這個變化能不能以更廉價的方式表達**；能，就不得烘點位；不能，就正當使用，並依靜態／時序拆入對應的 sub。

---

## 4. Pipeline 規範總結

1. **點位快取限定用於真形變**：凡能以 `xformOp`、`SkelAnimation` 或 `blendShapeWeights` 表達的變化，**一律不得烘焙 Point Cache**。真正的形變（固定拓樸的布料、旗幟、擠壓）則正當使用，並拆入 `propAnim` 的 `geo`／`xform` 兩個 sub；拓樸逐幀改變者不屬動畫單元，改由 FX Element 承載。判準詳見 §3。
2. **統一 SkelRoot 邊界**：所有骨架角色必須包覆在 `SkelRoot` 節點內，確保即時預覽（Hydra）與離線渲染時能正確解算 Skinning。
3. **`SkelBindingAPI` 必須顯式套用**：`skel:skeleton`、`skel:animationSource`、`skel:joints`、`primvars:skel:jointIndices` 等全系列屬性皆隸屬 `SkelBindingAPI` 這個 **Applied API Schema**。凡是承載這些屬性的 Prim（`SkelRoot`、`Skeleton`、被 skin 的 `Mesh`），都必須以 `prepend apiSchemas = ["SkelBindingAPI"]` 套用；**只寫屬性而未套用 Schema 是無效綁定**，Hydra 不會解算 Skinning 且 `usdchecker` 會報錯。發布前 QC 應列為必檢項。詳見：[USD Skel 骨架動畫設定指南](usd-skel-guide.md)。
4. **時序資料集中**：攝影機與道具的動態屬性統一宣告為 `xformOp` 時間樣本，確保被 Lighting 或 FX 圖層引用時具備乾淨的時序插值（Interpolation）。

---

## 5. Animation 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

動畫部門交付發布時，同樣適用全 Pipeline 封裝標準：
1. **目錄即包裝單元（同構內部結構）**：`charAnim/` 為**分類目錄**，其下每個角色動畫單元（如 `charAnim/BoyWalking/`）各自為獨立封裝單位、各自進版。單元內部結構固定為 `charAnim_latest.usda`、各版次 `v###/charAnim.usd`，以及兩個沿用 sub 物件規則、均不設 `latest` 的子單元——`skel/v###/skel.usd` 承載**靜態**資料（`Skeleton` 拓樸、`BlendShape` 本體、控制器階層），`anim/v###/anim.usd` 承載**時序**取樣（joint、`xformOp`、`blendShapeWeights` 動畫）。檔名維持統一同構，嚴禁摻雜具體角色名稱。
2. **Solaris Implicit Layer 禁錮**：若由 Solaris 輸出，所有導出的隱式圖層必須限制在目標目錄或其子目錄內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：`anim.usd` 堆疊包內的骨架動畫層與鏡頭層一律使用相對路徑（`@./...@`）。
   - **包外引用**：動畫層引用外部角色幾何或道具 Asset，輸出時由 Solaris Output Processor 自動改寫為 ``@`"${PROJECT_ROOT}/..."`@``，確保專案遷移或交接客戶時可一鍵切換。

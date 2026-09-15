# USD：Shot Layers 鏡頭分層與 Overrides 覆寫架構

在 OpenUSD 的鏡頭級生產中，**Shot Layer Stacking（鏡頭圖層堆疊）** 與 **Department Overrides（部門內部與跨部門覆寫）** 是協同作業的核心骨幹。

本篇完整規範了四大部門圖層的 Sublayer 權重秩序（`L > FX > A > E`）、命名空間邊界、各部門內部的 `Master = Overrides + Base` 雙層結構，以及較強部門如何透過非破壞性的稀疏覆寫（Sparse Overrides）達成跨部門意見貫穿。

---

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一根節點 `/ROOT`**：所有鏡頭圖層與元素頂層一律以 `/ROOT` 為唯一根節點，各部門在下方以專屬分支隔離（`/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting`），徹底避免名稱碰撞。**唯一例外為渲染設定 `/Render`**，其為 `/ROOT` 的同層兄弟——渲染設定不是場景內容，不應隨場景被引用（見 §4）。
> 2. **LIVRPS Sublayer 強弱順序**：頂層 `subLayers` 順序決定意見權重（Index 越小權限越強）：
>    `Lighting (最強) > FX (次強) > Animation (中等) > Environment (最弱)`
> 3. **各部門內部雙層堆疊**：四大主要圖層內部普遍採用 `Master → Overrides → Base` 結構；`overrides.usd` 本身作為聚合容器，再 Sublayer 各任務微型覆寫檔案。
> 4. **跨部門稀疏覆寫（Sparse Overrides）**：較強部門的 Override 圖層**不受限於自身的 Scene Tree**。只要透過 USD `over "/ROOT/..."` 語法，即可直接非破壞性地覆寫較弱部門的屬性（如 Lighting 覆寫道具材質、FX 隱藏角色幾何以接管破碎）。
> 5. **覆寫單向性**：覆寫方向嚴格遵守權重矩陣，僅允許「上層覆寫下層」，禁止或無效化逆向覆寫。

---

## 1. 鏡頭頂層總成 (`shot.usd`)

在鏡頭的主組裝檔案（`shot.usd`）中，透過 `subLayers` 陣列將各部門交付的 Master Layer 按權重依序堆疊：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
    framesPerSecond = 24
    startTimeCode = 1        # 含前後手把的完整範圍
    endTimeCode = 100
    subLayers = [
        @./layers/lighting.usd@,     # [0] 最強：燈光、渲染設定與全場外觀覆寫
        @./layers/fx.usd@,           # [1] 次強：特效模擬、破碎與角色接管
        @./layers/anim.usd@,    # [2] 中等：角色骨架動態、攝影機與道具動畫
        @./layers/environment.usd@   # [3] 最弱：世界舞台、建築與 Set Dressing
    ]
)

def Xform "ROOT" (
    kind = "assembly"
)
{
}
```

---

## 2. Sublayer 強弱順序與權重解析

### 為什麼是這個強弱順序？

| 圖層順序 (LIVRPS 意見強弱) | 圖層檔案 | 權限層級 | 核心架構職責與覆寫能力 |
| :--- | :--- | :--- | :--- |
| **Index 0 (最強)** | `lighting.usd` | 最強 (最高仲裁權) | Pipeline 最後一棒，具全場最終覆寫權（修整瑕疵、調光綁定） |
| **Index 1 (次強)** | `fx.usd` | 次強 | 可非破壞性接管/隱藏角色幾何，疊加體積、布料與破碎模擬 |
| **Index 2 (中等)** | `anim.usd` | 中等 | 接管環境道具 Transform，驅動骨架角色表演與鏡頭時序動畫 |
| **Index 3 (最弱)** | `environment.usd` | 最弱 (基礎舞台) | 提供純幾何世界舞台，作為動畫角色定位基準與 FX 模擬碰撞體 |

1. **Lighting 最強**：Pipeline 最後一棒，需具備修正任何瑕疵的能力（例如覆寫局部材質、排除特定光源、隱藏穿幫物件）。
2. **FX 強於 Animation**：FX 需能非破壞性地隱藏動畫角色幾何（接管為破碎模型）或在角色身上疊加動態效果（泥漿、血跡）。
3. **Animation 強於 Environment**：動畫師需能接管或覆寫環境道具的位置（如拿起桌面上的杯子），且動畫鏡頭視角高於環境預設。

---

## 3. 各 USD Layer 的內部結構與職責

每個部門的 Layer 檔案均各自獨立發佈，內部均以 `/ROOT` 為根，並建立該部門專屬的 Primitive 分支：

### 1. Environment Layer (`environment.usd`) —— 最弱（舞台基底）
> 📖 詳細架構請見：[USD Environment 與 Set Dressing 場景陳設架構設計](usd-environment-setdressing.md)、[USD Asset Layer 架構設計](usd-asset-layer.md)

承載整體靜態舞台空間。內部透過 Reference / Payload 引用 Component Asset，自身不帶龐大多邊形快取：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Environment" ( kind = "group" )
    {
        # 引用外部發布之 Asset（由 Output Processor 替換為 Expression Variable，指向 asset_latest.usd 之 </ROOT>）
        def Xform "Terrain" (
            payload = @`"${PROJECT_ROOT}/publish/assets/env/terrain/cliff_path/asset_latest.usd"`@</ROOT>
        ) {}
        
        def Scope "Props" ( kind = "group" )
        {
            def Xform "Table_01" (
                payload = @`"${PROJECT_ROOT}/publish/assets/props/wooden_table/asset_latest.usd"`@</ROOT>
            ) {}
        }
    }
}
```

### 2. Animation Layer (`anim.usd`) —— 次弱（動態表演）
> 📖 詳細架構請見：[USD Animation Layer 動態架構設計](usd-animation-layer.md)

負責全場角色表演與鏡頭運動。解耦為 `geo`（幾何）、`skel`（骨架拓樸）與 `animation`（關節時序動態），磁碟佔用極小（僅數 MB）：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim" ( kind = "group" )
    {
        def Scope "Characters" ( kind = "group" )
        {
            # 單次引用綁定角色，一併帶入幾何、材質與骨架；其 /ROOT 即為 SkelRoot
            def "Hero" (
                prepend apiSchemas = ["SkelBindingAPI"]
                prepend references = @`"${PROJECT_ROOT}/publish/chars/hero/char_latest.usd"`@</ROOT>
            )
            {
                # 動畫層唯一產出：純動態時序資料
                def SkelAnimation "AnimData"
                {
                    uniform token[] joints = ["Hips", "Spine", "Head"]
                    quatf[] rotations.timeSamples = { 1: [...], 100: [...] }
                }
                rel skel:animationSource = </ROOT/Anim/Characters/Hero/AnimData>
            }
        }
    }
}
```

### 3. FX Layer (`fx.usd`) —— 次強（動態模擬）
> 📖 詳細架構請見：[USD FX Layer 鏡頭特效層架構設計](usd-fx-layer.md)

負責承載體積、流體、粒子與剛體碎屑快取。以專案註冊之元素名稱掛載：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "FX" ( kind = "group" )
    {
        # 掛載大型體積快取 (Payload 延遲加載)
        def Xform "explosion_hero" (
            payload = @`"${PROJECT_ROOT}/publish/fx/elements/explosion_hero/element_latest.usd"`@</ROOT>
        ) {}
    }
}
```

### 4. Lighting Layer (`lighting.usd`) —— 最強（終審裁決）
> 📖 詳細架構請見：[USD Lighting Layer 燈光層架構與最終仲裁權](usd-lighting-layer.md)

定義光源、環境光、Light Linking 與最終渲染品質；並一併產出 `/Render` 命名空間下的渲染設定（詳見 [§4 Render 層](#4-render-層render-命名空間)）：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Lighting" ( kind = "group" )
    {
        def DomeLight "SkyDome"
        {
            # 注意：asset 型「屬性值」不適用 Composition 階段的 Expression Variable，
            # 一律由 Output Processor 於輸出時寫入已解析的絕對路徑。詳見發布封裝篇 §4.2。
            asset inputs:texture:file = @/projects/show_A/assets/hdri/sunset.exr@
            float inputs:intensity = 1.2
        }
        def RectLight "KeyLight"
        {
            float inputs:intensity = 5000.0
            color3f inputs:color = (1.0, 0.95, 0.8)
            double3 xformOp:translate = (1, 2.5, 1.5)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }
    }
}
```

---

## 4. Render 層：`/Render` 命名空間

渲染設定（`RenderSettings` / `RenderProduct` / `RenderVar`）是鏡頭的**終端配置**，其命名空間位於 **`/Render`——`/ROOT` 的同層兄弟，而非其子孫**。

> [!IMPORTANT]
> **這是「統一根節點 `/ROOT`」鐵律的唯一例外，且為刻意設計**
> 鐵律要求所有內容一律掛在 `/ROOT` 底下，但其兩項立論在渲染設定上**皆不適用**：
> 1. **名稱解耦不需要**：`RenderSettings` 不會被消費端引用並重新命名，它是該鏡頭的終端產物，不具備跨專案複用的性質。
> 2. **工具不靠路徑尋找**：渲染器透過 `renderSettingsPrimPath` 這項 Layer Metadata、或按 Prim 型別遍歷來定位它，與所在路徑無關。
>
> 更關鍵的是**一項正面理由**：**渲染設定不是場景內容，不應隨場景一起被引用**。若置於 `/ROOT` 底下，任何人 Reference 該鏡頭的 `</ROOT>` 都會把渲染設定一併拖入——這顯然是錯的。置於 `/Render` 可天然隔離。
>
> 此結構亦與 Houdini Solaris 的原生行為一致（實測 22.0：`Render Settings LOP` 預設即建立於 `/Render/rendersettings`），無須逐次調整 LOP 參數。

### 1. 命名空間結構

沿用 Houdini Solaris 的預設佈局，全專案統一：

```text
/Render                                   (Scope)
├── <settings_name>                       (RenderSettings)   例：final / preview / techpass
└── Products/                             (Scope)
    ├── <product_name>                    (RenderProduct)
    └── Vars/                             (Scope)
        └── <var_name>                    (RenderVar)        例：beauty / depth / cryptomatte
```

### 2. 一個鏡頭並存多套 `RenderSettings`

同一顆鏡頭通常需要數種產出組態，各自獨立成一個 `RenderSettings` Prim：

| 用途 | 典型差異 |
| :--- | :--- |
| `preview` | 半解析度、低取樣、僅 beauty，供日常確認 |
| `final` | 全解析度、正式取樣與降噪、完整 AOV |
| `techpass` | Cryptomatte、Deep、Utility Pass，供合成使用 |

> [!TIP]
> **要用哪一套，是「提交當下」的選擇，不是發布時的決定**
> `renderSettingsPrimPath` 在發布的圖層中通常不予宣告；實際由 USD Render ROP 或農場提交工具在送算時指定。如此一來，同一份已發布的鏡頭無須重新發布，即可切換不同產出組態。

### 3. 職責邊界：哪些該由 Lighting 決定，哪些不該

`/Render` 由 **`lighting.usd` 一併產出**，不另立發布單元——Lighting TD 本就是實際調校畫質與 AOV 的人，且這些設定與燈光強耦合（Light Linking、per-light LPE）。

但**並非 `/Render` 裡的每一項都屬於 Lighting 的職權**：

| 項目 | 決定者 | 理由 |
| :--- | :--- | :--- |
| 取樣數、降噪、光線深度、AOV 組成 | **Lighting** | 屬畫質與外觀範疇 |
| 解析度、`pixelAspectRatio` | **Pipeline 注入** | 源自專案規格，非單一鏡頭可決定 |
| 影格範圍 | **Pipeline 注入** | 源自剪輯與鏡頭規格；寫死將使鏡頭改長度即逼 Lighting 重新發布 |
| 送算當下的臨時調整 | **提交層覆寫** | 如半解析度試算、只出特定 AOV，不應污染已發布版本 |

> [!CAUTION]
> **嚴禁將製作資料寫死於 Lighting 的發布版本**
> 解析度與影格範圍屬製作管理系統的資料。若由 Lighting 手動填入並隨版本發布，則剪輯每次改動鏡頭長度，都會迫使一個內容毫無變化的 Lighting 版本重新發布；久之版本號將失去意義。
>
> 正確作法是由 Pipeline 於鏡頭總成或提交階段，以薄覆寫層注入當下的製作資料。

### 4. 提交階段的臨時覆寫

送算時的調整一律以**提交層**處理，不修改任何已發布圖層：

```usda
# 提交工具產生的臨時層，疊於 shot.usd 之上
over "Render"
{
    over "final"
    {
        int2 resolution = (960, 540)      # 半解析度試算
        rel products = [ </Render/Products/beauty_only> ]
    }
}
```

---

## 5. 部門內部圖層結構：Master 與 Overrides 堆疊

在實際 Pipeline 中，四大圖層本身並非單一扁平檔案，而是各自採用 **Master → Overrides → Base** 的 Sublayer 結構：

```usda
# lighting.usd (Master 入口)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./lighting_overrides.usd@,  # 最強 (Index 0): 彙整所有微型覆寫意見
        @./lighting_base.usd@        # 較弱 (Index 1): 本部門基礎光源與產出 (/ROOT/Lighting)
    ]
)

over "ROOT" {}
```

### `lighting_overrides.usd` 容器的多層 Sublayer 結構

`overrides.usd` 本身作為聚合容器（Container Layer），進一步 Sublayer 各任務或藝術家獨立發佈的微型覆寫檔案：

```usda
# lighting_overrides.usd (聚合容器)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./overrides/shot_lookdev_patch_v03.usd@, # 針對特定鏡頭的 Lookdev 局部微調
        @./overrides/char_eye_highlight_fix.usd@,  # 角色眼神光修補
        @./overrides/bg_prop_prune.usd@           # 隱藏背景穿幫道具的可見度覆寫
    ]
)

over "ROOT" {}
```

```text
[Shot 視角]
shot.usd
 └── subLayer: lighting.usd (Master)
      ├── subLayer: lighting_overrides.usd (容器)
      │    ├── subLayer: shot_lookdev_patch_v03.usd   <-- 細分任務覆寫
      │    ├── subLayer: char_eye_highlight_fix.usd   <-- 細分任務覆寫
      │    └── subLayer: bg_prop_prune.usd            <-- 細分任務覆寫
      └── subLayer: lighting_base.usd                 <-- 放置 /ROOT/Lighting 光源本體
```

---

## 6. 跨部門稀疏覆寫（Cross-Department Sparse Overrides）

### 為什麼不需要符合自身 Scene Tree？

在傳統階層思維中，Lighting 部門似乎只能修改 `/ROOT/Lighting` 底下的節點。但在 USD 的 Sublayer 機制中：
- **Sublayer 權限全域生效**：只要圖層處於上層（如 Lighting 位於 Stage 最頂層），該圖層內的任何意見都會覆蓋下層所有部門同名屬性。
- **USD `over` 的純屬性稀疏性**：不需要重新定義 Mesh 或完整幾何，只需聲明路徑與欲修改的屬性（稀疏意見，Sparse Opinion）。

因此，較強部門的 override 圖層**完全可以、且常常需要跨部門寫入**較弱部門的 Scene Tree。

---

## 7. 跨部門覆寫實務情境代碼範例

### 情境 A：Lighting 覆寫 Environment（背景道具微調）
* **檔案**：`lighting_overrides/bg_prop_prune.usd`
* **實務目的**：背景某張桌子反光過強，或某棵樹擋住鏡頭焦點，燈光師直接調降該物件粗糙度或隱藏它：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Environment"
    {
        over "Props"
        {
            # 覆寫環境部門定義的木桌材質參數 (不更動環境原檔)
            over "Table_01"
            {
                rel material:binding = </ROOT/Lighting/Materials/M_Table_Darker>
            }
            
            # 隱藏背景遮擋視線的樹木（此樹為獨立 Prim，故可直接 over）
            over "Tree_Occluder"
            {
                token visibility = "invisible"
            }
        }
    }
}
```

> [!CAUTION]
> **若目標是 `PointInstancer` 的其中一個實例，上述寫法完全無效**
> `PointInstancer` **本身是 Prim，可正常以 `over` 覆寫**；但它的**個別實例不是 Prim**——實例只是 `positions` / `protoIndices` 等陣列中的一筆索引，命名空間裡沒有 `.../ForestTrees/Tree_01723` 這種路徑存在，因此**無法對單一實例下 `over`**。
>
> 換言之：覆寫的對象從「**那棵樹**」變成「**那顆 Instancer 的屬性**」。海量散佈（森林、碎石、草皮）一律以 `PointInstancer` 承載，所以「隱藏那棵擋鏡頭的樹」必須改寫 Instancer 上的實例級屬性：
>
> ```usda
> over "ROOT" { over "Environment" { over "SetDressing"
> {
>     over "OuterForest"
>     {
>         over "ForestTrees"
>         {
>             # 以 id 隱藏個別實例；未宣告 ids 時，id 即為實例在陣列中的索引
>             int64[] invisibleIds = [1723, 4408]
>         }
>     }
> } } }
> ```
>
> **同一限制亦適用於材質**：無法為單一實例指定專屬 `material:binding`。若需外觀差異，只能在原型層級處理——增加一個原型並以 `protoIndices` 指派，或改用 `Instanceable Xform` 逐顆擺放。
>
> 因此 Lighting 在動手前必須先確認目標的承載形式：**獨立 Prim 用 `over`，`PointInstancer` 實例用 `invisibleIds`**。兩者無法互換，用錯不會報錯、只是毫無反應。

> [!WARNING]
> **`invisibleIds` 是單一陣列屬性，多部門覆寫會互相蓋掉而非合併**
> 這是 `PointInstancer` 覆寫最容易出事的地方。`invisibleIds` 是一個 `int64[]`，屬性解析採**最強意見全取**——陣列**不會逐元素合併**。
>
> 因此當 FX 在 `fx_overrides` 隱藏了被爆炸波及的 `[4408, 4409]`，而 Lighting 在更強的圖層隱藏了擋鏡頭的 `[1723]`，最終生效的是 **`[1723]`**——FX 那兩棵樹會**默默重新出現**，且雙方都不會收到任何警告。
>
> 這與一般稀疏覆寫「各改各的屬性、互不干擾」的直覺完全相反。因應方式：
> - **單一負責人原則**：同一顆 `PointInstancer` 的 `invisibleIds`，全鏡頭只由**一個**覆寫圖層維護，其他部門以需求單形式集中提出。
> - **若確需多方各自控制**，則該散佈不適合以單一 `PointInstancer` 承載——應依用途拆分為多顆 Instancer（如 `ForestTrees_BG` 與 `ForestTrees_Hero`），使各自的 `invisibleIds` 不再競爭。
>
> 同一風險適用於 `PointInstancer` 的所有陣列屬性（`protoIndices`、`positions`、`orientations`、`scales`）。

### 情境 B：Lighting 覆寫 Animation（角色 Lookdev 修補）
* **檔案**：`lighting_overrides/char_eye_highlight_fix.usd`
* **實務目的**：關閉特定幾何的投射陰影，或為主角臉部調整專屬著色屬性：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Anim"
    {
        over "Characters"
        {
            over "Hero"
            {
                # 關閉主角斗篷對特定燈光的陰影遮蔽
                bool primvars:karma:light:shadow = false
            }
        }
    }
}
```

### 情境 C：FX 覆寫 Animation（接管被炸毀的角色）
* **檔案**：`fx_overrides/explosion_hero_switch.usd`
* **實務目的**：第 45 格主角被炸碎，FX 圖層需在第 45 格將動畫角色設為隱形，改由 FX 自身生成的破碎快取呈現：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Anim"
    {
        over "Characters"
        {
            over "Hero"
            {
                # 在第 45 格由可見轉為不可見
                token visibility.timeSamples = {
                    1: "inherited",
                    44: "inherited",
                    45: "invisible"
                }
            }
        }
    }
}
```

### 情境 D：Animation 覆寫 Environment（道具手持接管）
* **檔案**：`anim_overrides/prop_pickup.usd`
* **實務目的**：角色拿起原本擺在環境桌上的咖啡杯，動畫師在第 20 格接管杯子的 Transform：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Environment"
    {
        over "Props"
        {
            over "CoffeeCup"
            {
                # 覆寫杯子的 Transform 為動態動畫快取
                double3 xformOp:translate.timeSamples = {
                    1: (0.1, 0.8, 0.05),
                    20: (0.1, 0.8, 0.05),
                    25: (0.15, 1.1, 0.08)
                }
            }
        }
    }
}
```

---

## 8. 跨部門覆寫的合法方向矩陣

依據 Sublayer 堆疊權重規則（`Lighting > FX > Anim > Env`），覆寫方向具有**單向性**：

| 發起覆寫的部門 | 可合法覆寫的目標部門與路徑 | 禁止/無效的覆寫方向 |
| :--- | :--- | :--- |
| **Lighting Overrides** | `/ROOT/Lighting`（自身）<br>`/ROOT/FX`<br>`/ROOT/Anim`<br>`/ROOT/Environment` | 無（位於最頂層，對全場擁有最終覆寫權） |
| **FX Overrides** | `/ROOT/FX`（自身）<br>`/ROOT/Anim`<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>*(FX 的意見無法蓋過 Lighting)* |
| **Animation Overrides** | `/ROOT/Anim`（自身）<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>❌ `/ROOT/FX` |
| **Environment Overrides** | `/ROOT/Environment`（自身內部細節微調） | ❌ 上述所有部門 |

---

## 9. 架構優勢與防坑指南

### Pipeline 架構優勢
1. **多人並行協作零衝突（Zero File Lock）**：
   - 燈光組內燈光師 A 負責 `char_lighting_patch.usd`，燈光師 B 負責 `env_shader_tweak.usd`。
   - 兩人各自發佈獨立小檔，僅在 `overrides.usd` 註冊 sublayer，完全不產生 Git 衝突或檔案鎖爭奪。
2. **安全版本回滾（Clean Rollback）**：
   - 若某個修補效果出錯，只需發布新版的 `overrides.usd` 容器、將該 sublayer 自清單移除，即可完全復原，**不傷害底層快取、也不需重新解算任何內容**。
   - 被移除的修補檔本身仍完整保留於原處，日後隨時可重新掛回。
3. **極致輕量化（Ultra Lightweight）**：
   - Override 檔案內通常只有幾十行純 ASCII 文字（`over`、屬性變更或時間樣本），不夾帶沉重的 Mesh 或快取，傳輸與解析極快。

> [!CAUTION]
> **Layer Muting 是除錯工具，不是交付手段**
> `UsdStage.MuteLayer()`（以及 Houdini Solaris 圖層面板上的靜音開關）是**純執行期、僅存在於記憶體**的狀態：
> - **不會寫入任何檔案**，存檔後即消失。
> - **不隨檔案傳遞**——送上農場、交給下游、交付客戶，對方拿到的都是未靜音的版本。
> - 僅作用於當前 Stage 或當前行程。
>
> 典型的事故流程是：藝術家靜音掉出問題的修補層 → Viewport 顯示正常 → 送農場算圖 → **農場帶著那個問題渲染完整卷**，因為靜音狀態從未離開他的 session。
>
> **Muting 的正當用途**是在自己的 session 中快速 A／B 比對、逐層排查是哪個覆寫造成問題。一旦判定要移除，**必須落實為發布動作**。

> [!WARNING]
> **亦不可**「**直接編輯已發布的 `overrides.usd` 把 sublayer 註解掉**」
> 已發布的版次目錄一律轉為唯讀、位元組層級不可變（見 [發布封裝篇](usd-publish-packaging.md)）。就地修改已發布檔案會破壞該版本的歷史確定性——所有引用它的鏡頭都會被無聲改變，且無從追溯。
>
> 正確作法是**發布新版的 `overrides.usd` 容器**，於 `subLayers` 清單中不再列入該修補檔。這既保留了完整的版本軌跡（哪一版拿掉了哪個修補一目了然），也讓被移除的修補檔原封不動地留在原處，隨時可重新掛回。

### 防坑指南
> [!WARNING]
> **嚴禁在下層預寫高層屬性**
> - **問題**：若環境組在 `environment.usd` 順便建了測試燈光，該光源會殘留至最終合成中，干擾燈光師工作。
> - **解法**：嚴守資料邊界，環境圖層只允許在 `/ROOT/Environment` 建立幾何與靜態材質。

> [!TIP]
> **命名空間隔離的優勢**
> 透過 `/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting` 明確切割分支，各部門發佈各自的 usd 時，永遠不會發生節點名稱碰撞（Name Collision），合成時只需由頂層以 `over` 定義 cross-branch 的互動或覆寫。

---

## 10. 鏡頭交付與進版對齊

> 📖 發布邊界、目錄封裝與進版機制詳見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

所有交付至鏡頭中的圖層元素皆遵循統一標準：
- **目錄即包裝單元**：以目標輸出資料夾作為完整封裝邊界，隱式圖層禁止外溢。
- **內相對、外絕對**：資料夾內部層層互連使用 `@./...@` 相對路徑；引用外部共用 Asset 庫一律使用絕對路徑。
- **動態 `latest` 引用與逆向鎖定**：日常製作預設引用 `latest.usd`；農場算圖或定剪審查時，由自訂 **Asset Resolver** 將 `latest` 在記憶體中逆向鎖定為具體歷史版本，保證 100% 畫面可重現。

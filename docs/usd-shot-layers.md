# USD：Shot Layers 鏡頭分層與 Overrides 覆寫架構

在 OpenUSD 的鏡頭級生產中，**Shot Layer Stacking（鏡頭圖層堆疊）** 與 **Department Overrides（部門內部與跨部門覆寫）** 是協同作業的核心骨幹。

本篇完整規範了四大部門圖層的 Sublayer 權重秩序（`L > FX > A > E`）、命名空間邊界、各部門內部的 `Master = Overrides + Base` 雙層結構，以及較強部門如何透過非破壞性的稀疏覆寫（Sparse Overrides）達成跨部門意見貫穿。

---

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一根節點 `/ROOT`**：所有鏡頭圖層與元素頂層一律以 `/ROOT` 為唯一根節點，各部門在下方以專屬分支隔離（`/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting`），徹底避免名稱碰撞。**攝影機不屬任何部門**，另立與之同層的 `/ROOT/Cameras`（見 §5）。**唯一例外為渲染設定 `/Render`**，其與 `/ROOT` 同層——渲染設定不是場景內容，不應隨場景被引用（見 §4）。
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
    # 四個部門 Master 各為獨立包裝單元，故一律以專案變數作跨包絕對引用
    subLayers = [
        # [0] 最強：燈光、渲染設定與全場外觀覆寫
        @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/lighting/Lighting_master/lighting_latest.usda"`@,
        # [1] 次強：特效模擬、破碎與角色接管
        @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/fx/Fx_master/fx_latest.usda"`@,
        # [2] 中等：角色骨架動態、攝影機與道具動畫
        @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/anim/Anim_master/anim_latest.usda"`@,
        # [3] 最弱：世界舞台、建築與 Set Dressing
        @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/environment/Environment_master/environment_latest.usda"`@
    ]
)

def Xform "ROOT" (
    kind = "assembly"
)
{
    # 攝影機不屬任何部門，故不經部門 Master，由此直接以 Reference 帶入。
    # 經 Reference 弧的意見弱於整個 Layer Stack 的 Local 意見，因此它恆在
    # 四個部門之下，任何部門皆可覆寫——詳見 §5.3。
    def Scope "Cameras"
    {
        # FinalCamera 是「位置」的保留字，不是單元名——落在此處者即為
        # 最終算圖相機，單元本身不知道自己被選中了（見 §5.2）。
        def "FinalCamera" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/camera/LayoutMain/camera_latest.usda"`@</ROOT>
        ) {}
    }
}
```

> [!IMPORTANT]
> **部門 Master 是包外引用，不得寫成相對路徑**
> 四個部門 Master 與 `Shot` 分屬**不同的包裝單元**，彼此引用即為包外引用，依[路徑雙重標準](usd-publish-packaging.md)必須使用絕對路徑並由 Output Processor 變數化。若寫成 `@./layers/lighting.usd@`，等於宣稱 Master 是 `Shot` 包內的檔案——一旦該部門單獨重新發布，鏈結即告失效。

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
        # 引用外部發布之 Asset（由 Output Processor 替換為 Expression Variable，指向 asset_latest.usda 之 </ROOT>）
        def Xform "Terrain" (
            payload = @`"${PROJECT_ROOT}/publish/assets/env/terrain/CliffPath/asset_latest.usda"`@</ROOT>
        ) {}
        
        def Scope "Props" ( kind = "group" )
        {
            def Xform "Table_01" (
                payload = @`"${PROJECT_ROOT}/publish/assets/props/WoodenTable/asset_latest.usda"`@</ROOT>
            ) {}
        }
    }
}
```

### 2. Animation Layer (`anim.usd`) —— 次弱（動態表演）
> 📖 詳細架構請見：[USD Animation Layer 動態架構設計](usd-animation-layer.md)

負責全場角色表演與鏡頭運動。解耦為 `geo`（幾何）、`skel`（骨架拓樸）與 `animation`（關節時序動態），磁碟佔用極小（僅數 MB）：
```usda
# anim_base.usd —— 部門 Master 的 base，彙整本鏡頭已發布的動畫單元
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim" ( kind = "group" )
    {
        # 各 charAnim 單元以 Reference 嫁接，Prim 名即單元名。
        # 單元內部已封裝綁定角色與 SkelAnimation，此處不再重複宣告。
        def "BoyWalking" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/anim/charAnim/BoyWalking/charAnim_latest.usda"`@</ROOT>
        ) {}
    }
}
```

合成後 `/ROOT/Anim/BoyWalking` 即為完整的 `SkelRoot`，底下是 `Geometry`／`Skel`／`AnimData` 三顆。單元自身的結構與 Master ／ `base` ／ `overrides` 三層堆疊分別詳見 [Animation Layer 篇](usd-animation-layer.md) 與本篇 §5。

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
        def Xform "ExplosionHero" (
            payload = @`"${PROJECT_ROOT}/publish/assets/fx/ExplosionHero/element_latest.usda"`@</ROOT>
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
            # OpenUSD 24.08+ 支援 asset-valued attribute 的 Variable Expression；
            # 舊版部署須改由 Asset Resolver logical identifier 處理。詳見發布封裝篇 §6.2。
            asset inputs:texture:file = @`"${PROJECT_ROOT}/assets/hdri/sunset.exr"`@
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

渲染設定（`RenderSettings` / `RenderProduct` / `RenderVar`）是鏡頭的**終端配置**，其命名空間位於 **`/Render`——與 `/ROOT` 同層，而非在其之下**。

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

> [!NOTE]
> **`RenderSettings` 以 relationship 指向攝影機**
> `rel camera = </ROOT/Cameras/FinalCamera/Motion/Camera>`。該路徑之所以能寫死在模板裡，是因為 `FinalCamera` 為**位置**的保留字——落在該位置的即為全鏡頭主相機——見 [§5.2](#2-最終算圖相機由鏡頭總裝指定而非單元自稱)。
>
> `camera` 是 **per-settings** 的，因此各套 `RenderSettings` 大可指向不同攝影機——techpass 從另一機位算圖即為常見情形。這與「主相機只有一部」不衝突，兩者談的不是同一件事，見 [§5.2](#2-最終算圖相機由鏡頭總裝指定而非單元自稱)。

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

## 5. 攝影機單元：跨部門，且恆為最弱

攝影機**不屬於任何部門**。會發布攝影機的不只 Animation——Layout 的 previz 機、Lighting 的 witness 機、FX 為模擬對位而設的輔助機皆然。因此它：

- 不進入任何部門的 Master 或 `base`
- 合成於 **`/ROOT/Cameras`**——與 `/ROOT/Anim`、`/ROOT/FX` **同層**，而非位於任何部門之下
- 由 `shot.usd` **以 Reference 直接帶入**

### 1. 單元結構：運動與光學分離

```usda
# camera/<unit>/v###/camera.usd —— 以 /ROOT 為根，不知悉掛載位置
#usda 1.0
(
    defaultPrim = "ROOT"
)

def "ROOT"
{
    # 運動：攝影機在世界中的位移與旋轉
    def Xform "Motion"
    {
        double3 xformOp:translate.timeSamples = {
            1: (0, 1.5, 3),
            50: (0.2, 1.55, 2.5)
        }
        float3 xformOp:rotateXYZ.timeSamples = {
            1: (-10, 5, 0),
            50: (-8, 12, 0)
        }
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]

        # 光學：鏡頭本身的成像參數
        def Camera "Camera"
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
        }
    }
}
```

分作兩層的理由是**運動與光學各有其擁有者**：運動多由 Layout 或 Animation 決定，光學（景深、焦段）則常由攝影指導或 Lighting 主張。分層後兩者可各自被覆寫而不互相牽動——例如 Lighting 調整景深時不會動到機位。

> [!NOTE]
> **3D 立體相機是具名例外**
> 立體拍攝需一組運動掛載左右雙機，`Motion` 底下因而是兩顆 `Camera` 而非一顆，固定葉節點結構在此不成立。
>
> 這不構成問題，因為**它在專案設定階段就已知**：是否為立體專案不會到鏡頭組裝時才發現。Pipeline 得以預先反應——QC 的葉節點檢查改為接受雙機、提交工具依專案組態決定送哪一眼。
>
> 而 `FinalCamera` **這個位置的名稱不受影響**：無論底下掛的是單機或雙機，最終算圖相機恆在 `/ROOT/Cameras/FinalCamera`。下游要定位它的方式沒有改變。

> [!IMPORTANT]
> **`xformOp` 一律寫在 `Motion` 上，不寫在 `Camera` 上**
> 就合成結果而言兩者其實等價——`Motion` 是 `Camera` 的父層，變換本就往下傳遞，實測 FOV 與最終矩陣皆無差異。這是**可讀性與歸屬**的規範，不是技術限制。
>
> 縮放最能說明為何要分：**縮放永遠不影響 FOV**。視角只由 `focalLength / aperture` 決定，實測三種配置（無縮放、縮放於 `Motion`、縮放於 `Camera`）的 FOV 完全一致：
>
> ```text
> 無縮放          focalLength=0.5000  aperture=0.2095  FOV=23.6702°
> Motion 縮放 2   focalLength=0.5000  aperture=0.2095  FOV=23.6702°
> Camera 縮放 2   focalLength=0.5000  aperture=0.2095  FOV=23.6702°
> ```
>
> 因此縮放寫在 `Camera` 上格外誤導——它**看起來**像在調整鏡頭，實際上只是在空間中改變攝影機的尺度與位置，而那正是 `Motion` 的職責。場景需要整體縮放（微縮模型、比例改版）時，縮放整組運動遠比縮放鏡頭本體符合直覺。
>
> 分層之後，`Camera` Prim 上就只剩**真正的光學參數**，排查時不必再判斷某個 `xformOp` 究竟意在移動還是意在成像。

### 2. 最終算圖相機：由鏡頭總裝指定，而非單元自稱

**每個攝影機單元的內部結構完全相同**，不因用途而異：

```text
<任一相機單元>/v###/camera.usd
└── /ROOT
    └── Motion
        └── Camera
```

單元**不知道自己是不是最終算圖相機**。這件事由 `shot.usd` 在 Reference 時決定——落在 `FinalCamera` 這個位置的，就是最終算圖相機：

```usda
# shot.usd
def Scope "Cameras"
{
    # 保留位置：最終算圖相機
    def "FinalCamera" (
        prepend references = @`"${PROJECT_ROOT}/.../camera/LayoutMain/camera_latest.usda"`@</ROOT>
    ) {}

    # 其餘為複選，位置自由命名
    def "PrevizWide" (
        prepend references = @`"${PROJECT_ROOT}/.../camera/HandheldA/camera_latest.usda"`@</ROOT>
    ) {}
    def "WitnessTop" (
        prepend references = @`"${PROJECT_ROOT}/.../camera/LightingWitness/camera_latest.usda"`@</ROOT>
    ) {}
}
```

合成後：

```text
/ROOT/Cameras/FinalCamera/Motion/Camera        <-- 全專案恆定，算圖對象
/ROOT/Cameras/PrevizWide/Motion/Camera         <-- 複選
/ROOT/Cameras/WitnessTop/Motion/Camera
```

> [!IMPORTANT]
> **`FinalCamera` 是位置的保留字，不是單元名**
> 這與[單元不知悉自身掛載位置](usd-publish-packaging.md)是同一條原則。若改由單元自稱（把某個發布目錄命名為 `FinalCamera`），會產生三個問題：
>
> 1. **發布者被迫在發布當下決定用途**，但「哪一台是最終機」往往到 Layout 定案甚至更晚才確定。
> 2. **更換最終機需重新發布或改名**，而實際上該變的只是鏡頭總裝的一個 Reference 目標。
> 3. **跨部門撞名**：會發布攝影機的部門不只一個，而[單元名於鏡頭作用域內唯一](usd-publish-packaging.md)——Layout 與 Lighting 都想交付「最終機候選」時即告死結。
>
> 位置保留字沒有這些問題：各部門自由命名自己的單元（`LayoutMain`、`HandheldA`、`LightingWitness`），由鏡頭總裝挑選其一放進 `FinalCamera`。

> [!IMPORTANT]
> **路徑固定是流程約束，不是 USD 的要求**
> `UsdRenderSettings` 的 `camera` 是 **relationship**，技術上可指向任意路徑——即使每顆鏡頭的相機路徑都不同，USD 也運作無礙。
>
> 但那會讓 `RenderSettings` 無法以模板產生：每顆鏡頭都得有人手動接上正確的相機，農場提交工具也無從推導。固定 `FinalCamera` 之位，即以結構消除歧異：
>
> ```usda
> def RenderSettings "final"
> {
>     rel camera = </ROOT/Cameras/FinalCamera/Motion/Camera>
> }
> ```

「只能有一部」由命名空間自然保證——同一個 `Cameras` Scope 底下不可能存在兩個 `FinalCamera`。

> [!IMPORTANT]
> **判準是對整顆鏡頭而言，不是有沒有被拿去算圖**
> 一顆鏡頭可並存多套 `RenderSettings`，而 `rel camera` 是 per-settings 的——Lighting 為 techpass 另備一台機、從別的角度算出輔助 Pass，完全正當。這與「主相機只有一部」並不衝突，因為兩者界定的不是同一件事：
>
> | | `FinalCamera` | 部門自備的機 |
> | :--- | :--- | :--- |
> | 作用範圍 | 全鏡頭共同基準 | 僅對該部門有意義 |
> | 誰依它工作 | Layout 定機位、動畫表演、FX 模擬皆依它 | 其他部門不依它 |
> | 是否唯一 | 是 | 可有多台 |
>
> techpass 機只對 Lighting 有意義，其他部門不依它工作，因此**不符合主相機的定義**——即使它確實參與了算圖。
>
> 這類機依循完全相同的規則：由該部門發布為一個攝影機單元，於 `shot.usd` 佔據自己的位置（如 `TechpassCam`），其 `RenderSettings` 指向該位置。無須任何新機制——這正是「[攝影機是任何部門都可產出的單元](#5-攝影機單元跨部門且恆為最弱)」在實務上的體現。

### 3. 以 Reference 帶入，因而弱於所有部門

`shot.usd` 以 **Reference** 而非 Sublayer 帶入攝影機：

```usda
# shot.usd
def Xform "ROOT" ( kind = "assembly" )
{
    def Scope "Cameras"
    {
        def "FinalCamera" (
            prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/camera/LayoutMain/camera_latest.usda"`@</ROOT>
        ) {}
    }
}
```

> [!IMPORTANT]
> **這個選擇決定了攝影機的強弱位置——而且與直覺相反**
> 直覺會認為「`shot.usd` 是 Root Layer，寫在裡面的東西最強」。但經 **Reference 弧**帶入的意見，依 LIVRPS 弱於**整個 Root Layer Stack 的 Local 意見**——而四個部門 Master 正是 `shot.usd` 的 Sublayer，同屬該 Layer Stack。
>
> 因此攝影機恆在所有部門**之下**，任何部門都能覆寫它。實測：單元宣告 `focalLength = 0.35`，Lighting 圖層覆寫為 `0.85`，合成結果為 `0.85`。
>
> 若改以 Sublayer 帶入，攝影機便會與部門圖層在同一個 Layer Stack 內競爭，強弱取決於排序，且無法同時弱於全部四個部門。

這正是攝影機該有的位置：它是**全鏡頭的共同基準**，而非某個部門的產出。Layout 定了機位、動畫依之表演、FX 依之模擬、Lighting 最後仍保有微調景深與焦段的餘地。

### 4. 附帶效益：攝影機可跨鏡頭取用

攝影機單元既是自成一體的 `/ROOT` 包、又不隸屬任何部門，取用它便與取用一個 Asset 無異——**包含取用別顆鏡頭的**：

```usda
# 本鏡頭的 shot.usd
def Scope "Cameras"
{
    def "FinalCamera" (
        prepend references = @`"${PROJECT_ROOT}/.../sh010/camera/LayoutMain/camera_latest.usda"`@</ROOT>
    ) {}

    # 直接引用鄰鏡的主相機，用於接戲比對
    def "PrevShotCam" (
        prepend references = @`"${PROJECT_ROOT}/.../sh009/camera/LayoutMain/camera_latest.usda"`@</ROOT>
    ) {}
}
```

典型用途：接戲檢查、整場戲共用一台主相機（此時該單元宜改置於[序列級作用域](usd-publish-packaging.md)）、或 Lighting 需以另一機位驗證光線。**無須複製檔案、也無須改動來源鏡頭**——這是「攝影機不屬任何部門」與「單元 `/ROOT` 化」兩項決定疊加後自然浮現的能力。

---

## 6. 部門內部圖層結構：Master 與 Overrides 堆疊

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

### `<dept>_base.usd`：彙整本鏡頭該部門的發布單元

`base` 並非單一扁平檔案，而是**彙整該鏡頭中本部門所有已發布單元**的容器。以 Animation 為例，本鏡頭發布了 `BoyWalking` 與 `GirlRunning` 兩個角色動畫單元：

```usda
# anim_base.usd
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

合成後，每個單元各自佔據部門分支底下以**自身單元名**命名的一顆 Prim：

```text
/ROOT/Anim/BoyWalking
/ROOT/Anim/GirlRunning
```

> [!IMPORTANT]
> **`base` 以 Reference 嫁接單元，不以 Sublayer**
> Sublayer **不做路徑重映射**：單元若以 Sublayer 疊入，就必須自己把內容寫在 `/ROOT/Anim/<UnitName>` 這個最終路徑上——等於把落點硬編碼進單元，單元從此必須知悉消費端的命名空間。
>
> 改用 Reference 後，單元得以與 FX Element、Prop、Set **完全同構**：自身以 `/ROOT` 為根、不知道自己會被掛到哪裡，由消費端決定落點並自動重映射。這正是 [`/ROOT` 解耦哲學](usd-publish-packaging.md)的直接應用。

> [!IMPORTANT]
> **單元名即 Prim 名**
> 這是[單元名採 PascalCase](usd-publish-packaging.md) 的直接效益——單元名無須任何轉換即可充當 Prim 名，工具鏈不必維護「單元名 → Prim 名」對照表。同時它使「哪顆 Prim 由哪個單元產出」在命名空間中一望即知，跨部門排查時無須回溯整個圖層堆疊。

四大部門一律同構：

| 部門 | Master | `base` 彙整的單元 | 合成後的 Prim |
| :--- | :--- | :--- | :--- |
| Environment | `environment.usd` | Set Dressing、Layout 單元 | `/ROOT/Environment/<UnitName>` |
| Animation | `anim.usd` | charAnim、camera 單元 | `/ROOT/Anim/<UnitName>` |
| FX | `fx.usd` | FX Element 單元 | `/ROOT/FX/<UnitName>` |
| Lighting | `lighting.usd` | Light Rig、燈光單元 | `/ROOT/Lighting/<UnitName>` |

> [!NOTE]
> **Master 進版，`base` 與 `overrides` 不進版**
> Master 是部門對鏡頭的交付面，具備完整版本歷史與 `latest`。`base` 與 `overrides` 是其內部組裝層，隨 Master 一併凍結——任一單元進版，由 Pipeline 重新產生 `base` 並推進 Master 版次。這與 [sub 物件不設 `latest`](usd-publish-packaging.md) 是同一條規則。

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
 └── subLayer: lighting.usd (Master，進版並維護 latest)
      ├── subLayer: lighting_overrides.usd (容器)
      │    ├── subLayer: shot_lookdev_patch_v03.usd   <-- 細分任務覆寫
      │    ├── subLayer: char_eye_highlight_fix.usd   <-- 細分任務覆寫
      │    └── subLayer: bg_prop_prune.usd            <-- 細分任務覆寫
      └── subLayer: lighting_base.usd                 <-- 彙整本鏡頭已發布的燈光單元
           ├── reference: KeyRig/lighting_latest.usda      --> /ROOT/Lighting/KeyRig
           └── reference: RimRig/lighting_latest.usda      --> /ROOT/Lighting/RimRig
```

---

## 7. 跨部門稀疏覆寫（Cross-Department Sparse Overrides）

### 為什麼不需要符合自身 Scene Tree？

在傳統階層思維中，Lighting 部門似乎只能修改 `/ROOT/Lighting` 底下的節點。但在 USD 的 Sublayer 機制中：
- **Sublayer 權限全域生效**：只要圖層處於上層（如 Lighting 位於 Stage 最頂層），該圖層內的任何意見都會覆蓋下層所有部門同名屬性。
- **USD `over` 的純屬性稀疏性**：不需要重新定義 Mesh 或完整幾何，只需聲明路徑與欲修改的屬性（稀疏意見，Sparse Opinion）。

因此，較強部門的 override 圖層**完全可以、且常常需要跨部門寫入**較弱部門的 Scene Tree。

---

## 8. 跨部門覆寫實務情境代碼範例

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

## 9. 跨部門覆寫的合法方向矩陣

依據 Sublayer 堆疊權重規則（`Lighting > FX > Anim > Env`），覆寫方向具有**單向性**：

| 發起覆寫的部門 | 可合法覆寫的目標部門與路徑 | 禁止/無效的覆寫方向 |
| :--- | :--- | :--- |
| **Lighting Overrides** | `/ROOT/Lighting`（自身）<br>`/ROOT/FX`<br>`/ROOT/Anim`<br>`/ROOT/Environment` | 無（位於最頂層，對全場擁有最終覆寫權） |
| **FX Overrides** | `/ROOT/FX`（自身）<br>`/ROOT/Anim`<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>*(FX 的意見無法蓋過 Lighting)* |
| **Animation Overrides** | `/ROOT/Anim`（自身）<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>❌ `/ROOT/FX` |
| **Environment Overrides** | `/ROOT/Environment`（自身內部細節微調） | ❌ 上述所有部門 |

---

## 10. 架構優勢與防坑指南

### Pipeline 架構優勢
1. **多人並行時降低同檔衝突（Reduced File Lock Contention）**：
   - 燈光組內燈光師 A 負責 `char_lighting_patch.usd`，燈光師 B 負責 `env_shader_tweak.usd`。
   - 兩人各自發佈獨立小檔，可避免內容層互相覆寫；但 `overrides.usd` 的 sublayer 清單仍是共享寫入點，必須由發布服務序列化、合併或以 CAS 檢查更新，不能宣稱完全零衝突。
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
> **亦不可直接編輯已發布的 `overrides.usd` 把 sublayer 註解掉**
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

## 11. 鏡頭交付與進版對齊

> 📖 發布邊界、目錄封裝與進版機制詳見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

所有交付至鏡頭中的圖層元素皆遵循統一標準：
- **目錄即包裝單元**：以目標輸出資料夾作為完整封裝邊界，隱式圖層禁止外溢。
- **內相對、外絕對**：資料夾內部層層互連使用 `@./...@` 相對路徑；引用外部共用 Asset 庫一律使用絕對路徑。
- **動態 `latest` 引用與逆向鎖定**：日常製作預設引用 `*_latest.usda`；農場算圖或定剪審查時，由自訂 **Asset Resolver** 將 `latest` 在記憶體中逆向鎖定為具體歷史版本，保證 100% 畫面可重現。

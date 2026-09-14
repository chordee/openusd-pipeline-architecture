# USD：架構設計體系總覽與導讀 (Map of Content)

本目錄匯集了影視與動畫工業級 **OpenUSD 生產 Pipeline 架構設計** 的完整規範。從底層 Asset、場景陳設（Set Dressing）、角色動態（Animation）、特效模擬（FX），到鏡頭圖層堆疊（Shot Layers）、跨部門覆寫（Overrides）、發布封裝（Packaging）與進版鎖定（Versioning & Resolver），建立了一套高內聚、低耦合、極致輕量且具備 100% 歷史可重現性的 USD 體系。

---

## 🗺️ 架構全景導讀地圖 (Pipeline Architecture Map)

![Pipeline Architecture Map](assets/pipeline_architecture_map.svg)

---

## 📚 專題筆記清單與核心權威索引

全套架構由 8 篇互補且深度的專題筆記構成，涵蓋 Pipeline 所有核心面向：

| 筆記名稱 | 核心探討範疇 | 關鍵架構概念 |
| :--- | :--- | :--- |
| **[USD Shot Layers 鏡頭分層與覆寫架構](docs/usd-shot-layers.md)** | 鏡頭總成、強弱權重與覆寫機制 | 四大部門圖層順序（`L > FX > A > E`）、`Master = Overrides + Base`、跨部門稀疏覆寫 |
| **[USD Asset Layer 架構設計](docs/usd-asset-layer.md)** | 單一發布 Asset 內部結構 | 模型/材質雙圖層 Sublayer、`ModelDefault`/`LookDefault`、雙維度 VariantSet、`/ROOT` 解耦哲學 |
| **[USD Environment 與 Set Dressing 場景陳設架構設計](docs/usd-environment-setdressing.md)** | 世界舞台與場景陳設組裝 | Layout 與 Set Dressing 組合、虛擬組裝（零幾何實體）、`PointInstancer` 點雲數據消耗 |
| **[USD Animation Layer 動態架構設計](docs/usd-animation-layer.md)** | 角色骨架與道具時序動態 | 骨架三合一解耦（`geo` + `skel` + `animation`）、Transform 時序動畫、數 MB 極致輕量儲存 |
| **[USD FX Layer 鏡頭特效層架構設計](docs/usd-fx-layer.md)** | 特效元素封裝與掛載機制 | `/ROOT/FX/<element_name>`、元素自身以 `/ROOT` 為基底、Payload 延遲載入體積與點雲 |
| **[USD 發布封裝、路徑邊界與進版解析架構](docs/usd-publish-packaging.md)** | 通用封裝、路徑邊界與版本控制 | 目錄即包裝單元、內相對外絕對、`latest` 指向與 Asset Resolver 逆向鎖定 |
| **[USD Asset Loader 工具架構設計](docs/usd-asset-loader.md)** | 全元素載入與場景陳設工具架構 | Query/Load 兩段式分離、原生 Composition Arcs、自由指定 Prim Path、Instanceable、Class Inherits 標籤廣播 |
| **[USD Solaris Implicit Layer 治理與輸出指南](docs/usd-solaris-implicit-layer.md)** | Solaris 導出虛擬層收斂與治理機制 | Flatten 打平優先、無法打平時強制落地子目錄（`./layers/`）、`Configure Layer` 主動顯式化（Explicit Layer） |

---

## 🏛️ 全 Pipeline 貫穿的七大架構共通鐵律

本目錄下所有專題設計，均無一例外地嚴格遵守以下七大基礎鐵律：

### 1. 統一根節點 `/ROOT` 與語意命名解耦
- **所有發布單元（Asset、Set Dressing、FX Element、Shot）頂層一律以 `/ROOT` 為唯一根節點**。
- **解耦哲學**：Asset 內部不硬編碼特定名稱（如 `/Chair`），而是在被引用端（Consumer）消費時，由外部 Stage 自由指派語意路徑（如 `/ROOT/Environment/Props/OfficeChair_01`）。

### 2. Sublayer 強弱順序與意見貫穿（LIVRPS / Layer Stacking）
- 鏡頭頂層 `subLayers` 順序決定意見權重（Index 越小意見越強）：
  `Lighting (0, 最強) > FX (1, 次強) > Animation (2, 中等) > Environment (3, 最弱)`
- 頂層具備最高仲裁權，可在不觸碰下層快取的前提下，達成非破壞性微調（Non-destructive Overrides）。

### 3. 部門內部階層化與跨部門稀疏覆寫（Sparse Overrides）
- 每個主要圖層內部皆為 `Master = Overrides + Base` 結構；`overrides.usd` 本身作為容器 Sublayer 多個任務覆寫小檔。
- **打破自身 Scene Tree 限制**：較強部門可直接在 override 圖層宣告 `over "/ROOT/..."`，跨部門覆寫較弱部門的屬性（如 Lighting 修改環境道具 Shader、FX 設定動畫角色可見度）。

### 4. 虛擬組裝與資料徹底解耦（極致輕量化）
- **Set Dressing**：100% 透過 Reference / Payload 引用 Component Asset，無多邊形實體，容量僅數 KB 至數 MB（唯一的磁碟體積為 `PointInstancer` 座標陣列）。
- **Animation**：幾何早已在 Asset 階段發佈；動畫層僅存數十個 Joint 旋轉四元數與 Matrix TimeSamples，免除傳統全頂點烘焙動輒數十 GB 的肥大快取。

### 5. 目錄級封裝邊界、同構結構與路徑雙重標準
- **全元素通用**：Asset、Set Dressing、Animation、FX、Pure USD 一體適用。
- **目錄即包裝單元與同構內部結構**：以目標資料夾底下的全體檔案作為不可分割的單一發布單元。無論任何具體物件，資料夾內部結構與命名固定同構（如 `asset_latest.usd`、`modelDefault/`、`lookDefault/`），絕不以 Asset 名稱命名內部檔案。
- **暫存輸出與原子移轉註冊（Staging & Atomic Promotion）**：所有發布一律先輸出至隔離的暫存資料夾，待流程完全跑完且驗證通過後，才原子移轉至專案正式流程目錄並完成註冊，杜絕半成品外溢污染。
- **Solaris Implicit Layer 治理與子目錄收斂**：優先採用 Flatten 打平；無法打平時由 Houdini 自動轉換輸出之圖層，必須透過 `Save Paths Relative to Output` 強制限制在輸出子目錄（如 `./layers/`）內，嚴禁外溢。亦可透過 `Configure Layer` 主動將隱式圖層顯式化。詳情參閱 [USD Solaris Implicit Layer 治理與輸出指南](docs/usd-solaris-implicit-layer.md)。
- **路徑邊界與 Expression Variable 替換**：
  - **包內互連**：一律使用相對路徑 `@./...@`，確保發布目錄可隨意搬遷、封存、跨平臺掛載而不壞鏈。
  - **包外引用**：輸出時由 Solaris Output Processor 自動將專案前綴替換為 Stage Expression Variable（`@${PROJ_ROOT}/...@`），並於 Layer Metadata 預設宣告；專案遷移或交接客戶時，只需在頂層重新指派變數即可一口氣全局生效。

### 6. `asset_latest` 動態指向與 Asset Resolver 逆向鎖定（Version Pinning）
- **版本控管的架構取捨**：不採用 VariantSet 控版（避免回溯修改歷史註冊檔），改採目錄進版（`v001`, `v002`...）並自動維護 `asset_latest.usd`。
- **Sub 物件無 latest 與推進連動**：Asset 底下的 `modelDefault/`、`lookDefault/` 等 sub 物件自身不設 `latest`；每次子組件進版，直接驅動單元物件 Asset 整體進版，並由 Pipeline 自動更新根目錄唯一的 `asset_latest.usd`。
- **跨平臺適配**：Linux 採 Symbolic Link；Windows 採 `subLayers = [@./v###/asset.usd@]` 包裝圖層。
- **歷史確定性**：日常製作預設引用 `asset_latest.usd` 享受無感更新；提交渲染與發布時，由自訂 **Asset Resolver** 讀取審批快照，在記憶體中將 `asset_latest` 逆向鎖定為具體歷史版本，保證 100% 畫面可重現。

### 7. Purpose 對稱完整性、ModelAPI DrawMode 與 `usdkind` 治理
- **Purpose 兩者齊備原則**：幾何若定義 `purpose`，`render` 與 `proxy` 必須兩者齊全；無 Proxy 代理網格則一律保持為 `default`，防止 Viewport 與農場渲染顯示不同步。
- **Viewport 降載首選 ModelAPI DrawMode**：`purpose` 為全域性切換，而 **USD ModelAPI 的 `drawMode`**（`bounds`, `cards`）可針對個別 Component 或 Assembly 獨立降級顯示，是釋放 Viewport 與顯存壓力的最核心手段。
- **Pipeline 嚴格維護 `usdkind`**：ModelAPI 的階層選取與 DrawMode 機制 100% 依賴 `kind` 元數據（`component`, `group`, `assembly`）。Pipeline 所有輸出與驗證工具必須在任何時候全力維護 `kind` 規則，確保 ModelAPI 能力正常運作。詳見：[USD Asset Layer 架構設計](docs/usd-asset-layer.md)。

---

## 👥 部門協同與閱讀導引

各專業崗位可依下列推薦順序研讀本體系筆記：

| 專業崗位 | 核心推薦閱讀篇目 | 實踐重點 |
| :--- | :--- | :--- |
| **Pipeline / TD / 架構師** | 全部 8 篇（著重於 [USD 發布封裝、路徑邊界與進版解析架構](docs/usd-publish-packaging.md)、[USD Asset Loader 工具架構設計](docs/usd-asset-loader.md)、[USD Solaris Implicit Layer 治理與輸出指南](docs/usd-solaris-implicit-layer.md)、[USD Shot Layers 鏡頭分層與覆寫架構](docs/usd-shot-layers.md)） | 掌握包裝邊界驗證、Solaris ROP 配置、Implicit Layer 輸出治理、Asset Resolver 鎖定邏輯與發布 Hook。 |
| **Model / Lookdev TD** | [USD Asset Layer 架構設計](docs/usd-asset-layer.md)、[USD 發布封裝、路徑邊界與進版解析架構](docs/usd-publish-packaging.md) | 理解幾何與材質雙層解耦、Model/Look VariantSet 封裝、以及 `/ROOT` 命名規範。 |
| **Layout / Set Dresser** | [USD Asset Loader 工具架構設計](docs/usd-asset-loader.md)、[USD Environment 與 Set Dressing 場景陳設架構設計](docs/usd-environment-setdressing.md)、[USD Solaris Implicit Layer 治理與輸出指南](docs/usd-solaris-implicit-layer.md)、[USD Asset Layer 架構設計](docs/usd-asset-layer.md) | 掌握 Loader Query/Load 擺放實務、Assembly 虛擬組裝、跨鏡頭 Set Asset 複用、`PointInstancer` 海量散佈優化、與避免 multi-input 產生外溢隱式圖層。 |
| **Animator / Rigging TD** | [USD Animation Layer 動態架構設計](docs/usd-animation-layer.md)、[USD Skel 骨架動畫設定指南](docs/usd-skel-guide.md) | 掌握 `geo` + `skel` + `animation` 三分法，避免輸出全幾何快取，規範 SkelRoot 邊界。 |
| **FX Artist / TD** | [USD FX Layer 鏡頭特效層架構設計](docs/usd-fx-layer.md)、[USD Shot Layers 鏡頭分層與覆寫架構](docs/usd-shot-layers.md) | 掌握 `/ROOT/FX/<element_name>` 註冊名掛載、獨立元素自帶 `/ROOT`、以及角色隱藏接管機制。 |
| **Lighting / Render TD** | [USD Shot Layers 鏡頭分層與覆寫架構](docs/usd-shot-layers.md)、[USD 發布封裝、路徑邊界與進版解析架構](docs/usd-publish-packaging.md) | 掌握頂層權限覆寫、Light Linking、跨部門稀疏材質微調、與算圖版本鎖定（Pinning）。 |

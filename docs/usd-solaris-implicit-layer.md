# USD：Houdini Solaris Implicit Layer 輸出與治理指南

在 Houdini Solaris（LOP）架構中，節點網路在記憶體中建構 Stage 時，會因應節點操作即時衍生出大量的記憶體虛擬圖層 **Implicit Layers（隱式圖層）**。

許多藝術家在點擊 USD ROP 輸出時，經常遭遇「莫名其妙導出一大堆碎檔（`.usd`）」、「路徑外溢散落在專案目錄各處」等災難。本篇旨在澄清 Implicit Layer 的生成本質，建立從 「**主動 Flatten**」、「**Configure Layer 顯式化（Explicit）**」 到 「**Save Paths Relative to Output 防禦收斂**」 的完整治理體系。

---

> [!IMPORTANT]
> **30 秒核心思維**
> 1. **核心目標並非「盲目阻擋 Implicit Layer 輸出」**：而是**利用 Solaris 盡量 Flatten（打平）所有的 Implicit Layer**；對於結構上無法被 Flatten 的圖層，則需受控地導出。
> 2. **無法 Flatten 時的自動轉換**：當節點網路結構包含跨圖層引用或特定層級覆寫時，Houdini 為了符合 OpenUSD 規範，**會在輸出時自動將無法 Flatten 的 Implicit Layer 轉換為磁碟實體檔案（Explicit Layer）**。
> 3. **輸出目錄第一道防線**：必須啟用 **Save Paths Relative to Output**，強制將所有自動轉換生成的子檔案約束在目標目錄的子資料夾（如 `./layers/`）內，嚴禁散落外溢。
> 4. **最佳解法是源頭顯式化**：教導製作人員學會使用 `Configure Layer` 節點主動設定 Save Path，將隱式匿名層顯式化（Explicit Layer），從根源掌控檔案產出。
> 5. **流程工具配合預先防禦**：在點擊輸出前，配合 Pipeline 流程工具（Scene Checker）檢視 Stage 與圖層的 Save Path，預先發現並修正問題，避免到了輸出階段才中斷。
> 6. **Output Processor 最終守衛**：在 USD ROP 掛載自訂 Output Processor 作為最後防線，偵測到路徑不符規範即拋錯中斷，但因走到此步已是輸出末期代價較大，故前兩道防禦才是治本之道。
> 7. **部門風險差異**：Asset/FX 組流程天然直接打平，風險極低；Layout 組因濫用 `SOP Create/Modify` 與 multi-input 合併節點，為重災區。

---

## 1. 為什麼 Houdini 會自動產生外部 Layer 檔案？

### 1. OpenUSD 的圖層不可變性（Layer Immutability）
OpenUSD 的核心哲學之一是**非破壞性堆疊（Composition Arcs）**。當多個圖層之間存在複雜的弱強覆寫（Sublayer）、引用（Reference）或變體（Variant）時，USD 在底層無法將它們隨意壓扁成單一檔案，否則會破壞意見優先權（LIVRPS）。

### 2. 記憶體虛擬層 → 磁碟實體化（Bake / Materialization）
在 Solaris 視圖中，藝術家透過節點拉出了一棵看似完整的場景樹，但**背後其實是由許多匿名的記憶體隱式圖層（Anonymous Implicit Layers）動態拼裝而成**。

當你透過 USD ROP 執行導出時：
```text
[Solaris 記憶體節點網路]
SOP Create ──► Merge (Separate Layers) ──► Reference ──► USD ROP
    │                   │                      │              │
 (Implicit)          (Implicit)            (Implicit)         ▼
                                                       【輸出磁碟時】
                                                       Houdini 發現無法完全打平
                                                       ▼
                                     ┌─────────────────┴─────────────────┐
                                     ▼                                   ▼
                           main.usd (主入口)                   ./layers/sublayer_01.usd (自動具現化)
```
如果某些結構在 USD 規格中**無法被打平（Flatten）**，Houdini 為了維持 Stage 的正確性，會在後台自動將這些隱式圖層儲存為實體檔案，並在主檔案中將其作為 sublayer 或 reference 引用進來。

---

## 2. 輸出目錄防禦底線：Save Paths Relative to Output

藝術家如果不理解上述轉換機制，且 ROP 設定不當，Houdini 就會根據預設規則或使用者設定，把自動生成的圖層寫入系統暫存區（如 `C:/temp`）、Houdini 暫存目錄、或是個人工作目錄，導致整個發布包嚴重殘缺、外包或渲染農場算圖必定壞鏈。

### USD ROP 必備設定規範

在所有的 USD ROP（或 USD Output Processor）配置中，必須嚴格落實以下規則：

```text
USD ROP (Output Processor)
├── Output File: /projects/.../publish/sets/livingroom/v001/livingroom.usd
├── Save Path Mode: Relative to Output File
└── Sublayer/Anonymous Directory: ./layers/
```

1. **Save Paths Relative to Output**：
   - 告訴 Houdini：「所有你逼不得已必須自動轉換、輸出的隱式圖層，其磁碟路徑一律以主輸出檔（Output File）為相對起點」。
2. **約束在子目錄（`./layers/`）內**：
   - 所有生成的輔助圖層必須統一集中在目標輸出目錄底下的 `./layers/` 或 `./sublayers/` 子資料夾內。
   - 確保整個發布目錄（`v001/`）依然維持完整的封裝原子性（Packaging Unit），包內相對引用，搬移不壞。

---

## 3. 根治手段：主動顯式化（Explicit Layer Conversion）

單純依賴 ROP 的自動防禦是不夠的，因為自動產生的檔名通常極度混亂（如 `anon_0x7f8a9b0c.usd` 或 `implicit_sublayer_1.usd`），不利於版本控制與排錯。

**正確的 Pipeline 實踐是：主動利用 `Configure Layer` 節點，在節點網路中將隱式圖層轉換為 Explicit Layer。**

### `Configure Layer` 節點的核心用法

在節點網路中，當你引入了新的圖層分支時，應緊接著接上 `Configure Layer` 節點：

```text
[SOP Import / 外部幾何]
         │
[Configure Layer]  <-- 【關鍵節點】
         │              ├── Save Path: ./layers/table_mesh.usd
         │              ├── Default Prim: /ROOT
         │              └── Mute / Layer Metadata
         ▼
[下游組裝網路]
```

1. **明確指定 Save Path**：
   - 在節點參數中的 **Save Path** 欄位填入明確的相對路徑（例如 `./layers/prop_geometry.usd`）。
   - 這樣一來，該圖層不再是「未知的隱式圖層」，而是「**具備明確身分的顯式圖層（Explicit Layer）**」。
2. **自訂檔案命名與語意**：
   - 發布出來的檔案不再是匿名亂數，而是具備清楚業務含義的子圖層檔案（如 `table_mesh.usd`、`materials.usd`）。
3. **消除 ROP 的猜測行為**：
   - ROP 導出時直接讀取你在 `Configure Layer` 中指定的目標路徑，精準落地，零意外。

---

## 4. Pipeline 的縱深防禦：Output Processor 守衛與三層防禦體系

### 4.1 核心困境：為什麼 Pre-publish Hook 在節點階段難以完全防禦？

許多 Pipeline TD 的第一反應是：「我在發布前寫一個 Pre-publish Hook 腳本，在節點圖上檢查只要有 Implicit Layer 就報錯阻擋，不就解決了？」

在實務上，**這點極其困難且容易引發誤判**，原因如下：

1. **決策發生在 Output 階段（Late Binding）**：
   - 在 Solaris 記憶體網路中，幾乎「處處都是 Implicit Layer」。節點圖在執行 ROP 寫入硬碟之前，尚未經過 Output Processor 的解析與轉換。
   - 哪些圖層會被 Flatten？哪些會被分離寫出？完全取決於 ROP 的 **Save Style**（Flatten Stage、Flatten Layers、Separate Layers）與 Output Processor 的內部邏輯。
2. **無法單純從節點拓撲預知落地行為**：
   - 在節點網路層面，Hook 很難精準判定「這個記憶體圖層在寫入磁碟時，到底會被完美打平成單一檔，還是會分裂成實體外部檔」。
3. **過度阻擋會扼殺合法流程**：
   - 某些複雜的 Shot Overrides 或 Multi-Layer 本來就合理需要拆分為子圖層；若在節點圖上一律盲目阻擋隱式層，會導致正常作業完全無法進行。

---

### 4.2 終端攔截手段：Solaris Output Processor 雙重職責 (守衛與路徑改寫)

既然節點圖難以預測，另一種在 Pipeline TD 之間常見且強大的手段是：**利用 Houdini Solaris 的自訂 Output Processor**。

在工業級 Pipeline 中，自訂 Output Processor 肩負兩大核心任務：

1. **路徑合法性守衛（The Safety Net）**：
   - 逐一比對每個圖層的目標磁碟路徑：是否位在當前任務所允許的發布資料夾底下的 `./layers/` 子目錄？
   - **一旦偵測到輸出路徑不符規範（例如產生未規範的匿名圖層實體化檔、或路徑外溢到非預期資料夾），立即拋出例外中止輸出（Abort Export）**。
2. **專案根目錄替換為 Stage Expression Variable（可攜性保證）**：
   - 掃描所有外連圖層的絕對路徑，凡命中目前專案根目錄（如 `/projects/show_A/`）者，自動改寫為 `@${PROJ_ROOT}/...@`。
   - 同時在導出的 Layer Metadata 中宣告預設的 `expressionVariables = { string PROJ_ROOT = "..." }`，使整批發布的 USD 在未來專案搬遷或交接客戶時，能透過最外層 Wrapper 圖層一鍵全局覆寫。

* **致命痛點（為什麼仍需前置防禦）**：
  - **輸出已至最後階段**：當 Output Processor 觸發時，通常已經點擊了 Render / Export，甚至場景已經送往 Farm 進行背景算圖。
  - **代價高昂且體驗極差**：若單靠 Output Processor 守衛，經過長時間的計算與排隊後在最後一刻拋錯中止，會造成算圖資源浪費與藝術家嚴重的挫折感。因此它定位為「安全底線」，而非日常唯一手段。

---

### 4.3 最佳實踐：三層縱深防禦體系 (Three-Tier Defense Architecture)

因此，工業級 Pipeline 的最佳解法絕非單靠終端的 Output Processor 攔截，而是建立「**源頭教育 → 流程前置檢視 → 終端守衛**」的三層縱深防禦體系：

```
[第一道防線：製作人員教育 (源頭治理)]
  └─ 最佳解法：學會使用 Configure Layer 主動將隱式層轉為 Explicit Layer
       │
       ▼
[第二道防線：流程工具前置檢視 (預先防禦)]
  └─ 輸出前透過 Scene Checker / Layer Inspector 檢視 Stage 圖層 Save Path，提早預警
       │
       ▼
[第三道防線：Output Processor 守衛 (終端底線)]
  └─ ROP 導出時攔截非法路徑並拋錯中斷，防止髒資料外溢污染發布目錄
```

#### 第一道防線：製作人員心智模型重塑（最佳解法）
- **核心思維**：治本之道永遠是教導製作人員正確理解圖層行為。
- **實踐做法**：推廣「隱式轉換為顯式（Explicit）」的觀念。製作人員在創作階段只要使用 `SOP Create`、`SOP Modify` 或特殊分支，就必須主動接上 `Configure Layer` 明確指定 Save Path。將圖層命運由自己掌控，而非交由 Houdini 猜測。

#### 第二道防線：流程工具配合預先防禦（Pre-flight Inspection）
- **核心思維**：不要等到按下 Render 才發現錯誤，要在創作介面即時給予反饋。
- **實踐做法**：
  1. **發布前檢核面板（Pre-publish / Scene Checker）**：藝術家提交發布前，工具自動走訪當前 Stage 的圖層清單。
  2. **檢視 Explicit Layer 的 Save Path**：檢查已設定的儲存路徑是否符合 `./layers/<name>.usd` 的命名規範與子目錄層級。
  3. **未顯式化圖層預警**：若偵測到 Stage 內存在大量未具備 Save Path 的 SOP/Merge 匿名節點分支，工具提前以醒目黃字警告：「偵測到潛在未打平之隱式圖層，請確認是否需使用 Configure Layer 顯式化或設置 Flatten 模式」，並提供「一鍵輔助設置」功能。

#### 第三道防線：Output Processor 終端守衛（Fail-Safe Barrier）
- **核心思維**：最後一根安全帶，寧可中斷報錯，也絕不容許非法檔案落地污染專案 Asset 庫。
- **實踐做法**：掛載 Pipeline 自訂 Output Processor。若前兩道防線因特殊意外被繞過，Output Processor 在底層硬性核查，一旦發現外溢路徑立即拋錯，確保發布目錄的絕對純淨。

---

## 5. 各部門風險差異與實戰治理策略

### 1. Asset 組 & FX 組：天然低風險區

這兩個部門在 Solaris 中的流程通常具備高度線性與獨立性，幾乎不需要過度防禦：

* **Asset 部門**：
  - 標準輸出模式本來就是追求乾淨的組件。
  - 通常嚴格遵守 `model.usd`（幾何）與 `look.usd`（材質）的結構，在內部組裝時多採用 **Flatten** 或極度明確的兩層 Sublayer。
  - 只要 SOP Import 妥善設定，極少產生非預期的隱式分離。
* **FX 部門**：
  - FX 產出的本體是 VDB 快取、BGEO 點雲或剛體快取。
  - 特效元素通常以自帶 `/ROOT` 的獨立單元發布，引入時多採用直接的 **Explicit Reference** 或 **Payload**。
  - 流程非常單純，只要在 `SOP Import` 節點中規範好圖層儲存設定，就能避免 95% 以上的狀況。

---

### 2. Layout / Set Dressing 組：隱式圖層爆發的「重災區」

Layout 與場景陳設組在製作環境（Environment）時，是 Pipeline 中最容易出問題的部門。

#### 常見四大災難操作：
1. **過度依賴 `SOP Create` 與 `SOP Modify`**：
   - 藝術家習慣在 Solaris 內部直接拉 `SOP Create` 捏幾何、排地表碎石，或用 `SOP Modify` 隨手刷權重。
   - 這些節點會在背後生成大量依附於特定影格與時間點的匿名 Implicit Layers，且藝術家往往不主動管理。
2. **濫用 `Merge` 節點的預設模式**：
   - `Merge` 節點預設或常被設為 **Separate Layers** 模式。
   - 每次 Merge 都在記憶體中憑空新增一個 Sublayer；若合併了 10 個道具分支，記憶體中就累積了 10 個隱式圖層。
3. **Multi-input `Reference` 與 `Sublayer` 節點未規範**：
   - 同時拉入多條 Pipeline 分支，節點網路層層嵌套，沒有明確的根 Prim 宣告。
4. **輸出時完全不手動處理**：
   - 最終直接拉一顆 USD ROP 點擊輸出，Houdini 在背後執行拓撲分析時發現無法打平，瞬間向硬碟寫出 20～30 個雜亂的匿名 `.usd` 檔案。

---

## 6. Layout 部門的標準防禦與操作規範 (SOP)

針對 Layout / Set Dressing 部門，Pipeline 應確立以下作業標準：

### 規則一：環境組裝優先使用 Flatten 模式
在 Layout 中使用 `Merge` 節點匯整多個擺設或 Asset 時：
- **操作要求**：將 `Merge` 節點的參數設置為 **Flatten Layers**（打平圖層），除非該分支有明確的獨立覆寫需求。
- **效果**：強制在記憶體中將多個分支合併為單一圖層，從源頭消除多餘的隱式層。

### 規則二：SOP 產物必須經由 `Configure Layer` 明確落實
若場景中確實需要在 Solaris 中直接建立地形或道具（`SOP Create` / `SOP Import`）：
- **操作要求**：禁止直接將 SOP 節點連入最終總成。必須在 SOP 輸出後立即連接 **`Configure Layer`** 節點。
- **設定標準**：明確定義 `Save Path` 為 `./layers/<prop_name>_geo.usd`，將其轉換為可控的 Explicit Layer。

### 規則三：Set Dressing 全面虛擬化（零幾何實體）
- **操作要求**：禁止在 Layout 檔案內烘焙實體多邊形。環境中的所有樹木、家具、建築，一律透過外部發布之 Asset 以 `Reference` 或 `Payload` 載入。
- **大量散佈**：使用 `PointInstancer` 節點消費點雲，原型（Prototypes）直接參照外部 Asset，保持 Stage 內部純淨。

---

## 7. Pipeline 治理檢核清單 (Checklist)

| 防線層級 / 環節 | 檢查項目 | 合格標準 |
| :--- | :--- | :--- |
| **第一防線（製作源頭）** | 節點管理（`SOP Create/Modify`） | 必須銜接 `Configure Layer` 明確指派 Save Path 轉為 Explicit Layer |
| **第一防線（製作源頭）** | 合併節點（`Merge`）模式 | 靜態陳設組裝預設採用 **Flatten Layers** 模式，避免多餘隱式分支 |
| **第二防線（流程前置工具）** | Scene Checker / Layer Inspector | 輸出前以 [`layer_inspector.py`](../tools/layerinspector/README.md) 掃描 Stage 圖層清單，檢查 Explicit Layer Save Path 是否符合規範 |
| **第二防線（流程前置工具）** | 未顯式化圖層提早預警 | 以 [`layer_inspector.py`](../tools/layerinspector/README.md) 檢出無 Save Path 的匿名 SOP/Merge 分支，追查建立節點並即時提示藝術家修正 |
| **第三防線（ROP 基礎設定）** | Save Path Mode | 強制鎖定為 **Relative to Output File**，收斂於 `./layers/` |
| **第三防線（Output Processor）** | 終端路徑合法性守衛 | 掛載 [`portablereferences.py`](../tools/outputprocessors/README.md) 確保包內相對路徑與邊界收斂，攔截違規外溢 |
| **發布驗證（磁碟驗收）** | Post-Export 磁碟目錄掃描 | 目標輸出資料夾之外，不得有任何關聯圖層外溢 |

---

## 🔗 相關手冊與工具導讀
- **[USD 架構設計體系總覽與導讀](../README.md)**：全 Pipeline 架構地圖與六大核心鐵律
- **[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)**：通用目錄封裝規範、內相對外絕對與進版解析
- **[Houdini Solaris Layer Inspector 檢測工具庫](../tools/layerinspector/README.md)**：第二防線前置圖層檢查實作腳本（`layer_inspector.py`）
- **[Houdini Solaris Output Processors 實作工具庫](../tools/outputprocessors/README.md)**：第三防線輸出處理參考腳本（`portablereferences.py`、`projectrootvariable.py`）
- **[USD Environment 與 Set Dressing 場景陳設架構設計](usd-environment-setdressing.md)**：Layout / Set Dressing 虛擬組裝與點雲實例化架構
- **[USD Shot Layers 鏡頭分層與覆寫架構](usd-shot-layers.md)**：鏡頭頂層四大部門圖層順序與覆寫權重機制

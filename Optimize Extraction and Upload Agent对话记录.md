# Chat Conversation

Note: _This is purely the output of the chat conversation and does not contain any raw data, codebase snippets, etc. used to generate the output._

### User Input

我正在尝试进行开源游戏《Space Station 14 (SS14)》的自动化汉化项目，我是一个毫无代码基础，且没有太多vibe coding经验的新手。
游戏原文绝大多数采用硬编码，存储在大量 YAML 文件中，少量则是使用.ftl文件方便进行i18n，使用了大量标签（如 `name`, `description` 等）。
我的目标是构建一个基于Paratranz和github的持续本地化工作流。

已有资源：
1.  上游仓库 (Read-only): `https://github.com/Monolith-Station/Monolith` (游戏源文件)
2.  我的仓库 (Maintain):`https://github.com/Sinotrasen14/Monolith-CN` (存放脚本、汉化文件和 Action)
3.  翻译平台: Paratranz (PZ)
4.  旧的翻译工具: 我手头有一个 Python 编写的本地翻译工具（v1.40），原先目的是作为单独的API接口汉化工具，将单独的yaml硬编码的英文文本翻译并生成新的yaml文件，不具备协作能力，且相对来说属于重复造轮子。

我个人精力有限，无法单独用工具完全处理，因此打算开一个paratranz项目，同时网站上的术语表和翻译记忆库都很利于多人协作和一致性。但现在我对于如何对接github和paratranz，如何在paratranz上更新的维护不太熟悉。

目前我用AI总结出了一个大概的方案和流程，内容如下：
```
架构与工作流设计：
我需要实现一个全自动的GitHub和paratranz工作流程：
提取游戏文本 -> 打包至 ParaTranz -> 人工汉化 -> 定期拉取汉化文件至 GitHub -> 更新服务器文件

游戏yaml文件实例：
<游戏yaml文件>
- type: entity
  parent: [ClothingBackpack, BaseChameleon]
  id: ClothingBackpackChameleon
  name: backpack
  description: You wear this on your back and put items into it.
  suffix: Chameleon
  components:
    - type: Tag
      tags: [] # ignore "WhitelistChameleon" tag
    - type: Sprite
      sprite: Clothing/Back/Backpacks/backpack.rsi
    - type: ChameleonClothing
      slot: [back]
      default: ClothingBackpack
    - type: UserInterface
      interfaces:
        enum.StorageUiKey.Key:
          type: StorageBoundUserInterface
        enum.ChameleonUiKey.Key:
          type: ChameleonBoundUserInterface

- type: entity
  parent: [Clothing, ClothingSlotBase]
  id: ClothingBackpackWaterTank
  name: backpack water tank
  description: Holds a large amount of fluids. Supplies to spray nozzles in your hands, and has a slot on the side for said spray nozzles.
  components:
  - type: Tag
    tags:
    - NozzleBackTank
    - WhitelistChameleon
  - type: Sprite
    sprite: Clothing/Back/Backpacks/waterbackpack.rsi
    state: icon
  - type: Item
    size: Ginormous
  - type: Clothing
    slots: BACK
    sprite: Clothing/Back/Backpacks/waterbackpack.rsi
  - type: ItemSlots
    slots:
      item:
        priority: 2
        whitelist:
          tags:
          - SprayNozzle
  - type: ItemMapper
    mapLayers:
      icon-filled:
        whitelist:
          tags:
            - SprayNozzle
  - type: Appearance
  - type: SolutionAmmoProvider
    solutionId: tank
    proto: BulletWaterShot
  - type: SolutionContainerManager
    solutions:
      tank:
        maxVol: 1000 #much water
  - type: SolutionTransfer
    transferAmount: 50
    maxTransferAmount: 100
    minTransferAmount: 10
    canChangeTransferAmount: true
  - type: UserInterface
    interfaces:
      enum.TransferAmountUiKey.Key:
        type: TransferAmountBoundUserInterface
  - type: DrawableSolution
    solution: tank
  - type: RefillableSolution
    solution: tank
  - type: DrainableSolution
    solution: tank
  - type: ExaminableSolution
    solution: tank
    exactVolume: true

    # 其中name和description是游戏原文，其他是游戏文件的结构和标签,id通常可作为唯一key，但存在其他物品引用物品id的情况。
</游戏yaml文件>

paratranz支持json，csv等文件，不支持yaml。以下是paratranz支持的json文件格式：
<paratranz格式>
# original:网站上显示的翻译原文
# translation：导入原文后空缺，直到导入新翻译或是有译文
# context：网站的上下文功能，可自定义内容，如cdda翻译项目中的文件来源
 [
  {
    "key": "842d1bbc201c734b7a2ef557e940b1ab",
    "original": "游戏原文1",
    "translation": "一",
    "stage": 5,
    "context": "ID: style_niten\n位于 /Kenan-Structured-Modpack/CBMArms/martialarts.json\n类型为 martial_art\n\nWIKI:\nhttps://onetwo.ren/CDDA-Kenan-Modpack-Chinese/#CBMArms→martial_art→style_niten\n物品浏览器：\nhttp://cdda.aloxaf.cn/search?q=style_niten"
  },
  {
    "key": "47540830cfa149067a9c8cfd8aab48a0",
    "original": "游戏原文2",
    "translation": "二",
    "stage": 5,
    "context": "ID: style_silat\n位于 /Kenan-Structured-Modpack/CBMArms/martialarts.json\n类型为 martial_art\n\nWIKI:\nhttps://onetwo.ren/CDDA-Kenan-Modpack-Chinese/#CBMArms→martial_art→style_silat\n物品浏览器：\nhttp://cdda.aloxaf.cn/search?q=style_silat"
  }
]
在paratranz上的文件顺序是按照json文件中从上到下排序的，即游戏原文1在前，游戏原文2在后。
</paratranz格式>

现在我的目标是这个工作流要具有良好的可维护性，且操作能够实现提取和合并的自动化。以专业程序员和规划角度，在代码和工作流程上，上述的内容如何？是否有补充或更好的方案？以及结合当前这个py工具，是否存在可重复利用或可以用于编写所需脚本的内容？

*Listed directory [yaml汉化工具](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7) *

*Viewed [# YAML批量AI本地化工具 v1.40.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/%23%20YAML%E6%89%B9%E9%87%8FAI%E6%9C%AC%E5%9C%B0%E5%8C%96%E5%B7%A5%E5%85%B7%20v1.40.py) *

*Listed directory [.github](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github) *

*Listed directory [workflows](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows) *

*Viewed [localization.yml](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows/localization.yml) *

*Listed directory [yaml汉化工具](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7) *

*Edited relevant file*

### User Input

我找了一下同行的github关于如何同步github和paratranz工作流的教程：https://github.com/VM-Chinese-translate-group/Template-Repo
以下为他们工作流代码：

<Paratranz To GitHub>
```
Workflow file for this run
.github/workflows/upload2paratranz.yml at 1fa0266
name: Upload Action

on:
  workflow_dispatch:

jobs:
  upload:
    name: Upload
    environment: PARATRANZ_ENV
    runs-on: ubuntu-latest
    env:
      API_TOKEN: ${{ secrets.API_KEY }}
      FILE_PATH: ./
      PROJECT_ID: ${{ vars.ID }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install git+https://github.com/MuXiu1997/ParaTranz-SDK-python.git
          pip install PyGithub
      - name: Upload To Paratranz
        run: |
          python .github/workflows/github2para.py
```

Upload Action
```
Workflow file for this run
.github/workflows/upload2paratranz.yml at 1fa0266
name: Upload Action

on:
  workflow_dispatch:

jobs:
  upload:
    name: Upload
    environment: PARATRANZ_ENV
    runs-on: ubuntu-latest
    env:
      API_TOKEN: ${{ secrets.API_KEY }}
      FILE_PATH: ./
      PROJECT_ID: ${{ vars.ID }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install git+https://github.com/MuXiu1997/ParaTranz-SDK-python.git
          pip install PyGithub
      - name: Upload To Paratranz
        run: |
          python .github/workflows/github2para.py
```
</Paratranz To GitHub>

还有另一个项目实例：
<实例文件2>
```
Add workflow [Quest Book To Paratranz]
MuXiu1997 committed on Oct 21, 2022 
commit f70c9b44fef27126d64617bafe66921ba9b13c57
 69 changes: 69 additions & 0 deletions69  
.github/workflows/1-quest-book-to-paratranz.yml
Original file line number	Diff line number	Diff line change
@@ -0,0 +1,69 @@
name: Quest Book To Paratranz

on:
  issues:
    types: [ opened ]

env:
  PARATRANZ_TOKEN: ${{ secrets.PARATRANZ_TOKEN }}
  PARATRANZ_PROJECT_ID: ${{ secrets.PARATRANZ_PROJECT_ID }}

jobs:
  check-and-parse-issue:
    if: contains(github.event.issue.labels.*.name, '自动化:questbook→paratranz')
    name: Check And Parse Issue
    runs-on: ubuntu-latest
    steps:
      - name: Checkout MuXiu1997/GTNH-translation-compare
        uses: actions/checkout@v3
        with:
          repository: MuXiu1997/GTNH-translation-compare
          ref: rework
      - name: Ensure Dependencies
        uses: ./.github/actions/ensure-dependencies
      - name: Run Script
        id: check-and-parse-issue
        env:
          GITHUB_ISSUE: ${{ toJSON(github.event.issue) }}
          VALID_LABEL: 自动化:questbook→paratranz
          VALID_USER: ${{ github.repository_owner }}
        run: |
          poetry run python main.py parse-issue quest-book-to-paratranz
    outputs:
      passed: ${{ steps.check-and-parse-issue.outputs.passed }}
      commit-sha: ${{ steps.check-and-parse-issue.outputs.commit-sha }}

  close-issue:
    name: Close Issue
    needs: check-and-parse-issue
    if: ${{ needs.check-and-parse-issue.outputs.passed != 'true' }}
    runs-on: ubuntu-latest
    steps:
      - name: Close Issue
        uses: peter-evans/close-issue@v2.0.0
        with:
          comment: |
            此模板仅由内部人员使用，已自动关闭。
  quest-book-to-paratranz:
    name: Quest Book To Paratranz
    needs: check-and-parse-issue
    if: ${{ needs.check-and-parse-issue.outputs.passed == 'true' }}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout MuXiu1997/GTNH-translation-compare
        uses: actions/checkout@v3
        with:
          repository: MuXiu1997/GTNH-translation-compare
          ref: rework
      - name: Ensure Dependencies
        uses: ./.github/actions/ensure-dependencies
      - name: Run Script
        run: >-
          poetry run python main.py action quest-book-to-paratranz
          --commit-sha='${{ needs.check-and-parse-issue.outputs.commit-sha }}'
      - name: Close Issue
        uses: peter-evans/close-issue@v2.0.0
        with:
          comment: |
            已自动同步至 Paratranz。
```
</实例文件2>

这两个文件对于我的项目有什么信息补充或帮助吗？

*Edited relevant file*

### User Input

开始创建

*User accepted the command `mkdir scripts`*

*Edited relevant file*

*Edited relevant file*

### User Input

Continue

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*User accepted the command `python scripts/extract.py --help`*

*User accepted the command `python scripts/extract.py --target_folders . --output test_extract.json`*

*Edited relevant file*

### User Input

GitHub 仓库Secrets已添加，以及我的Paratranz 项目ID为16648。同时我看到脚本测试是使用指令，能否加入.bat或是其他更加方便的文件来一键操作？最后请输出一份适合我这种小白的操作指南。

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

运行1_提取文本.bat后显示如下：
```
Active code page: 65001
正在提取游戏文本...
[20:41:44] [INFO] Scanning directory: Content
[20:41:44] [INFO] Extraction complete. Processed 0 files, found 0 strings.
[20:41:44] [INFO] Saved to en.json

提取完成！文件已保存为 en.json
你可以将此文件上传到 Paratranz。
Press any key to continue . . .
```
生成了一个只有[]的en.json.

content文件夹是什么东西，是我要自己新建一个吗？

游戏文件里那些物品文件主要分布在F:\Github\Monolith-CN\Resources\Prototypes里，我要怎么提取？

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

Continue

*Listed directory [yaml汉化工具](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7) *

*Edited relevant file*

### User Input

作为一个小白，一个个指令去点有点麻烦，能否实现更好看的操作界面，比如图形化之类的，同时要能够保存设置和选择记录。

提取原文能不能自己指定目录？因为不只是Prototypes，其他地方可能也有文件要处理。

同时“合并翻译”要具有足够的稳健性和准确性，要有能够正确合并到对应的文件的能力。

同时代码注释必须使用中文进行

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

把前面的脚本或代码检查一遍，把注释全部改为中文

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

我看到有很多零散的代码，能否整合其中的一部分，减少文件数量？可以先讨论可行性

### Planner Response

### 可行性分析：合并代码文件

完全可行。目前为了模块化（编程习惯），我把功能拆分得很细。考虑到你希望减少文件数量，我们可以进行“**终极整合**”。

#### 建议方案：单文件全能模式 (`ss14_tracker.py`)

我们可以把所有的 Python 脚本（[extract.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/scripts/extract.py:0:0-0:0), [merge.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/scripts/merge.py:0:0-0:0), [pz_client.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/scripts/pz_client.py:0:0-0:0), [utils.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/scripts/utils.py:0:0-0:0), [yaml_utils.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/scripts/yaml_utils.py:0:0-0:0) 甚至 [gui_launcher.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/gui_launcher.py:0:0-0:0)）整合进**唯一的一个** [.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/gui_launcher.py:0:0-0:0) 文件中，例如命名为 `ss14_tracker.py`。

这个文件将具备“双重人格”：
1.  **双击运行 (GUI模式)**: 当你不带参数直接运行它时，它会弹出图形界面，供你在本地操作。
2.  **带参数运行 (命令行模式)**: 当 GitHub Actions 调用它时（例如 `python ss14_tracker.py extract ...`），它会像旧脚本一样默默执行任务。

#### 优点
*   **极致简洁**: 你的 `scripts/` 文件夹将消失，只有一个 `ss14_tracker.py`。
*   **维护方便**: 不用担心文件路径引用错误，拖着这一个文件到处跑都行。
*   **配置简单**: 它可以把配置直接保存在同目录下的 `config.json`，没有路径困扰。

#### 缺点
*   **文件较长**: 这个文件可能会有 500-600 行代码（但对你来说无所谓，反正不用看）。

#### 操作计划
如果你同意，我将：
1.  创建新的 `ss14_tracker.py`。
2.  将所有逻辑迁移进去。
3.  修改 [.bat](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/Start_GUI.bat:0:0-0:0) 文件和 [localization.yml](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows/localization.yml:0:0-0:0) 以指向这个新文件。
4.  删除旧的 `scripts/` 文件夹。

是否执行这个整合方案？

### User Input

执行

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

*Viewed [localization.yml](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows/localization.yml) *

*Edited relevant file*

*Edited relevant file*

*User accepted the command `Remove-Item -Path "scripts" -Recurse -Force; Remove-Item -Path "gui_launcher.py" -Force`*

*Edited relevant file*

### User Input

请你检查项目所有内容和代码，以专业程序员和设计师的角度看看是否有可以优化的地方，是否能够更加智能且方便易用

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Listed directory [yaml汉化工具](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7) *

*Edited relevant file*

### User Input

This is a system-generated message that is sent due to the user's review policy. Proceed with the decision that you think is the most optimal here.

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

编写一份新的适合小白的使用指南吧

*Edited relevant file*

### Planner Response

新的使用说明已经编写完成！这份指南专为小白用户设计，包含：

- **清晰的步骤编号** - 按安装 → 使用的顺序引导
- **一键同步重点突出** - 推荐最简单的操作方式
- **表格速查** - 快速了解各选项卡功能
- **常见问题解答** - 预防用户遇到的典型问题
- **表情符号** - 让文档更友好易读

你可以在 `使用说明.md` 中查看。

### User Input

接下来我要做什么？如何把这些内容变成一个项目？

### Planner Response

为了将你现在的这些代码和工具正式变成一个**长期运行的项目**，你需要完成从“本地文件夹”到“GitHub 仓库”的跨越。

以下是你接下来的**项目上线四部曲**：

### 第一步：文件大迁移（整理行装）
不要直接在桌面运行工具。你应该将目前文件夹下（`f:\Desktop\ss14翻译\yaml汉化工具`）的所有核心内容复制到你的游戏汉化仓库根目录（例如 `F:\Github\Monolith-CN`）。

**需要迁移的文件清单：**
- [ss14_tracker.py](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py:0:0-0:0) (核心程序)
- `.github/` 文件夹 (自动化指令)
- `*.bat` 所有脚本 (本地快捷方式)
- [requirements.txt](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/requirements.txt:0:0-0:0) (环境依赖清单)
- `使用说明.md` (你的项目文档)

---

### 第二步：提交到 GitHub（建立基地）
打开你的 Git 管理工具（如 GitHub Desktop 或命令行），将这些新文件提交并推送到你的远程仓库。

1. **Commit**: 填写信息如 `Initialize localization toolkit v3.0`。
2. **Push**: 点击推送，让 GitHub 看到这些自动化文件。

> **注意**：一旦你推送了 [.github/workflows/localization.yml](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows/localization.yml:0:0-0:0)，GitHub 就会自动识别并准备运行自动化任务了。

---

### 第三步：配置“通关密钥”（安全授权）
这是最关键的一步，否则 GitHub 没有权限帮你上传/下载项目。

1. 打开浏览器，进入你的 GitHub 仓库页面。
2. 点击 **Settings** (设置) -> **Secrets and variables** -> **Actions**。
3. 点击 **New repository secret** (新建仓库密钥)。
4. **Name** 填写：`PARATRANZ_TOKEN`。
5. **Secret** 填写：你的 Paratranz Token 字符串。
6. 点击 **Add secret** 保存。

---

### 第四步：开启第一次“试飞”（验证成果）
1. 在仓库页面点击 **Actions** 选项卡。
2. 在左侧选择 **Continuous Localization**。
3. 点击右侧的 **Run workflow** 下拉按钮，点击绿色的 **Run workflow**。
4. **观察**：看它是否能顺利走完所有步骤（变绿勾）。如果这一步成功了，以后每天早上 8 点，它都会自动帮你干活！

---

### 🌟 作为一个“项目负责人”，你以后只需要：
- **本地翻译时**：双击 [Start_GUI.bat](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/Start_GUI.bat:0:0-0:0) 用一键同步，搞定后提交。
- **自动更新时**：偶尔上 GitHub 看看 Actions 有没有报错。
- **有人加入时**：把 `使用说明.md` 丢给他们看。

**恭喜！你已经从一个“手动翻译的小白”，变成了一个“拥有自动化汉化流水线的项目架构师”。** 

如果有哪里卡住了，随时告诉我！

### User Input

单独使用paratranz同步选项中的下载功能无法使用，且无论填什么都是连接测试成功，效果形同虚设。填入对应API token情况下报错信息也根本无法正常使用，只会反复显示以下内容：
❌ 操作失败，请检查上方日志。
而日记中根本什么也没有。

以下为paratranz的官方API接口文档中关于token的相关内容：
```
ParaTranz OpenAPI 文档
 0.5.0 
OAS 3.0
本文档介绍 ParaTranz.cn 平台的 API

获取 Token
首先需要获取API Token，可以在个人资料页面中的设置选项卡获取API Token， 调用 API 时将 Token 直接放在请求头的 Authorization 中即可。

cURL 使用示例:

$ curl --header "Authorization: Bearer {TOKEN}" https://paratranz.cn/api/projects
错误处理
API 返回的错误格式如下

{
  "message": "ERROR MESSAGE", // 错误消息
  "code": 10000 // 5位错误代码，注意与下面的HTTP状态码区分，部分接口不返回
}
HTTP状态码有以下几种类型

400 - 调用参数错误
401 - Token 错误或过期
403 - 没有相关权限
404 - 资源不存在
405 - 没有相关HTTP方法，一般为调用方法错误
429 - 调用过于频繁，具体频率限制请看上一节
500 - 服务器错误，一般会提供具体出错的位置，请发送给站长方便定位问题
502 - 服务器无响应，部分用户被墙时可能会遇到
503 - 服务不可用
504 - 服务超时，访问量大时会出现
```
以下为paratranz的官方API接口文档中
项目相关接口的相关内容：
```
Artifacts
导出压缩包及下载相关接口

GET
/projects/{projectId}/artifacts
导出结果


获取最近一次导出的结果

Parameters
Name	Description
projectId *
integer
(path)
项目ID

Example : 867

867
Responses
Code	Description	Links
200	
返回结果

Media type

application/json
Controls Accept header.
Example Value
Schema
{
  "id": 1001,
  "createdAt": "2021-01-11T03:19:52.818Z",
  "project": 1453,
  "total": 0,
  "translated": 0,
  "disputed": 0,
  "reviewed": 0,
  "hidden": 0,
  "duration": 0
}
No links

POST
/projects/{projectId}/artifacts
触发导出


手动触发导出操作，仅管理员可使用

Parameters
Name	Description
projectId *
integer
(path)
项目ID

Example : 867

867
Responses
Code	Description	Links
200	
返回结果

Media type

application/json
Controls Accept header.
Example Value
Schema
{
  "id": 1,
  "createdAt": "2021-01-11T03:19:52.818Z",
  "startedAt": "2021-01-11T03:19:52.818Z",
  "finishedAt": "2021-01-11T03:19:52.818Z",
  "scheduledAt": "2021-01-11T03:19:52.818Z",
  "params": {},
  "project": 1453,
  "uid": 0,
  "type": "string",
  "status": 0,
  "result": {}
}
No links
403	
没有权限

No links

GET
/projects/{projectId}/artifacts/download
下载


下载导出的压缩包

Parameters
Name	Description
projectId *
integer
(path)
项目ID

Example : 867

867
Responses
Code	Description	Links
302	
重定向至压缩包链接
```

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

### User Input

工具还存在窗口字体模糊，可能不适配2K屏幕的情况。且提取原文功能在github工作流中是否存在能够识别更新而选择性提取，而不是重新遍历整个文件，从而提高效率的功能？

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [localization.yml](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/.github/workflows/localization.yml) *

*Edited relevant file*

*Edited relevant file*

### User Input

下载功能加入指定下载位置的功能

### Planner Response

这是一个简单的增强请求。我将为下载功能添加指定下载位置的选项。

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

### Planner Response

已完成！「Paratranz 同步」选项卡现在新增了一个**「下载保存路径」**输入框，你可以：

1. 直接输入路径（如 `zh.json` 或 `D:\翻译\output.json`）
2. 点击「浏览...」按钮选择保存位置

下载路径会自动保存到配置文件，下次启动时会记住你的选择。

### User Input

start_gui打开命令行终端但不会随着图形化窗口的关闭而自动结束，优化一下

*Viewed [Start_GUI.bat](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/Start_GUI.bat) *

*Edited relevant file*

### Planner Response

已优化。我移除了 [Start_GUI.bat](cci:7://file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/Start_GUI.bat:0:0-0:0) 末尾的 `pause` 命令。现在当你关闭图形化窗口时，背后的命令行终端也会随之自动关闭。

### User Input

我想要优化一下提取原文和上传至paratranz的功能，因为在paratranz上如果文件中只有en.json的话浏览和检索起来会是灾难性的差，虽然手动提取过程中可以自己重命名json文件，但工作量无意是过大的。并且ss14游戏文件夹中存在着不少和翻译无关的yaml文件。

1.关于检索：
如cdda的中文mod汉化项目中，采用了直接把整个mod内的对应提取出来，以mod名为单位的json文件进行翻译的方案，译员们点开后文件能够直观的了解里面的词条都是对应mod的内容。而ss14本身则是用文件夹进行归类，因此我希望查阅对应的官方接口文档，是否能让程序或工作流提取原文时识别文件夹结构，并通过API创建对应文件夹将文件导入或更新。

2.关于文件识别:
ss14的文件管理情况如下：
游戏目录Monolith-CN\Resources\Prototypes\Entities\Clothing\Back中包含4个文件如backpacks.yml，这些是正常硬编码可以汉化的。

但如Monolith-CN\Resources\Prototypes\_Mono\Loadouts\USSP目录下，则是存在一系列采用了.ftl方案的yaml:

```
- type: loadoutGroup
  id: UsspFirearm
  name: loadout-group-weapon
  minLimit: 1
  fallbacks:
  - FactionAk502Loadout

- type: loadoutGroup
  id: UsspFirearmCommissar
  name: loadout-group-weapon
  minLimit: 1
  fallbacks:
  - FactionAk150Loadout
```

按照程序的标签识别则会提取出：

```
  {
    "key": "UsspMagCommissar.name",
    "original": "loadout-group-magazine",
    "context": "文件: Specifics\\gun.yml\nID: UsspMagCommissar\n"
  }
```

但提取出来文本实际上是.ftl对应的字符串，无法作为正常文本进行翻译，如果上传后被汉化了反而导致游戏文本出错。（这种"name:A-B-C"类型的，中间有连字符-的一般属于采用.ftl方案进行i18n的文件。）

有什么方案能够高效且稳定解决第二个问题？同时参阅一下这个json结构的文档内容，看看是否有内容以帮助上述问题  @[paratranz api文档.json]

*Viewed [paratranz api文档.json](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/paratranz%20api%E6%96%87%E6%A1%A3.json) *

*Edited relevant file*

### User Input

This is a system-generated message that is sent due to the user's review policy. Proceed with the decision that you think is the most optimal here.

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Viewed [ss14_tracker.py](file:///f:/Desktop/ss14%E7%BF%BB%E8%AF%91/yaml%E6%B1%89%E5%8C%96%E5%B7%A5%E5%85%B7/ss14_tracker.py) *

*Edited relevant file*

*Edited relevant file*
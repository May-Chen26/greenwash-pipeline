# Greenwash Pipeline v0.5

证据优先的报告 NLP 上游：PDF/TXT → 指标与声明候选 → 人工复核 → JSON 导出。
这是可追溯的离线规则原型，尚未验证跨公司精确率或召回率。没有自动判断漂绿或生成 B/G 分数。

## 安装与运行

Python 3.10+。**核心只依赖标准库**；PDF 输入才需要 Poppler 的 pdftotext 与 PyMuPDF。

### 作为依赖安装（推荐）

```bash
pip install "greenwash-pipeline @ git+https://github.com/erikjin12345/greenwash-pipeline@v0.5.0"
pip install "greenwash-pipeline[pdf] @ git+https://github.com/erikjin12345/greenwash-pipeline@v0.5.0"
```

第一种只装核心（纯 stdlib，能跑 TXT 路径）；第二种带 PDF 额外依赖。**Poppler 是系统依赖，装不了，必须自己 `brew install poppler` 或 `apt-get install poppler-utils`。**

装完后有一个控制台命令 `greenwash`，等价于 `python -m greenwash`。

### 作为库使用

```python
from greenwash import extract, review_html, apply_review, __version__, EXTRACTOR_VERSION

bundle = extract("report.pdf", "2330.TW", published_at="2025-04-01", as_of="2026-10-04")
open("review.html", "w").write(review_html(bundle))
```

公开接口只有这四个名字（外加两个版本号），其余模块都是内部实现、可能变动。

### 在源码树里开发

```bash
pip install -r requirements-pdf.txt
```

macOS 安装 Poppler：`brew install poppler`；Ubuntu：`sudo apt-get install poppler-utils`。

```bash
python -m greenwash extract examples/synthetic_report.txt --company DEMO --published-at 2025-04-01 --as-of 2026-10-03 --synthetic --out runs/demo
python -m greenwash extract /path/to/report.pdf --company COMPANY_ID --as-of 2026-10-03 --out runs/company
```

发布日期不明时省略 --published-at，系统记录 null 和警告；不再以接收日期冒充发布日期。as-of 用于筛选已知发布日期，但无法让未知日期数据具备历史回测资格。

打开输出目录的 review.html。复核时确认或拒绝候选、修改字段、填写复核人，再下载 decisions.json。页面末尾另列“未进入复核队列”的句子，它们不能接受或拒绝，只用于让复核者看到漏提范围：

```bash
python -m greenwash apply-review runs/company/candidates.json /path/to/decisions.json --out runs/reviewed
```

只导出 accepted 的 Observation / Claim。Claim 确认仅表示提取正确，assessment_status 仍是 not_assessed。未知字段保留 null。复核页面刷新不会自动保存，需及时下载。输出目录必须是新目录，避免覆盖工作。

无需重新提取即可打开 `examples/mtr-output/review.html` 检查港铁候选，或运行现成模拟复核：

```bash
python -m greenwash apply-review examples/demo-output/candidates.json examples/demo-decisions.json --out runs/reviewed-example
python -m unittest discover -s tests -v
python -m greenwash.evaluate examples/mtr-output/candidates.json tests/fixtures/mtr-gold.json
```

## v0.5 改动

在干净基线上重建。新增语言层 `greenwash/lang.py`，让同一套规则读英文、繁体中文（台湾）和简体中文（中国大陆）报告：

- **民国年。** `民國111年` / `中华民国113年` 换算为 2022 / 2024。同时修掉 `\b` 的隐患：`2050淨零` 里数字与汉字都是词字符，原来的 `\b(?:19|20)\d{2}\b` 一个都匹配不到。
- **中文单位。** 公噸／公吨、千、萬（万）、百萬（百万）、億（亿）吨，以及 `公噸－二氧化碳當量`、下标 `CO₂e` 和全角括号 `（ ）`、脚注标记 `註1`。
- **中文 scope 标签。** 範疇一（范畴一／范围一／範圍一）、直接排放、間接排放；`範疇一及範疇二` 与 `Scope 1 and 2` 一样弃权。
- **中文声明词表。** ACTION／FUTURE／TARGET_NOUN／REALIZED／否定／强度／认证等词表补上繁体与简体。繁体句（`減少`、`目標`）在 v0.4 会被当成"没有行动动词"而丢进漏提清单。
- **中文句子切分。** `claim_segments` 原以 8 个空白词为门槛，中文整段只有一个 token，会被整段丢弃；现改为 12 个汉字。
- 输出 schema 不变（1.2）。**英文结果不变**：英文表格、声明分类与包内样本都重跑过，数字一致。

在 8 份真实台湾永續報告書上验证（`tw_esg/`，经 PyMuPDF 版面重建喂入）：

| 指标 | v0.4 | v0.5 |
|---|---|---|
| 声明候选合计 | 190 | 1234 |
| 数值观测合计 | 0 | 6（全部来自台积电 p228） |
| 未入队句子 | 261 | 450 |

其余 7 份的排放表是「scope 当做列」的横向版式，不满足本解析器"单序列、需显式年份表头"的设计前提，按既有约定弃权而不是猜。这是已知缺口，不是回归。

`examples/` 下两份产物仍是 v0.4 冻结样本，未重新生成：PDF 路径需要 Poppler 的 `pdftotext`，构建机上没有；`review.html` 的渲染逻辑未变，仍可打开查看。

## v0.4 改动

- **漏提可见。** 未达到候选门槛的句子不再静默丢弃，改为写入 `skipped_candidates`、计数进 `quality_summary.skipped_claim_candidates`，并在 review.html 末尾列出（最多 200 条）。已作为数值观测捕获的句子不计入漏提；无标点且超过 600 字符的整块页面文本不作为句子列出。
- **补齐动词词表。** ACTION 与 REALIZED 增加 fell/rose/increased/grew/cut/dropped/declined/improved 及对应中文，恶化方向不再系统性欠捕获。
- **补齐单位形态。** 表格支持百万级单位（million T of CO2e、million tonnes CO2e、MtCO2e）以及把单位写在行标签括号内的写法；短标题（如 “Environmental 2024 2023 2022”）也可作为年份表头，但含年份的散文句子仍不当作表头。港灯样本的数值候选由 0 提升到 3。
- **区分承诺与结果。** `claim_type=future_target` 现在要求显式前瞻标记（will/aim/plan/intend/pledge/commit/expect/on track 或目标名词）；已实现动词优先于单纯出现“target”一词，因此“我们已达成目标”归类为 realized_result。这是分类口径变更，需要团队确认。
- **复核页面定位修复。** 声明的 `evidence.line` 为 null，原先渲染成 `p16:None`；现改为显示 `p<N> · <block_id>`。
- **页数对齐守卫。** `pdftotext` 页数与 PyMuPDF 文本块页数不一致时直接报错，不再按索引错位挂接声明。
- 版本升至 0.4.0，主容器 `schema_version` 升至 1.2（新增 `skipped_candidates`）。`examples/mtr-output` 与 `examples/demo-output` 仍是 v0.3 冻结产物，未重新生成。

## v0.3 改动

- PDF 声明按带坐标文本块和句子生成，保留原始换行文本、规范化文本、句子字符区间和 bbox。对明显不连续的原生文本块再次分组；不宣称任意版式均正确。
- 表格支持明确年份表头的升序/倒序、Unicode CO₂e、tCO2e/ktCO2e/千吨单位、带脚注数值、显式缺失单元格。
- 合并 Scope 1+2 不假装是单独 Scope 1；CO2 不假装是 CO2e；歧义数字格式、多主体重复年份和列数不符时弃权。
- 声明标记不完整、混合绝对量/强度、否定、估计、目标主体不明等风险；从附近明确的目标标题提取年份时保留上下文证据并要求复核。
- 缺失发布日期、零提取结果和低文本页均明确提示；质量汇总不提供虚构置信度。
- 增加只在明确人工标注范围内计算数值匹配率的评测脚本。重复预测不会虚增召回率。

## 包内结果

港铁仍是开发样本，15 个总体排放数值对上只能作为回归结果。其他候选没有全部人工验收；声明数量不能当准确率。整体与业务分项不能相加。Scope 2 方法、地理和组织边界仍需核验。

`docs/validation.md` 记录本版测试结果；`docs/holdout-protocol.md` 定义下一份报告的独立考核流程。`docs/contracts.md` 定义接口，`docs/backlog.md` 是团队任务清单。

## 尚未实现及限制

无 OCR、LLM、下载器或网络调用；不支持所有多主体/跨页/图形表格；表格仅处理受支持的 Scope 排放行和少量行内营收格式。表头不存在时不会猜年份。收入 USD 规则不能替代完整多币种财务解析。

段落可能跨块或跨页，部分声明仍不完整。代词、否定范围、条件句、第三方目标与隐含基准年尚不能完整解析。脚注是待核验证据，不会自动完成口径可比性判断。全部候选需要人工复核。

模型替代规则也必须经过同一套盲测。没有真实声明金标准前，不报告精确率或召回率；没有核验主体和口径前，不判断矛盾。

## 团队接入

本包是**独立依赖**，不再以 vendored 目录的形式复制进消费方仓库。消费方在 `pyproject.toml` 里声明：

```toml
dependencies = [
    "greenwash-pipeline @ git+https://github.com/erikjin12345/greenwash-pipeline@v0.5.0",
]
```

需要 PDF 时用 `greenwash-pipeline[pdf]`。**不要**再把 `greenwash/` 拷进别的仓库——之前四份副本三个版本，就是这么分叉的。

发布流程（版本只有两个地方需要动，其中一个会被自动读取）：

1. 改 `greenwash/__init__.py` 里的 `__version__`（pyproject 用 `dynamic` 从它读，不会再出现两处版本打架）。
2. 重算 `release-manifest.json` 的 `sha256` 与 `version`。
3. `uv build` 出 wheel/sdist，打 tag `v0.5.0` 再推送。
4. 提醒：仓库还没有 LICENSE，公开前必须定一个——这是法务决定，代码里没有替你选。

实际 PDF、密钥和运行数据不要放入普通源码提交；本包包含用户提供报告的派生文本示例（`examples/`），公开仓库前需确认是否保留。

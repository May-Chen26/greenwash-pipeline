# 接口 v1.0

主容器 candidates.json：schema_version、extractor_version、document、as_of、pages、passages、records、warnings、skipped_candidates。

document 保存 SHA-256、公司 ID、发布日期及来源标记、synthetic。发布日期依赖用户输入，不代表系统独立核实。PDF 页码是物理页码，line 是解析后文本行号，不是 PDF 坐标。

record 公共字段：id、kind、company_id、available_at、evidence(document_id/page/line/quote)、context、review_status、fields。

Observation.fields：metric(scope1/scope2/scope3/revenue)、value、unit(tCO2e/USD)、year、geography、organizational_boundary、scope2_method、period_basis。

Claim.fields：claim_type、metric、baseline_year、target_year、geography、organizational_boundary、assessment_status。未确定值使用 JSON null。重复原文提供 duplicate_group；合并语义相近声明需下一阶段实现。

claim_type 口径（v0.4 起）：`realized_result` 与 `future_target` 互斥。出现已实现动词且无显式前瞻标记时归 realized_result；只有显式前瞻标记（will/aim/plan/intend/pledge/commit/expect/targeting/on track，或目标名词）才归 future_target；其余为 unclassified。仅出现“target”一词不再自动等于未来目标。

Review 输入：document_id、reviewer、decisions[{id,status,fields,note}]。status 为 pending/accepted/rejected。未列出的候选保留待复核状态。字段集合不可变；原文证据不可通过 decisions 修改；人工只能修改 fields。

Review 输出：reviewed.json 保留所有记录及原始字段；observations.json/claims.json 仅含 accepted，保留 document 与 as_of。scoring_ready 固定 false，因为此阶段没有匹配同行数据或验证声明真伪。

人工确认并不等于自动验证事实。应在下游比对地理、主体、范围、方法、年份和期间；任何口径不一致必须弃权，不得强行判矛盾。

## 下一阶段接口

LLM adapter 接收原文段落及稳定证据 ID，返回同一套字段与逐字引用。必须检验引用存在并通过单位、类型校验，初始状态仍为 pending。模型不得改变 evidence，不得在此阶段生成 B/G。

Assessment 建议独立保存 claim_id、evidence_ids、status、severity、rule_version、reviewer。状态至少有 supported/contradicted/partially_supported/insufficient_evidence/not_comparable/not_yet_due。不要把这一阶段的 extraction review_status 当成 Assessment。

表格候选附带 header_quote/header_line/raw_cell、section_hint、related_notes；这些提供复核依据，不自动确认为主体口径。

## v1.1 / v0.3 更新

- document.published_at 和 record.available_at 可为 null；未知时间不能用于有效历史回测。
- 声明 evidence 包含 block_id、bbox、normalized_source_text、raw_source_text、char_start/end。quote 必须精确等于 normalized_source_text 的对应片段；换行只在规范化副本中合并。字符位置指 Python 字符索引。
- bbox 为 PDF 文本块坐标 [x0,y0,x1,y1]，不是句子精确边界。TXT 输入 bbox 为 null。声明 line 为 null，以 block_id 定位。
- quality_flags、percentages_mentioned 仅为候选元数据；未将百分比自动解释为实际减排。
- nearby target heading 提供额外 context_evidence，字段从标题推导时明确标记；不跨页继承年份。
- quality_summary 包含候选数量和警告状态，accuracy_measured=false、scoring_ready=false；不能将其视为准确率或覆盖率。

## v1.2 / v0.4 更新

- 新增顶层 `skipped_candidates`：数组，元素为 {page, block_id, quote, reason}。这是漏提可见性清单，不是 record，不能接受或拒绝，也不参与评测分数。
- reason 取值：`SHORT_SENTENCE_BELOW_REVIEW_THRESHOLD`（含环境词与动作词但短于复核门槛）、`QUANTIFIED_ENV_SENTENCE_WITHOUT_ACTION_VERB`（含环境词与百分比/碳能源单位但无动作词）。
- 已作为 observation 捕获的句子不计入 skipped_candidates；无标点且超过 600 字符的区块文本不作为句子列出。
- 当 skipped_candidates 非空时，warnings 增加 CLAIM_SENTENCES_OMITTED_FROM_REVIEW_QUEUE 并带 count；quality_summary 增加 skipped_claim_candidates。
- schema_version 升至 1.2。下游若按 1.1 严格校验字段集合需先适配。

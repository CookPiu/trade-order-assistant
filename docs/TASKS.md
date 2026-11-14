# 智能商贸提单助手 任务清单

依据 [SPEC.md](SPEC.md)（已确认）与 [DESIGN.md](DESIGN.md)。`[P]` 表示与同组其他任务没有文件和顺序依赖，可以并行。完成基础与 US1 两组后即可演示最小可用版本。

## 准备与公共基础

- [x] T001 后端工程初始化：uv 项目、FastAPI 入口、配置加载、日志、`.env.example`（backend/pyproject.toml、backend/app/main.py、backend/app/core/config.py）C-004
- [x] T002 [P] 前端工程初始化：Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router（frontend/）
- [x] T003 [P] 浅色商务蓝主题，覆盖 Element Plus CSS 变量并定义超额红、提醒黄、待确认高亮状态色（frontend/src/styles/theme.scss）FR-048
- [x] T004 数据库表模型：部门、用户、签约单位、项目、合同（含到期日）、合同明细、物料（含公允价）、别名、草稿、订单、订单明细、单号流水、trade 表、导入批次与行、审计日志、系统参数（backend/app/models/）C-001
- [x] T005 初始化脚本：建表并灌入示例数据（两个部门、三类角色账号、合同 2026-WZ-089、剩余 15 万元的采购合同、临近到期合同、约 30 条物料及别名、系统参数），可重复执行（backend/scripts/seed.py）FR-061
- [x] T006 [P] 生成演示素材：42.5 水泥 500 吨 22 万元的签收单图片、含三类异常行的批量 Excel（backend/scripts/make_samples.py、samples/）FR-061
- [x] T007 JWT 登录接口、当前用户与部门校验依赖（backend/app/api/auth.py、backend/app/core/security.py）FR-001 FR-002
- [x] T008 [P] 审计日志服务，只追加（backend/app/services/audit.py）FR-003
- [x] T009 前端登录页、路由守卫、按角色导航与默认页跳转（frontend/src/views/Login.vue、frontend/src/router/、frontend/src/stores/session.ts）FR-001 FR-045
- [x] T010 [P] 文本模型与视觉模型客户端，含超时与失败异常（backend/app/llm/）FR-011 FR-015
- [x] T011 合同、项目、物料主数据查询接口，校验合同类型与订单类型匹配、合同属于本部门（backend/app/api/master.py）FR-020 FR-024 FR-002
- [x] T012 额度计算服务：四项统计、金额超额判定、数量超出高亮、驳回不计入、公允价偏离与配额阈值提醒，附单元测试（backend/app/services/quota.py、backend/tests/test_quota.py）FR-021 FR-022 FR-025 FR-026 FR-027 FR-028
- [x] T013 单号生成：按前缀、单位代码、日期行锁递增（backend/app/services/order_no.py）FR-032 C-003
- [x] T014 提交事务：锁合同行、重算额度、生成单号、写订单与 trade 表、draft_id 唯一防重，附并发与重复提交测试（backend/app/services/order_flow.py、backend/app/services/trade_sync.py、backend/tests/test_submit.py）FR-032 FR-033 FR-034 C-003 SC-003 SC-004
- [x] T015 [P] 草稿保存与“继续上次”载入接口（backend/app/api/drafts.py）FR-004

## US1 自然语言对话提单（P1）

- [x] T016 物料标准化：别名精确匹配、rapidfuzz 在合同物料内召回候选、模型只在候选中选择，附别名映射测试（backend/app/services/material_normalizer.py、backend/tests/test_normalizer.py）FR-016 C-002 SC-002
- [x] T017 [P] 提单图 intent 与 extract 节点：意图识别、JSON 结构化抽取、相对日期服务端换算、多轮合并到当前草稿（backend/app/graph/、backend/prompts/）FR-010 FR-011 FR-012
- [x] T018 提单图 link_contract、quota_check、assemble_draft、respond 节点：补全合同信息、固定业务属性、登录身份绑定、缺失与异常字段列表及追问（backend/app/graph/nodes/）FR-013 FR-014 FR-020 FR-023 FR-029
- [x] T019 对话接口与会话 checkpointer，模型失败时返回错误且保留草稿（backend/app/api/chat.py）FR-012
- [x] T020 [P] 前端会话与草稿 store，写入 sessionStorage 并在刷新后恢复（frontend/src/stores/draft.ts）FR-042
- [x] T021 全屏工作台布局、文本对话面板、四个快捷操作、消息气泡流与处理中状态（frontend/src/views/Workbench.vue、frontend/src/components/InputPanels/）FR-041
- [x] T022 预览区：状态胶囊、额度卡片、超额横幅、黄色提醒、基本信息网格、产品明细表，字段可编辑并与草稿双向同步，异常字段高亮（frontend/src/components/DraftPreview.vue、frontend/src/components/QuotaCards.vue）FR-030 FR-031 FR-022 FR-023 FR-025 FR-027 FR-028
- [x] T023 提单操作栏：保存草稿、一键提单、超额必填备注、提交后锁定按钮（frontend/src/components/SubmitBar.vue）FR-004 FR-022 FR-032 FR-033
- [x] T024 跑通需求原文场景一并截图（docs/screenshots/）SC-001

## US2 单据图片识别提单与超额预警（P1）

- [x] T025 图片识别接口：计算 SHA-256、调用视觉模型、走标准化与合同额度链路、记审计日志（backend/app/api/ocr.py）FR-015 FR-003
- [x] T026 前端图片面板：点击、拖拽、粘贴上传，识别卡片与一键应用为草稿（frontend/src/components/InputPanels/ImagePanel.vue）FR-015
- [x] T027 跑通需求原文场景二（超额、填备注、生成待特批订单）并截图（docs/screenshots/）SC-001

## US3 Excel 批量提单（P2）

- [x] T028 模板下载、逐行解析、逐行校验与批内按行累计额度、单行重新校验接口（backend/app/api/batch.py、backend/app/services/excel_parser.py）FR-017
- [x] T029 批量并发提交（每行一个事务）与导入批次记录（backend/app/api/batch.py、backend/app/services/batch_submit.py）FR-036 FR-047
- [x] T030 前端批量导入与数据中心页：拖拽上传、校验结果表、异常行标红、行内修改、批量提交、导入记录列表与批次明细（frontend/src/views/Batch.vue）FR-017 FR-036 FR-047
- [x] T031 用示例 Excel 验证三类异常行标红、修正后批量提交并截图 SC-005

## US4 悬浮窗提单与商贸系统联动（P2）

- [x] T032 订单列表与详情接口：按类型、状态、合同号、日期筛选，按部门隔离（backend/app/api/orders.py）FR-035 FR-002
- [x] T033 商贸订单列表页与详情抽屉（主档、明细、额度看板、审批意见、审计流水）（frontend/src/views/TradeOrders.vue、frontend/src/components/OrderDrawer.vue）FR-035
- [x] T034 悬浮球与悬浮窗：对话、精简草稿卡片、卡片一键提单、收起、切换全屏（frontend/src/components/FloatingWidget.vue、frontend/src/components/DraftMiniCard.vue）FR-040 FR-042 FR-044
- [x] T035 [P] 订单事件总线，提单成功后通知列表刷新（frontend/src/bus/）FR-043
- [x] T036 验证悬浮窗与全屏来回切换 3 次状态一致、提单后列表自动出现并截图 SC-006

## US5 订单审批（P2）

- [x] T037 审批接口：通过、退回、驳回，退回与驳回必填意见，记审计日志（backend/app/api/approval.py）FR-037 FR-003
- [x] T038 退回订单重提：原单号、排除自身占用重算额度、更新 trade 表，附测试（backend/app/services/order_flow.py、backend/tests/test_resubmit.py）FR-038 FR-026
- [x] T039 详情抽屉按角色显示审批操作；经办人对退回订单点击“修改”载入工作台（frontend/src/components/OrderDrawer.vue、frontend/src/stores/draft.ts）FR-046 FR-037 FR-038
- [x] T040 越权访问测试：跨部门读取订单与合同返回 403 或 404（backend/tests/test_permission.py）SC-007

## US6 主数据与系统配置（P3）

- [x] T041 合同台账、物料字典与别名的增改查接口（backend/app/api/admin.py）FR-050
- [x] T042 [P] 参数配置接口：公允价偏离比例、配额阈值、固定业务属性、模型参数（backend/app/api/params.py）FR-051
- [x] T043 [P] 审计日志查询接口，按操作人、动作、时间筛选（backend/app/api/audit.py）FR-052
- [x] T044 主数据与系统配置页四个页签（frontend/src/views/Admin.vue）FR-050 FR-051 FR-052

## 收尾

- [x] T045 README：本机从零启动步骤（依赖、MySQL80、`.env`、初始化、启动前后端）（README.md）FR-060
- [x] T046 测量对话单轮响应时间，逐条核对 FR 与 SC，整理测试截图（docs/screenshots/）SC-008 C-005 C-007

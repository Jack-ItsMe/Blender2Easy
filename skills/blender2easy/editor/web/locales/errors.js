// Stable interface explanations; unexpected diagnostic details remain verbatim.
const entries = [
  ['openProject', '请先打开或新建项目', 'Open or create a project first.', '請先開啟或建立專案'],
  ['openFirst', '请先打开项目', 'Open a project first.', '請先開啟專案'],
  ['referenceFormat', '参考图必须是本地 PNG 或 JPG 图片', 'Use a local PNG or JPG reference image.', '參考圖必須是本機 PNG 或 JPG 圖片'],
  ['referenceChanged', '参考图已变化，请由 Agent 创建新预览任务', 'The reference changed. Ask the agent to create a new review.', '參考圖已變更，請由 Agent 建立新的預覽任務'],
  ['mediaChanged', '成片已变化，请由 Agent 为新版本创建预览任务', 'The output changed. Ask the agent to create a review for the new version.', '成片已變更，請由 Agent 為新版本建立預覽任務'],
  ['referenceDuringLoad', '参考图在加载时发生变化，请重新创建预览任务', 'The reference changed while loading. Create a new review.', '參考圖在載入時發生變更，請重新建立預覽任務'],
  ['mediaDuringLoad', '成片在加载时发生变化，请重新创建预览任务', 'The output changed while loading. Create a new review.', '成片在載入時發生變更，請重新建立預覽任務'],
  ['previewBusy', '预览准备中，请完成后再切换调整任务', 'Wait for the preview to finish before switching reviews.', '預覽準備中，請完成後再切換調整任務'],
  ['reviewChanged', '调整任务已变更，请使用当前任务的新预览入口', 'This review changed. Open the current review link.', '調整任務已變更，請使用目前任務的新預覽入口'],
  ['projectFile', '请选择存在的项目 JSON 文件', 'Choose an existing project JSON file.', '請選擇存在的專案 JSON 檔案'],
  ['template', '未知模板', 'This template is unavailable.', '未知範本'],
  ['blendFile', '请选择存在的 .blend 文件', 'Choose an existing .blend file.', '請選擇存在的 .blend 檔案'],
  ['importBusy', '请等待当前 Blender 任务完成后导入', 'Wait for the current Blender task before importing.', '請等待目前 Blender 任務完成後匯入'],
  ['camera', '原生工程没有可用相机；请在 Blender 中添加相机后导入', 'The scene has no usable camera. Add one in Blender before importing.', '原生專案沒有可用相機；請在 Blender 中新增相機後匯入'],
  ['switched', '项目已在另一窗口切换，请重新打开当前项目后再操作', 'The project switched in another window. Reopen the current project.', '專案已在另一個視窗切換，請重新開啟目前專案後再操作'],
  ['renderBusy', '当前项目正在渲染，请在任务完成后保存', 'This project is rendering. Save after the task finishes.', '目前專案正在算圖，請在任務完成後儲存'],
  ['externalEdit', '项目已被其他窗口或程序修改，请重新打开后再保存', 'The project changed elsewhere. Reopen it before saving.', '專案已被其他視窗或程式修改，請重新開啟後再儲存'],
  ['validationChanged', '校验期间项目被外部程序修改，请重新打开', 'The project changed during validation. Reopen it.', '驗證期間專案被外部程式修改，請重新開啟'],
  ['externalChanged', '项目被外部程序修改，请重新打开', 'The project changed outside this window. Reopen it.', '專案被外部程式修改，請重新開啟'],
  ['shot', '镜头不存在', 'This shot is unavailable.', '鏡頭不存在'],
  ['operation', '不支持的任务', 'This operation is not supported.', '不支援的任務'],
  ['busy', '已有 Blender 任务运行中，请等待完成', 'A Blender task is running. Wait for it to finish.', '已有 Blender 任務執行中，請等待完成'],
  ['saveFirst', '请先保存当前参数，再生成 Blender 预览或视频', 'Save the current settings before generating a preview or video.', '請先儲存目前參數，再產生 Blender 預覽或影片'],
  ['previewFrames', '预览帧必须是至多 20 个正整数', 'Choose up to 20 positive whole-number preview frames.', '預覽影格必須是最多 20 個正整數'],
  ['jobChanged', '任务开始前项目已改变，请重新生成', 'The project changed before the task started. Generate it again.', '任務開始前專案已變更，請重新產生'],
  ['blenderFailed', 'Blender 任务失败', 'The Blender task failed.', 'Blender 任務失敗'],
  ['jobMissing', '任务不存在', 'This task is unavailable.', '任務不存在'],
  ['session', '编辑器会话已更新，请刷新页面', 'The editor session changed. Refresh the page.', '編輯器工作階段已更新，請重新整理頁面'],
  ['large', '请求太大', 'The request is too large.', '請求過大'],
  ['object', '请求须为对象', 'The request must contain a valid object.', '請求必須為物件'],
  ['scoped', '此预览只开放 agent 指定的调整项，请通过当前调整任务提交', 'Use the current review to submit only the adjustments enabled by the agent.', '此預覽只開放 Agent 指定的調整項，請透過目前調整任務提交'],
  ['activeReview', '当前存在局部调整任务，请先由 agent 完成该任务', 'An active scoped review must be completed by the agent first.', '目前有局部調整任務，請先由 Agent 完成該任務'],
  ['activation', '激活请求包含不支持的字段', 'The review activation includes unsupported fields.', '啟用請求包含不支援的欄位'],
  ['fields', '只允许提交本次调整项的值和反馈', 'Submit only this review’s allowed values and feedback.', '只允許提交本次調整項的值與回饋'],
  ['agentProduction', '本次预览由 agent 负责制作，提交反馈后继续处理', 'The agent prepares this preview and continues after you submit feedback.', '本次預覽由 Agent 負責製作，提交回饋後繼續處理'],
  ['endpoint', '接口不存在', 'This operation is unavailable.', '介面不存在'],
  ['file', '文件不存在', 'The file is unavailable.', '檔案不存在'],
  ['authoring', '完整编辑工具需要 agent 显式启用 authoring 模式', 'The agent must enable authoring mode before full editing is available.', '完整編輯工具需要 Agent 明確啟用 authoring 模式'],
  ['origin', 'Only this local editor origin is accepted', 'Open this page through the local editor address.', '請透過本機編輯器位址開啟此頁面'],
  ['crossOrigin', 'Cross-origin requests are not accepted', 'Open this page through the local editor address.', '請透過本機編輯器位址開啟此頁面'],
  ['frozenReference', 'Review reference changed; ask the agent for a new review', 'The review reference changed. Ask the agent for a new review.', '審閱參考圖已變更，請由 Agent 建立新的審閱'],
  ['noReview', 'No current review request', 'There is no active review.', '目前沒有審閱請求'],
  ['superseded', 'Review request was superseded; refresh the preview', 'A newer review is available. Refresh the preview.', '審閱請求已被取代，請重新整理預覽'],
  ['unknownReview', 'Unknown review request', 'This review is unavailable.', '找不到此審閱請求'],
  ['digest', 'Review response digest mismatch', 'The saved feedback does not match this review. Ask the agent to check it.', '儲存的回饋與此審閱不符，請由 Agent 檢查'],
  ['binding', 'Response belongs to a different review, project, or agent task', 'This feedback belongs to a different review, project or task.', '此回饋屬於不同的審閱、專案或 Agent 任務'],
  ['staleProject', 'Project changed since this review was created; ask the agent for a fresh review', 'The project changed. Ask the agent for a new review before submitting.', '專案已變更，請由 Agent 建立新的審閱後再提交'],
  ['staleSource', 'A source asset changed since review creation', 'A source asset changed. Ask the agent for a new review.', '來源素材已變更，請由 Agent 建立新的審閱'],
  ['frozenMedia', 'Review media changed; ask the agent for a new review', 'The review media changed. Ask the agent for a new review.', '審閱媒體已變更，請由 Agent 建立新的審閱'],
  ['alreadySubmitted', 'Feedback was already submitted and cannot be replaced; request a new review', 'Feedback has already been submitted. Request a new review to change it.', '回饋已提交且無法取代，如需修改請建立新的審閱'],
  ['inspection', 'This review does not permit the requested surface inspection', 'This surface inspection is outside the current review.', '此表面檢查超出目前審閱的允許範圍'],
];

export const messages = {en: {}, 'zh-Hans': {}, 'zh-Hant': {}};
export const sourceErrors = {};
for (const [name, source, english, traditional] of entries) {
  const key = 'errors.' + name;
  sourceErrors[source] = key;
  messages.en[key] = english;
  messages['zh-Hant'][key] = traditional;
  messages['zh-Hans'][key] = /[\u3400-\u9fff]/.test(source) ? source : ({
    origin: '请通过本地编辑器地址打开此页面。', crossOrigin: '请通过本地编辑器地址打开此页面。',
    frozenReference: '审查参考图已变化，请由 Agent 创建新的审查。', noReview: '当前没有审查请求。',
    superseded: '已有新的审查请求，请刷新预览。', unknownReview: '找不到此审查请求。',
    digest: '保存的反馈与此审查不符，请由 Agent 检查。', binding: '此反馈属于不同的审查、项目或任务。',
    staleProject: '项目已变化，请由 Agent 创建新的审查后再提交。', staleSource: '来源资产已变化，请由 Agent 创建新的审查。',
    frozenMedia: '审查媒体已变化，请由 Agent 创建新的审查。', alreadySubmitted: '反馈已经提交，如需修改请创建新的审查。',
    inspection: '此表面检查超出当前审查的允许范围。',
  }[name] || english);
}

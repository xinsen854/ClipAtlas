const stableCodeMessages: Record<string, string> = {
  generated_artifact_not_found: '没有找到对应的导出草稿',
  generated_artifact_invalid: '导出草稿路径无效，请重新生成',
  local_system_not_configured: '本机操作尚未配置完成',
  local_system_unsupported: '当前系统不支持此本机操作',
  local_system_action_failed: '本机操作执行失败',
  provider_not_found: '没有找到指定的视频理解服务',
  provider_authentication_failed: '视频理解服务凭证无效或无权限',
  provider_rate_limited: '视频理解服务请求过于频繁，请稍后再试',
  provider_request_failed: '视频理解服务请求失败',
  provider_invalid_structured_output: 'AI 返回的画面分析格式不正确，未能生成有效结果',
  auto_director_unavailable: '自动编导模型尚未配置或暂不可用',
  story_evidence_unavailable: '当前项目没有可用于故事分析的素材证据',
  story_outline_conflict: 'AI 返回的故事简纲引用了无效素材证据，请重试',
  speech_auth_failed: '语音服务凭证无效或无权限',
  speech_rate_limited: '语音服务请求过于频繁，请稍后再试',
  speech_request_failed: '语音服务请求失败',
  speech_audio_invalid: '语音服务返回的音频无效',
  speech_configuration_invalid: '语音参数配置有误，请检查设置',
  speech_profile_not_found: '没有找到对应的配音方案',
  speech_provider_unavailable: '语音服务尚未配置或暂不可用',
  rough_cut_unavailable: '剪辑草稿服务尚未就绪',
  rough_cut_plan_not_found: '没有找到对应的粗剪方案',
  rough_cut_not_ready: '当前条件还不能生成粗剪，请先完成上一步',
  rough_cut_retrieval_failed: '素材检索失败，暂时无法生成粗剪',
  rough_cut_planning_failed: '剪辑草稿生成失败',
  export_plan_not_found: '没有找到可导出的粗剪方案',
  export_not_ready: '当前粗剪方案还不能导出',
  export_invariant_failed: '导出数据校验失败',
  otio_serialization_failed: 'OTIO 导出失败',
  jianying_unavailable: '剪映草稿导出暂不可用',
  jianying_dependency_missing: '剪映草稿导出组件尚未安装',
  jianying_not_configured: '剪映尚未配置完成',
  jianying_media_unsupported: '素材格式无法写入剪映草稿',
  jianying_write_failed: '剪映草稿写入失败',
}

export function chineseErrorMessage(status: number, code?: string): string {
  if (code && stableCodeMessages[code]) {
    return stableCodeMessages[code]
  }

  if (status === 0) return '无法连接 ClipAtlas 服务'
  if (status === 404) return '没有找到请求的内容'
  if (status === 409) return '当前状态不允许此操作，请按提示完成上一步'
  if (status === 422) return '输入内容有误，请检查填写项'
  if (status === 429 || status === 503) return '服务暂不可用，请稍后再试'
  if (status >= 500) return '服务执行失败，请查看技术详情'
  if (status >= 400) return '请求失败，请检查输入后重试'
  return '发生未知错误'
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly technicalMessage?: string

  constructor(options: {
    status: number
    code?: string
    message?: string
    technicalMessage?: string
  }) {
    super(options.message ?? chineseErrorMessage(options.status, options.code))
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.technicalMessage = options.technicalMessage
  }
}

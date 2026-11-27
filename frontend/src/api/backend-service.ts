import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type CorrectionImportPayload = {
  file?: File | null
  content?: string
  rows?: Record<string, unknown>[]
  department?: string
  uploadedBy?: string
  receiptId?: number | string
  resume?: boolean
}

export async function importQualityCorrections(payload: CorrectionImportPayload): Promise<any> {
  let content = payload.content ?? ''
  let filename = ''
  if (payload.file) {
    content = await payload.file.text()
    filename = payload.file.name
  }
  const response = await request('/api/quality_report/corrections/import', {
    method: 'POST',
    body: JSON.stringify({
      filename,
      content,
      rows: payload.rows,
      编制部门: payload.department,
      编制人: payload.uploadedBy,
      receipt_id: payload.receiptId,
      resume: payload.resume,
    }),
  })
  return await response.json()
}

export async function resumeQualityCorrectionReceipt(
  receiptId: number | string,
  payload: CorrectionImportPayload,
): Promise<any> {
  let content = payload.content ?? ''
  let filename = ''
  if (payload.file) {
    content = await payload.file.text()
    filename = payload.file.name
  }
  const response = await request(`/api/quality_report/receipts/${receiptId}/resume`, {
    method: 'POST',
    body: JSON.stringify({
      filename,
      content,
      rows: payload.rows,
      编制部门: payload.department,
      resume: true,
    }),
  })
  return await response.json()
}

export async function getCorrectionReceipt(receiptId: number | string): Promise<any> {
  const response = await request(`/api/quality_report/receipts/${receiptId}`)
  if (!response.ok) throw new Error('导入回执读取失败')
  return await response.json()
}

export async function downloadCorrectionReceipt(receiptId: number | string): Promise<void> {
  const response = await request(`/api/quality_report/receipts/${receiptId}/download`)
  if (!response.ok) throw new Error('导入回执下载失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `correction_receipt_${receiptId}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function signQualityCorrection(
  correctionId: number | string,
  signer = '',
): Promise<any> {
  const response = await request(`/api/quality_report/corrections/${correctionId}/sign`, {
    method: 'POST',
    body: JSON.stringify({ 签收人: signer, signer }),
  })
  return await response.json()
}

export async function getDistributionReadiness(meetingId: number | string): Promise<any> {
  const response = await request(`/api/review_meeting/${meetingId}/distribution-readiness`)
  if (!response.ok) throw new Error('分发核对信息读取失败')
  return await response.json()
}

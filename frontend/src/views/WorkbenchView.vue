<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button
          v-if="meta.key === 'quality_report'"
          class="btn primary"
          data-testid="open-correction-import"
          type="button"
          @click="openCorrectionImport"
        >
          更正收件 / 导入更正
        </button>
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <p v-if="noticeMessage" class="success-text" data-testid="action-message">{{ noticeMessage }}</p>

    <section
      v-if="meta.key === 'quality_report'"
      class="receipt-lookup"
      data-testid="receipt-lookup"
    >
      <label>
        <span>凭原回执继续：</span>
        <input
          v-model="receiptRef"
          data-testid="receipt-ref-input"
          placeholder="输入回执编号或 ID，例如 JC-0001"
          @keyup.enter="openReceiptByRef"
        />
      </label>
      <button class="btn" type="button" data-testid="open-receipt-by-ref" @click="openReceiptByRef">
        查看原回执
      </button>
      <button class="btn" type="button" data-testid="download-receipt-by-ref" @click="downloadReceiptByRef">
        下载回执
      </button>
    </section>

    <section
      v-if="meta.key === 'quality_report' && activeReceipt"
      class="receipt-card"
      :data-testid="`correction-receipt-${activeReceipt.id}`"
    >
      <div class="panel-head">
        <div>
          <h3>导入回执 {{ activeReceipt.receipt_no }}</h3>
          <p>{{ receiptSummary }}</p>
        </div>
        <div class="page-actions">
          <button
            class="btn primary"
            type="button"
            :data-testid="`download-receipt-${activeReceipt.id}`"
            @click="downloadReceiptFile(activeReceipt.id)"
          >
            下载导入回执
          </button>
          <button class="btn" type="button" data-testid="resume-correction" @click="resumeFromReceipt">
            用原回执补完
          </button>
        </div>
      </div>
      <table class="data-table receipt-table">
        <thead>
          <tr>
            <th>行号</th>
            <th>原简报编号</th>
            <th>状态</th>
            <th>说明</th>
            <th>签收人</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in activeReceipt.items"
            :key="String(item.id ?? item.row_no)"
            :data-testid="`receipt-row-${item.row_no}`"
            :data-valid="String(Boolean(item.valid))"
          >
            <td>{{ item.row_no }}</td>
            <td :data-testid="`receipt-original-code-${item.row_no}`">{{ item.原简报编号 || '未填编号' }}</td>
            <td>{{ item.status }}</td>
            <td :data-testid="`receipt-message-${item.row_no}`">{{ item.message || '—' }}</td>
            <td>{{ item.签收人 || '待指定' }}</td>
            <td>
              <button
                v-if="item.valid && item.status === '待签收'"
                class="link"
                type="button"
                :data-testid="`sign-correction-${item.id}`"
                @click="signReceiptCorrection(item)"
              >
                签收更正
              </button>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section
      v-if="meta.key === 'review_meeting'"
      class="readiness-panel"
      data-testid="distribution-panel"
    >
      <h3>主持人分发核对</h3>
      <article
        v-for="row in rows"
        :key="`readiness-${row.id}`"
        class="readiness-card"
        :data-testid="`distribution-readiness-${row.id}`"
      >
        <div class="panel-head">
          <strong>#{{ row.id }} {{ row.会议主题 }}</strong>
          <span :data-testid="`distribution-mode-${row.id}`">
            {{ readinessMap[row.id]?.mode || '尚未核对' }}
          </span>
        </div>
        <p v-if="readinessMap[row.id]" :data-testid="`distribution-headline-${row.id}`">
          {{ readinessMap[row.id].headline }}
        </p>
        <p v-else>点击“核对分发依据”，判断沿已签认议程分发还是先核对更正版。</p>
        <div class="page-actions">
          <button
            class="btn"
            type="button"
            :data-testid="`check-distribution-${row.id}`"
            @click="checkDistribution(row)"
          >
            核对分发依据
          </button>
          <button
            v-if="readinessMap[row.id]?.blocking_correction_ids?.length"
            class="btn primary"
            type="button"
            :data-testid="`verify-and-distribute-${row.id}`"
            @click="verifyAndDistribute(row)"
          >
            核对更正版后分发
          </button>
        </div>
      </article>
    </section>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showCorrectionModal" class="modal-backdrop" data-testid="correction-import-modal">
      <form class="modal" @submit.prevent="submitCorrectionImport">
        <h3>更正收件：导入一组学期更正</h3>
        <p class="modal-hint">CSV 需包含“原简报编号”；系统只按原编号和编制部门匹配，不会按相同学期更新另一个部门的简报。</p>
        <label class="create-field">
          <span>编制部门</span>
          <input
            v-model="correctionForm.department"
            data-testid="correction-department"
            placeholder="例如：教务处质量科"
          />
        </label>
        <label class="create-field">
          <span>原回执编号（传输中止后续传时填写）</span>
          <input
            v-model="correctionForm.receiptId"
            data-testid="correction-receipt-id"
            placeholder="例如：JC-0001"
          />
        </label>
        <label class="create-field">
          <span>更正文件（CSV/TSV/JSON）</span>
          <input
            type="file"
            accept=".csv,.tsv,.json,text/csv,text/plain"
            data-testid="correction-file"
            @change="onCorrectionFile"
          />
        </label>
        <label class="create-field">
          <span>或直接粘贴文件内容</span>
          <textarea
            v-model="correctionForm.content"
            class="correction-textarea"
            data-testid="correction-content"
            placeholder="原简报编号,编制部门,更正类型,突出问题,更正说明&#10;Q-16,教务处,实质性更正,...,..."
          ></textarea>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCorrectionModal = false">取消</button>
          <button
            class="btn primary"
            type="submit"
            data-testid="submit-correction-import"
            :disabled="importingCorrection"
          >
            {{ importingCorrection ? '导入中…' : '上传并生成回执' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  createEntry,
  downloadCorrectionReceipt,
  downloadEntries,
  getCorrectionReceipt,
  getDistributionReadiness,
  importQualityCorrections,
  listEntries,
  moduleMeta,
  resumeQualityCorrectionReceipt,
  runAction as applyAction,
  signQualityCorrection,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const route = useRoute()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const showCorrectionModal = ref(false)
const importingCorrection = ref(false)
const correctionForm = ref<{ department: string; receiptId: string; content: string; file: File | null }>({
  department: '',
  receiptId: '',
  content: '',
  file: null,
})
const activeReceipt = ref<any | null>(null)
const receiptRef = ref('')
const readinessMap = ref<Record<string, any>>({})
const receiptSummary = computed(() => {
  const receipt = activeReceipt.value
  if (!receipt) return ''
  return `共 ${receipt.total_rows} 行；有效 ${receipt.valid_count}；无效 ${receipt.invalid_count}；待签收 ${receipt.pending_sign_count}`
})
const doneStatus = computed(() =>
  meta.key === 'review_meeting' ? '已分发' : meta.statuses[meta.statuses.length - 1],
)
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === doneStatus.value).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

function openCorrectionImport() {
  correctionForm.value = { department: '', receiptId: '', content: '', file: null }
  errorMessage.value = ''
  noticeMessage.value = ''
  showCorrectionModal.value = true
}

function onCorrectionFile(event: Event) {
  const input = event.target as HTMLInputElement
  correctionForm.value.file = input.files?.[0] ?? null
}

async function submitCorrectionImport() {
  importingCorrection.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const receiptId = correctionForm.value.receiptId.trim()
    const payload = {
      file: correctionForm.value.file,
      content: correctionForm.value.content,
      department: correctionForm.value.department,
      receiptId: receiptId || undefined,
      resume: Boolean(receiptId),
    }
    const result = receiptId
      ? await resumeQualityCorrectionReceipt(receiptId, payload)
      : await importQualityCorrections(payload)
    if (!result.ok) throw new Error(result.message)
    activeReceipt.value = result.receipt
    noticeMessage.value = result.message
    showCorrectionModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '更正导入失败'
  } finally {
    importingCorrection.value = false
  }
}

async function refreshActiveReceipt() {
  if (!activeReceipt.value?.id) return
  activeReceipt.value = await getCorrectionReceipt(activeReceipt.value.id)
}

async function downloadReceiptFile(receiptId: number | string) {
  errorMessage.value = ''
  try {
    await downloadCorrectionReceipt(receiptId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回执下载失败'
  }
}

async function openReceiptByRef() {
  const refValue = receiptRef.value.trim()
  if (!refValue) {
    errorMessage.value = '请输入原回执编号'
    return
  }
  errorMessage.value = ''
  try {
    activeReceipt.value = await getCorrectionReceipt(refValue)
    noticeMessage.value = `已打开原回执 ${activeReceipt.value.receipt_no}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原回执读取失败'
  }
}

async function downloadReceiptByRef() {
  const refValue = receiptRef.value.trim()
  if (!refValue) {
    errorMessage.value = '请输入回执编号后再下载'
    return
  }
  await downloadReceiptFile(refValue)
}

function resumeFromReceipt() {
  if (!activeReceipt.value) return
  correctionForm.value = {
    department: activeReceipt.value.编制部门 ?? '',
    receiptId: String(activeReceipt.value.receipt_no ?? activeReceipt.value.id),
    content: '',
    file: null,
  }
  showCorrectionModal.value = true
}

async function signReceiptCorrection(item: EntryRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await signQualityCorrection(item.id)
    if (!result.ok) throw new Error(result.message)
    noticeMessage.value = result.message
    await refreshActiveReceipt()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '更正签收失败'
  }
}

async function checkDistribution(row: EntryRow) {
  errorMessage.value = ''
  try {
    const readiness = await getDistributionReadiness(row.id)
    if (!readiness.ok) throw new Error(readiness.message)
    readinessMap.value = { ...readinessMap.value, [String(row.id)]: readiness }
    noticeMessage.value = readiness.headline
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分发核对失败'
  }
}

async function verifyAndDistribute(row: EntryRow) {
  await runAction('核对更正版后分发', row)
  await loadReadiness()
}

async function loadReadiness() {
  if (meta.key !== 'review_meeting') return
  const entries = await Promise.all(
    rows.value.map(async (row) => {
      try {
        return [String(row.id), await getDistributionReadiness(row.id)] as const
      } catch {
        return null
      }
    }),
  )
  const next: Record<string, any> = {}
  for (const entry of entries) {
    if (entry && entry[1]?.ok) next[entry[0]] = entry[1]
  }
  readinessMap.value = next
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    noticeMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
    await loadReadiness()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(() => {
  void reload()
  if (route.query.panel === 'correction' && meta.key === 'quality_report') {
    openCorrectionImport()
  }
})
</script>

<style scoped>
.success-text {
  margin: 8px 0 16px;
  padding: 10px 14px;
  border: 1px solid #b7e4c7;
  border-radius: 8px;
  background: #f0fff4;
  color: #166534;
}

.receipt-card,
.receipt-lookup,
.readiness-panel {
  margin: 0 0 20px;
  padding: 16px;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: #f8fafc;
}

.receipt-lookup {
  display: flex;
  align-items: end;
  gap: 12px;
  flex-wrap: wrap;
}

.receipt-lookup label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 280px;
}

.receipt-lookup input {
  padding: 9px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
}

.readiness-card {
  padding: 12px;
  margin-top: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.panel-head h3,
.readiness-panel h3 {
  margin: 0 0 6px;
}

.receipt-table {
  margin-top: 12px;
  background: #fff;
}

.modal-hint {
  margin: 0 0 12px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.correction-textarea {
  min-height: 120px;
  padding: 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font: inherit;
  resize: vertical;
}
</style>

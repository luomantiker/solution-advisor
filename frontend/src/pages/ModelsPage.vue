<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import ActionIcon from '../components/ActionIcon.vue'

const items = ref<any[]>([])
const error = ref('')
const deleting = ref('')

function access(item:any) { if (item.access === 'OWNER') return '我上传'; if (item.access === 'ADMIN') return '管理权限'; return item.access === 'SHARED_WITH_MODEL' ? '已分享模型' : '仅分享结果' }
function time(value:string|undefined) { return value ? new Date(value).toLocaleString('zh-CN', { hour12:false }) : '时间未记录' }
function size(value:number|undefined) { if (!value) return '大小未记录'; if (value < 1024) return `${value} 字节`; if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 / 1024).toFixed(1)} MB` }
function opset(item:any) { const entries = item.profile?.summary?.opset_imports || []; return entries.length ? entries.map((entry:any) => `${entry.domain || 'ai.onnx'} ${entry.version}`).join(' / ') : 'Opset 未记录' }
function evaluationStatus(item:any) { if (!item.profile) return { label:'分析中', detail:'完成分析后可创建评估', tone:'warning' as const }; if (item.can_create_task) return { label:'可创建评估', detail:'模型分析已完成', tone:'success' as const }; return { label:'仅可查看', detail:'当前授权不支持创建评估', tone:'neutral' as const } }
async function load() { try { items.value = await api('/model-assets') } catch (cause) { error.value = cause instanceof Error ? cause.message : '模型列表加载失败。' } }
async function removeModel(item:any) { if (!confirm(`删除模型“${item.original_filename}”会导致所有相关的评测记录、报告和证据丢失。此操作无法恢复，是否继续？`)) return; deleting.value = item.id; error.value = ''; try { await api(`/model-assets/${item.id}`, { method:'DELETE' }); await load() } catch (cause) { error.value = cause instanceof Error ? cause.message : '模型删除失败。' } finally { deleting.value = '' } }
onMounted(load)
</script>

<template>
  <section class="page models-page">
    <PageHeader title="我的模型" description="查看您可使用的模型；分析完成后，可从模型详情创建评估并查看历史结果。" eyebrow="模型资产" />
    <p v-if="error" class="feedback error">{{ error }}</p>
    <SectionCard class="models-list-card" title="模型列表" description="每个模型均可查看详细分析、评估可选平台和历史评估；状态会提示下一步可执行的操作。">
      <template #actions>
        <button class="button-secondary" @click="load"><ActionIcon name="refresh" />刷新</button>
        <RouterLink class="button-primary" to="/upload"><ActionIcon name="upload" />上传模型</RouterLink>
      </template>
      <EmptyState v-if="!items.length" icon="▦" title="还没有模型" description="先上传一个 ONNX 模型。系统分析完成后，您就可以创建评估。">
        <RouterLink class="button-primary" to="/upload"><ActionIcon name="upload" />上传 ONNX</RouterLink>
      </EmptyState>
      <div v-else class="table-wrap">
        <table class="data-table models-data-table">
          <thead><tr><th>模型名称</th><th>模型大小</th><th>文件格式</th><th>版本信息</th><th>文件标识</th><th>上传时间</th><th>评估状态</th><th>权限</th><th class="table-actions">操作</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td class="model-name-cell"><strong>{{ item.original_filename }}</strong><small>ONNX 模型</small></td>
              <td>{{ size(item.size_bytes) }}</td>
              <td><span class="file-type-tag">ONNX</span></td>
              <td><small class="opset-label">{{ opset(item) }}</small></td>
              <td><small class="file-id-label">SHA256</small><code>{{ item.sha256.slice(0,16) }}…</code></td>
              <td><time :datetime="item.created_at">{{ time(item.created_at) }}</time></td>
              <td><StatusBadge :tone="evaluationStatus(item).tone">{{ evaluationStatus(item).label }}</StatusBadge><small>{{ evaluationStatus(item).detail }}</small></td>
              <td><span class="access-label">{{ access(item) }}</span></td>
              <td class="table-actions"><div class="model-row-actions">
                <RouterLink class="row-secondary-action" :to="`/models/${item.id}`"><ActionIcon name="view" />查看详情</RouterLink>
                <RouterLink v-if="item.profile && item.can_create_task" class="row-primary-action" :to="`/tasks/new?profile_id=${item.profile.id}`"><ActionIcon name="create" />创建评估</RouterLink>
                <button v-if="item.can_delete_model" class="row-danger-action" :disabled="deleting === item.id" @click="removeModel(item)"><ActionIcon name="delete" />{{ deleting === item.id ? '正在删除…' : '删除模型' }}</button>
              </div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </SectionCard>
  </section>
</template>

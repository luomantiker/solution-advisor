<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, controlApi } from '../api'
import PageHeader from '../components/PageHeader.vue'
import MetricCard from '../components/MetricCard.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import SidePanel from '../components/SidePanel.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import ActionIcon from '../components/ActionIcon.vue'

const me = ref<any>(), people = ref<any[]>([]), error = ref(''), notice = ref('')
const defaultPassword = 'Realthon_1'
const createOpen = ref(false), selected = ref<any>(), pendingAction = ref<'suspend'|'activate'|'reset'|'delete'|''>('')
const draft = ref({ login_name:'', display_name:'', role:'USER', initial_password:defaultPassword, test_only:false })
const filters = ref({ source:'ALL', role:'ALL', status:'ALL', keyword:'' })
const pager = ref({ total:0, page:1, page_size:10, page_count:1 })
const isSuperAdmin = computed(() => me.value?.role === 'SUPER_ADMIN')
const activeCount = computed(() => people.value.filter(item => item.status === 'ACTIVE').length)
const adminCount = computed(() => people.value.filter(item => item.role === 'ADMIN').length)
const userCount = computed(() => people.value.filter(item => item.role === 'USER').length)
function headers(revision?:number){ return { 'Content-Type':'application/json', ...(revision ? {'If-Match':String(revision)} : {}) } }
function statusTone(person:any){ return person.status === 'ACTIVE' ? 'success' : 'warning' }
function roleLabel(role:string){ return ({ SUPER_ADMIN:'超级管理员', ADMIN:'管理员', USER:'普通用户' } as Record<string,string>)[role] || role }
function sourceLabel(source:string){ return ({ SYSTEM_BUILTIN:'系统内建', INTERNAL_GENERATED:'内部生成', USER_REGISTERED:'用户注册', TEST_ONLY:'测试专用' } as Record<string,string>)[source] || '内部生成' }
const sourceHelp='系统内建：系统初始化保留账号；内部生成：管理员或超级管理员手动创建、且非测试标记的账号；测试专用：自动化测试或人工创建且标记为测试的账号；用户注册：为未来自主注册预留，目前未启用。'
function sourceTone(source:string){ return ({ SYSTEM_BUILTIN:'progress', INTERNAL_GENERATED:'neutral', USER_REGISTERED:'success', TEST_ONLY:'warning' } as Record<string,string>)[source] || 'neutral' }
function query(){ const value = new URLSearchParams({ page:String(pager.value.page), page_size:String(pager.value.page_size) }); if(filters.value.source !== 'ALL') value.set('source', filters.value.source); if(filters.value.role !== 'ALL') value.set('role', filters.value.role); if(filters.value.status !== 'ALL') value.set('status', filters.value.status); if(filters.value.keyword.trim()) value.set('keyword', filters.value.keyword.trim()); return value.toString() }
async function load(reset=false){ if(reset) pager.value.page=1; error.value=''; try { const [session, result] = await Promise.all([api('/auth/session'), controlApi(`/api/admin/people?${query()}`)]); me.value = session; people.value = result.items; pager.value = { total:result.total, page:result.page, page_size:result.page_size, page_count:result.page_count } } catch(e:any){ error.value=e.message } }
function applyFilters(){ void load(true) }
function setPage(page:number){ if(page < 1 || page > pager.value.page_count) return; pager.value.page = page; void load() }
function openCreate(){ draft.value={login_name:'',display_name:'',role:'USER',initial_password:defaultPassword,test_only:false}; createOpen.value=true; error.value='' }
async function create(){ error.value=''; notice.value=''; try { await controlApi('/api/admin/people',{method:'POST',headers:headers(),body:JSON.stringify(draft.value)}); createOpen.value=false; notice.value='人员已创建并启用，可使用设置的初始密码直接登录。'; await load(true) } catch(e:any){error.value=e.message} }
function requestAction(person:any, action:'suspend'|'activate'|'reset'|'delete'){ selected.value=person; pendingAction.value=action }
async function confirmAction(){ if(!selected.value)return; const person=selected.value; try {
  if(pendingAction.value==='suspend') await controlApi(`/api/admin/people/${person.id}/suspend`,{method:'POST',headers:headers(person.revision),body:JSON.stringify({reason:'人员管理停用'})})
  if(pendingAction.value==='activate') await controlApi(`/api/admin/people/${person.id}/activate`,{method:'POST',headers:headers(person.revision),body:JSON.stringify({reason:'人员管理启用'})})
  if(pendingAction.value==='reset') await controlApi(`/api/admin/people/${person.id}/password-reset`,{method:'POST',headers:headers(person.revision),body:JSON.stringify({initial_password:defaultPassword,reason:'人员管理重置'})})
  if(pendingAction.value==='delete') await controlApi(`/api/admin/people/${person.id}`,{method:'DELETE',headers:headers(person.revision)})
  notice.value=({suspend:'账号已停用，现有会话已撤销。',activate:'账号已启用。',reset:'密码已重置为默认初始密码，现有会话已撤销。',delete:'人员及其仅归属的模型、评测、报告与制品引用已清理；平台治理主体已转移至当前超级管理员。'} as Record<string,string>)[pendingAction.value]
  pendingAction.value=''; selected.value=undefined; await load()
}catch(e:any){error.value=e.message;pendingAction.value=''} }
function actionTitle(){ return ({suspend:'停用人员',activate:'启用人员',reset:'重置密码',delete:'删除人员与归属资源'} as Record<string,string>)[pendingAction.value] || '' }
function actionDescription(){ const name=selected.value?.display_name||'该人员'; return ({suspend:`停用后，${name} 的所有本地会话将立即失效。`,activate:`将重新启用 ${name} 的账号。`,reset:`将把 ${name} 的密码重置为默认初始密码，并撤销其现有会话。`,delete:`将永久删除 ${name} 的本地账号及仅归属的模型、评测、报告和制品引用；平台接入记录的治理主体会转交给当前超级管理员。此操作无法恢复。`} as Record<string,string>)[pendingAction.value] || '' }
onMounted(()=>void load())
</script>

<template>
  <section class="page people-page">
    <PageHeader title="人员管理" description="按来源、角色和启用状态管理当前权限范围内的账号；所有操作由后端授权与审计。" eyebrow="治理控制台" />
    <p v-if="notice" class="feedback success-feedback">{{notice}}</p><p v-if="error" class="feedback error">{{error}}</p>
    <div class="metric-grid people-metrics"><MetricCard icon="♙" label="筛选结果" :value="pager.total" description="符合当前筛选条件的人员" /><MetricCard icon="●" label="本页已启用" :value="activeCount" description="当前页状态为 ACTIVE 的人员" tone="success" /><MetricCard v-if="isSuperAdmin" icon="◇" label="本页管理员" :value="adminCount" description="不含超级管理员" tone="progress" /><MetricCard icon="◌" label="本页普通用户" :value="userCount" description="可创建评估和查看自身资源" /></div>
    <SectionCard title="人员列表" :description="(isSuperAdmin?'超级管理员可管理管理员与普通用户。':'管理员仅能查看和管理普通用户。') + sourceHelp"><template #actions><button type="button" class="button-secondary" @click="load"><ActionIcon name="refresh"/>刷新</button><button class="button-primary" @click="openCreate"><ActionIcon name="create"/>新增人员</button></template>
      <form class="people-filter-bar" @submit.prevent="applyFilters"><label>人员来源<select v-model="filters.source" @change="applyFilters"><option value="ALL">全部来源</option><option value="SYSTEM_BUILTIN">系统内建</option><option value="INTERNAL_GENERATED">内部生成</option><option value="USER_REGISTERED">用户注册</option><option value="TEST_ONLY">测试专用</option></select></label><label>角色<select v-model="filters.role" @change="applyFilters"><option value="ALL">全部角色</option><option value="SUPER_ADMIN">超级管理员</option><option value="ADMIN">管理员</option><option value="USER">普通用户</option></select></label><label>账号状态<select v-model="filters.status" @change="applyFilters"><option value="ALL">全部状态</option><option value="ACTIVE">已启用</option><option value="SUSPENDED">已停用</option></select></label><label class="people-keyword">名称 / 账号<input v-model="filters.keyword" placeholder="输入名称或登录账号"><button class="button-secondary" type="submit"><ActionIcon name="view"/>筛选</button></label><button class="filter-reset" type="button" @click="filters={source:'ALL',role:'ALL',status:'ALL',keyword:''};applyFilters()">清除条件</button></form>
      <EmptyState v-if="!people.length" icon="♙" title="暂无符合条件的人员" description="请调整筛选条件，或通过右上角“新增人员”创建当前权限范围内的账号。" />
      <div v-else class="table-wrap"><table class="data-table"><thead><tr><th>名称 / 账号</th><th>人员来源</th><th>角色</th><th>状态</th><th>最近活动</th><th>更新时间</th><th class="table-actions">操作</th></tr></thead><tbody><tr v-for="person in people" :key="person.id"><td><strong>{{person.display_name}}</strong><small>{{person.login_name||person.id}}</small></td><td><StatusBadge :tone="sourceTone(person.person_source)">{{sourceLabel(person.person_source)}}</StatusBadge></td><td><StatusBadge :tone="person.role==='ADMIN'?'progress':'neutral'">{{roleLabel(person.role)}}</StatusBadge></td><td><StatusBadge :tone="statusTone(person)">{{person.status==='ACTIVE'?'已启用':'已停用'}}</StatusBadge></td><td>{{person.last_login_at||'从未登录'}}</td><td>{{person.updated_at||'未记录'}}</td><td class="table-actions"><div class="table-action-group"><button v-if="person.status!=='SUSPENDED'&&person.id!==me?.subject" class="row-danger-action" type="button" @click="requestAction(person,'suspend')"><ActionIcon name="lock"/>停用</button><button v-if="person.status==='SUSPENDED'" class="row-secondary-action" type="button" @click="requestAction(person,'activate')"><ActionIcon name="unlock"/>启用</button><button v-if="person.id!==me?.subject" class="row-secondary-action" type="button" @click="requestAction(person,'reset')"><ActionIcon name="edit"/>重置密码</button><button v-if="isSuperAdmin&&person.id!==me?.subject&&person.role!=='SUPER_ADMIN'" class="row-danger-action" type="button" @click="requestAction(person,'delete')"><ActionIcon name="delete"/>删除</button></div></td></tr></tbody></table></div>
      <footer v-if="pager.total" class="people-pagination"><span>共 {{pager.total}} 人</span><label>每页<select v-model.number="pager.page_size" @change="applyFilters"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select> 条</label><div><button class="button-secondary" :disabled="pager.page<=1" @click="setPage(pager.page-1)">上一页</button><strong>{{pager.page}} / {{pager.page_count}}</strong><button class="button-secondary" :disabled="pager.page>=pager.page_count" @click="setPage(pager.page+1)">下一页</button></div></footer>
    </SectionCard>
    <SidePanel :open="createOpen" title="新增人员" @close="createOpen=false"><p class="panel-intro">新建账号默认归类为“内部生成”，会直接启用；默认初始密码为 <code>Realthon_1</code>，用户可后续自行修改。</p><form class="form-grid" @submit.prevent="create"><label>登录名<input v-model="draft.login_name" required autocomplete="off"></label><label>显示名称<input v-model="draft.display_name" required></label><label>角色<select v-model="draft.role"><option value="USER">普通用户</option><option v-if="isSuperAdmin" value="ADMIN">管理员</option></select></label><label>初始密码<input v-model="draft.initial_password" autocomplete="new-password"></label><label class="checkbox-control"><input v-model="draft.test_only" type="checkbox"> 标记为测试专用账号</label><p class="muted">测试专用用于自动化、验收或演示账号，可在列表中单独筛选；配额和能力范围尚未形成可执行统一策略，因此本轮不开放配置。</p><button class="button-primary"><ActionIcon name="create"/>创建并启用</button></form></SidePanel>
    <ConfirmDialog :open="Boolean(pendingAction)" :title="actionTitle()" :description="actionDescription()" :confirm-label="pendingAction==='reset'?'确认重置':'确认执行'" @cancel="pendingAction=''" @confirm="confirmAction" />
  </section>
</template>

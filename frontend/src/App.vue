<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, localLogin, saveAccessToken } from './api'
import { HELP_VERSION, helpSections } from './help'
import AppShell from './components/AppShell.vue'
import SidebarIcon from './components/SidebarIcon.vue'
import ActionIcon from './components/ActionIcon.vue'

type LoginOptions = { local_login_enabled: boolean, enterprise_sso_enabled: boolean }
const signedIn = ref(false), principal = ref<any>()
const username = ref('superadmin'), password = ref(''), ssoToken = ref(''), error = ref('')
const options = ref<LoginOptions>({ local_login_enabled: false, enterprise_sso_enabled: false })
const passwordChangeCompleted = ref(false)
const sidebarCollapsed = ref(false), helpOpen = ref(false), notificationOpen = ref(false)
const notifications = ref<any[]>([]), notificationsLoading = ref(false), notificationsError = ref('')
const notificationFilter = ref<'all' | 'evaluation' | 'platform' | 'account'>('all')
const route = useRoute(), router = useRouter()
const isAdmin = computed(() => ['ADMIN', 'SUPER_ADMIN'].includes(principal.value?.role))
const isSuperAdmin = computed(() => principal.value?.role === 'SUPER_ADMIN')
const visibleHelp = computed(() => helpSections(principal.value?.role, route.path))
const principalInitial = computed(() => String(principal.value?.display_name || principal.value?.subject || '我').trim().slice(0, 1).toUpperCase())
const pageHeader = computed(() => {
  if (!signedIn.value) return { eyebrow: 'Solution Advisor', title: '登录', description: '登录后，您将看到自己有权使用的模型、评估和报告。' }
  if (route.path === '/') return { eyebrow: '首页', title: '信息概览', description: '快速查看正在执行的评估、最近结果、模型和可下载报告。' }
  if (route.path === '/upload') return { eyebrow: '我的模型', title: '上传模型', description: '选择 ONNX 模型后，系统会自动完成分析，为后续评估做好准备。' }
  if (route.path === '/models') return { eyebrow: '模型资产', title: '模型评估', description: '集中查看模型、分析是否完成，以及每个模型的历史评估。' }
  if (route.path.startsWith('/models/')) return { eyebrow: '模型资产', title: '模型详情', description: '查看模型分析、可选择的平台和本模型已经完成或正在执行的评估。' }
  if (route.path === '/tasks/new') return { eyebrow: '受控评估', title: '创建评估', description: '依次选择模型和目标平台，系统会自动安排后续执行。' }
  if (route.path.startsWith('/flows/')) return { eyebrow: '真实评估', title: '评估流程详情', description: '查看这次评估的进度、阶段结果、证据、网页报告和 PDF。' }
  if (route.path.startsWith('/tasks/')) return { eyebrow: '历史评估', title: '评估详情', description: '查看历史评估的结果、执行进度和可下载报告。' }
  if (route.path === '/reports') return { eyebrow: '评估报告', title: '评估报告', description: '集中查看自己可访问的评估报告，并按需要下载 PDF。' }
  if (route.path === '/people') return { eyebrow: '治理控制台', title: '人员管理', description: '创建、启用或调整您有权管理的账号与角色。' }
  if (route.path === '/system-settings') return { eyebrow: '系统治理', title: '系统设置', description: '管理员可备份和恢复平台配置；全局策略仅超级管理员可修改。' }
  if (route.path === '/platform-command-template-guide') return { eyebrow: '平台管理', title: '系统授权占位符', description: '了解平台接入规则中可以安全使用的系统变量。' }
  if (route.path === '/admin') return { eyebrow: '平台与执行资源', title: '平台管理', description: '查看平台接入进度、已发布平台和当前可用的执行资源。' }
  return { eyebrow: 'Solution Advisor', title: '工作区', description: '查看当前账号可访问的业务信息。' }
})

async function loadSession() {
  try { principal.value = await api('/auth/session'); signedIn.value = true; void loadNotifications() }
  catch { saveAccessToken(''); signedIn.value = false; principal.value = undefined; notifications.value = [] }
}
async function loadOptions() {
  try { options.value = await api('/auth/options') as LoginOptions }
  catch { error.value = '登录方式配置暂不可用，请稍后重试。' }
}
async function signInLocal() {
  error.value = ''
  try { await localLogin(username.value, password.value); saveAccessToken(''); password.value = ''; await loadSession() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '登录未完成。' }
}
async function saveSsoSession() {
  error.value = ''
  const value = ssoToken.value.trim()
  if (!value) { error.value = '请输入企业 SSO 签发的令牌。'; return }
  saveAccessToken(value)
  await loadSession()
  if (!signedIn.value) error.value = '企业 SSO 身份验证失败，请检查令牌或联系管理员。'
  else ssoToken.value = ''
}
async function clearSession() { try { await api('/auth/local/logout', { method: 'POST' }) } catch {} saveAccessToken(''); signedIn.value = false; principal.value = undefined; ssoToken.value = ''; notifications.value = []; notificationFilter.value = 'all'; helpOpen.value = false; notificationOpen.value = false }
async function finishPasswordChange(){ passwordChangeCompleted.value=false; await clearSession() }
async function changeInitialPassword() {
  const current = prompt('请输入当前初始密码'); const next = prompt('请输入新密码')
  if (!current || !next) return
  try { await api('/auth/local/password/change', { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ current_password: current, new_password: next }) }); passwordChangeCompleted.value=true }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '密码修改未完成。' }
}
function notificationTitle(item: any) {
  return ({ account: '账号通知', evaluation: '评估通知', platform: '平台通知' } as Record<string, string>)[String(item?.kind)] || '业务通知'
}
const notificationDimensions = computed(() => ([
  { kind: 'evaluation', title: '评估', icon: 'model' as const },
  { kind: 'platform', title: '平台治理', icon: 'platform' as const },
  { kind: 'account', title: '账号与系统', icon: 'people' as const },
].map((dimension) => {
  const items = notifications.value.filter((item) => item.kind === dimension.kind)
  return { ...dimension, total: items.length, unread: items.filter((item) => !item.read).length }
})))
const filteredNotifications = computed(() => notificationFilter.value === 'all'
  ? notifications.value
  : notifications.value.filter((item) => item.kind === notificationFilter.value))
const unreadNotificationCount = computed(() => notifications.value.filter((item) => !item.read).length)
function notificationTone(kind: string) { return ['evaluation', 'platform', 'account'].includes(kind) ? kind : 'account' }
function notificationTime(value: string | undefined) {
  if (!value) return '时间未记录'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}
async function loadNotifications() {
  notificationsError.value = ''
  notificationsLoading.value = true
  try { notifications.value = await api('/auth/notifications') as any[] }
  catch { notificationsError.value = '通知暂不可读取，请稍后重试。' }
  finally { notificationsLoading.value = false }
}
async function openNotifications() {
  notificationOpen.value = !notificationOpen.value
  helpOpen.value = false
  if (!notificationOpen.value || notificationsLoading.value) return
  await loadNotifications()
}
async function markAllNotificationsRead() {
  if (!unreadNotificationCount.value) return
  try { await api('/auth/notifications/read-all', { method: 'POST' }); await loadNotifications() }
  catch { notificationsError.value = '标记已读未完成，请稍后重试。' }
}
async function clearAllNotifications() {
  if (!notifications.value.length || !confirm('确定清空当前通知列表吗？这不会删除评估、审计或平台业务记录。')) return
  try { await api('/auth/notifications', { method: 'DELETE' }); notificationFilter.value = 'all'; await loadNotifications() }
  catch { notificationsError.value = '清空通知未完成，请稍后重试。' }
}
async function markNotificationRead(item: any) {
  if (item.read) return
  try { await api(`/auth/notifications/${encodeURIComponent(item.id)}/read`, { method: 'POST' }); await loadNotifications() }
  catch { notificationsError.value = '标记已读未完成，请稍后重试。' }
}
async function deleteNotification(item: any) {
  try { await api(`/auth/notifications/${encodeURIComponent(item.id)}`, { method: 'DELETE' }); await loadNotifications() }
  catch { notificationsError.value = '删除通知未完成，请稍后重试。' }
}
function openHelp() { helpOpen.value = !helpOpen.value; notificationOpen.value = false }
watch([signedIn, () => route.path, () => principal.value?.role], () => {
  if (!signedIn.value) return
  if ((route.path === '/people' && !isAdmin.value) || (route.path === '/admin' && !isAdmin.value) || (route.path === '/system-settings' && !isAdmin.value)) void router.replace('/')
})
onMounted(async () => { await Promise.all([loadOptions(), loadSession()]) })
</script>

<template>
  <main v-if="!signedIn" class="login-portal">
    <section class="login-portal-brand"><img src="./assets/realthon-logo-mark.png" alt="Realthon 标识"><div><strong>Solution Advisor</strong><small>AI 多芯片智能方案顾问</small></div></section>
    <section class="login-portal-card"><p class="eyebrow">欢迎使用</p><h1>登录 AI 智能方案顾问</h1><p>使用已授权的本地账号或企业 SSO 登录，进入模型评估、评测报告与平台管理工作区。</p><form v-if="options.local_login_enabled" @submit.prevent="signInLocal"><label>用户名<input v-model="username" autocomplete="username" required></label><label>密码<input v-model="password" type="password" autocomplete="current-password" required></label><button class="button-primary">登录</button></form><details v-if="options.enterprise_sso_enabled"><summary>使用企业 SSO 登录</summary><p>请输入企业身份系统签发的访问令牌；系统只从账号库读取角色。</p><input v-model="ssoToken" type="password" autocomplete="off" placeholder="企业 SSO 访问令牌"><button @click="saveSsoSession">使用 SSO 身份</button></details><p v-if="!options.local_login_enabled&&!options.enterprise_sso_enabled" class="login-unavailable">当前部署未启用可用登录方式，请联系部署管理员配置本地账号或企业 SSO。</p><p v-if="error" class="error">{{ error }}</p></section>
    <footer>Realthon · Solution Advisor</footer>
  </main>
  <AppShell v-else :collapsed="sidebarCollapsed">
    <template #sidebar>
      <div class="brand" :title="sidebarCollapsed ? 'Realthon' : undefined">
        <img src="./assets/realthon-logo-mark.png" alt="Realthon 标识" class="brand-logo">
        <div v-if="!sidebarCollapsed" class="brand-copy"><strong>Solution Advisor</strong><small>AI 多芯片智能方案顾问</small></div>
      </div>
      <nav class="sidebar-nav" aria-label="业务导航">
        <RouterLink to="/" title="首页"><SidebarIcon name="home" /><b v-if="!sidebarCollapsed">首页</b></RouterLink>
        <RouterLink to="/models" title="模型评估"><SidebarIcon name="model" /><b v-if="!sidebarCollapsed">模型评估</b></RouterLink>
        <RouterLink to="/reports" title="评估报告"><SidebarIcon name="report" /><b v-if="!sidebarCollapsed">评估报告</b></RouterLink>
        <RouterLink v-if="isAdmin" to="/admin" title="平台管理"><SidebarIcon name="platform" /><b v-if="!sidebarCollapsed">平台管理</b></RouterLink>
        <RouterLink v-if="isAdmin" to="/people" title="人员管理"><SidebarIcon name="people" /><b v-if="!sidebarCollapsed">人员管理</b></RouterLink>
        <RouterLink v-if="isAdmin" to="/system-settings" title="系统设置"><SidebarIcon name="settings" /><b v-if="!sidebarCollapsed">系统设置</b></RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <button type="button" class="sidebar-tool sidebar-notification-tool" title="通知消息" aria-label="通知消息" @click="openNotifications"><SidebarIcon name="notification" /><b v-if="!sidebarCollapsed">通知消息</b><em v-if="!sidebarCollapsed && unreadNotificationCount" class="sidebar-notification-count">{{ unreadNotificationCount > 99 ? '99+' : unreadNotificationCount }}</em></button>
        <button type="button" class="sidebar-tool" title="帮助" aria-label="帮助" @click="openHelp"><SidebarIcon name="help" /><b v-if="!sidebarCollapsed">帮助</b></button>
        <button type="button" class="sidebar-tool sidebar-collapse" :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" @click="sidebarCollapsed=!sidebarCollapsed"><SidebarIcon name="collapse" /><b v-if="!sidebarCollapsed">收起</b></button>
      </div>
    </template>
    <template #header>
      <header class="content-header">
        <div><p class="eyebrow">{{ pageHeader.eyebrow }}</p><h1>{{ pageHeader.title }}</h1><p class="content-header-description">{{ pageHeader.description }}</p></div>
        <div v-if="signedIn" class="session"><span class="session-avatar" aria-hidden="true">{{ principalInitial }}</span><span class="session-user"><small>当前登录</small><strong>{{ principal?.display_name }}（{{ principal?.role }}）</strong></span><button v-if="principal?.auth_source==='LOCAL'" @click="changeInitialPassword">修改密码</button><button @click="clearSession">退出登录</button></div>
      </header>
    </template>
    <RouterView />
    <template #overlays><aside v-if="notificationOpen" class="aux-panel notification-panel" aria-label="业务通知"><header><div><h2>通知</h2><small>仅展示当前账号可访问的业务动态</small></div><button type="button" aria-label="关闭通知" @click="notificationOpen=false">×</button></header><p v-if="notificationsLoading" class="muted">正在读取已有业务事件…</p><template v-else><div class="notification-dimensions" aria-label="通知维度筛选"><button v-for="dimension in notificationDimensions" :key="dimension.kind" type="button" class="notification-dimension" :class="[`tone-${dimension.kind}`, { active: notificationFilter === dimension.kind }]" @click="notificationFilter = notificationFilter === dimension.kind ? 'all' : dimension.kind"><span class="notification-dimension-icon"><SidebarIcon :name="dimension.icon" /></span><span><b>{{ dimension.title }}</b><small>{{ dimension.total }} 条 · 未读 {{ dimension.unread }}</small></span></button></div><div class="notification-toolbar"><span>共 {{ notifications.length }} 条{{ unreadNotificationCount ? `，未读 ${unreadNotificationCount} 条` : '' }}</span><div><button type="button" class="icon-action-button" title="全部标记为已读" aria-label="全部标记为已读" :disabled="!unreadNotificationCount" @click="markAllNotificationsRead"><ActionIcon name="check" /></button><button type="button" class="icon-action-button danger" title="清空通知列表" aria-label="清空通知列表" :disabled="!notifications.length" @click="clearAllNotifications"><ActionIcon name="clear" /></button></div></div><p v-if="notificationsError" class="error">{{ notificationsError }}</p><p v-else-if="!notifications.length" class="muted notification-empty">暂无可显示的业务通知。</p><p v-else-if="!filteredNotifications.length" class="muted notification-empty">此维度暂无通知。</p><ul v-else class="notification-list"><li v-for="item in filteredNotifications" :key="item.id" :class="[`notification-${notificationTone(item.kind)}`, { unread: !item.read }]"><span class="notification-marker" aria-hidden="true"></span><div class="notification-item-content"><div class="notification-item-title"><strong>{{ notificationTitle(item) }}</strong><span v-if="!item.read" class="notification-unread-label">未读</span></div><span>{{ item.summary || item.action }}</span><small>{{ notificationTime(item.created_at) }}</small></div><div class="notification-item-actions"><button v-if="!item.read" type="button" class="icon-action-button" title="标记为已读" aria-label="标记为已读" @click="markNotificationRead(item)"><ActionIcon name="check" /></button><button type="button" class="icon-action-button danger" title="删除通知" aria-label="删除通知" @click="deleteNotification(item)"><ActionIcon name="delete" /></button></div></li></ul></template></aside>
    <aside v-if="helpOpen" class="aux-panel help-panel" aria-label="上下文帮助"><header><div><h2>帮助</h2><small>{{ HELP_VERSION }}</small></div><button type="button" aria-label="关闭帮助" @click="helpOpen=false">×</button></header><section v-for="section in visibleHelp" :key="section.title"><h3>{{ section.title }}</h3><ul><li v-for="item in section.items" :key="item">{{ item }}</li></ul></section></aside></template>
    <div v-if="passwordChangeCompleted" class="modal-backdrop" role="presentation"><section class="modal card" role="dialog" aria-modal="true" aria-labelledby="password-change-completed"><h2 id="password-change-completed">密码修改成功</h2><p>为保护账号安全，当前会话已失效。请使用新密码重新登录。</p><button autofocus @click="finishPasswordChange">确定</button></section></div>
  </AppShell>
</template>

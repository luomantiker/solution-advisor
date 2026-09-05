import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import UploadPage from './pages/UploadPage.vue'
import EvaluationWorkbenchPage from './pages/EvaluationWorkbenchPage.vue'
import ReportsPage from './pages/ReportsPage.vue'
import ModelsPage from './pages/ModelsPage.vue'
import ModelDetailPage from './pages/ModelDetailPage.vue'
import TaskCreatePage from './pages/TaskCreatePage.vue'
import TaskDetailPage from './pages/TaskDetailPage.vue'
import EvaluationFlowDetailPage from './pages/EvaluationFlowDetailPage.vue'
import AdminPage from './pages/AdminPage.vue'
import PlatformCommandTemplateGuidePage from './pages/PlatformCommandTemplateGuidePage.vue'
import PeoplePage from './pages/PeoplePage.vue'
import SystemSettingsPage from './pages/SystemSettingsPage.vue'
import PlatformBindingsPage from './pages/PlatformBindingsPage.vue'
import './style.css'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: EvaluationWorkbenchPage }, { path: '/upload', component: UploadPage }, { path: '/models', component: ModelsPage },
  { path: '/models/:assetId', component: ModelDetailPage, props: true },
  { path: '/tasks/new', component: TaskCreatePage }, { path: '/flows/:flowId', component: EvaluationFlowDetailPage, props: true },
  { path: '/tasks/:flowId(flow_.*)', redirect: to => `/flows/${String(to.params.flowId)}` },
  { path: '/tasks/:taskId', component: TaskDetailPage, props: true },
  { path: '/reports', component: ReportsPage },
  { path: '/admin', component: AdminPage },
  { path: '/people', component: PeoplePage },
  { path: '/system-settings', component: SystemSettingsPage },
  { path: '/platform-bindings', component: PlatformBindingsPage },
  { path: '/platform-command-template-guide', component: PlatformCommandTemplateGuidePage },
] })
createApp(App).use(router).mount('#app')

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, controlApi } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import ActionIcon from '../components/ActionIcon.vue'

const deletionEnabled=ref(false), policy=ref<any>(), loaded=ref(false), saving=ref(false), message=ref(''), error=ref('')
const principal=ref<any>(), catalogs=ref<any[]>([]), selectedCatalogIds=ref<string[]>([])
const exporting=ref(false), importing=ref(false), backupFile=ref<File|null>(null), backupNotice=ref('')
const isSuperAdmin=computed(()=>principal.value?.role==='SUPER_ADMIN')
const hasPolicyChange=computed(()=>Boolean(policy.value?.extensions?.some((item:any)=>item.enabled!==item.initialEnabled)))
async function load(){
  error.value='';message.value=''
  try{
    principal.value=await api('/auth/session')
    catalogs.value=(await controlApi('/api/admin/platform-catalogs') as any[]).filter((item:any)=>item.state==='AVAILABLE')
    if(isSuperAdmin.value){
      const [settings, analysis]:any=await Promise.all([
        controlApi('/api/admin/system-settings'), controlApi('/api/admin/system-settings/onnx-analysis-policy'),
      ])
      deletionEnabled.value=!!settings.allow_evaluated_model_deletion
      policy.value={...analysis,extensions:(analysis.extensions||[]).map((item:any)=>({...item,initialEnabled:item.enabled}))}
    }
    loaded.value=true
  }catch(cause){error.value=cause instanceof Error?cause.message:'系统设置加载失败。'}
}
function toggleCatalog(id:string){selectedCatalogIds.value=selectedCatalogIds.value.includes(id)?selectedCatalogIds.value.filter(item=>item!==id):[...selectedCatalogIds.value,id]}
function selectBackupFile(event:Event){backupFile.value=(event.target as HTMLInputElement).files?.[0]||null}
async function exportBackup(){
  if(!selectedCatalogIds.value.length){error.value='请先选择至少一个已发布平台。';return}
  exporting.value=true;error.value='';backupNotice.value=''
  try{
    const blob=await controlApi('/api/admin/platform-migrations/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({catalog_ids:selectedCatalogIds.value})}) as Blob
    const url=URL.createObjectURL(blob), anchor=document.createElement('a')
    anchor.href=url;anchor.download='solution-advisor-platform-configuration-backup.zip';anchor.click()
    backupNotice.value=`已导出 ${selectedCatalogIds.value.length} 个平台配置。导入目标环境后仍需安装固定 Runner，并建立健康 Binding 与 READY Worker。`
    window.setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(cause){error.value=cause instanceof Error?cause.message:'平台配置备份失败。'}finally{exporting.value=false}
}
async function importBackup(){
  if(!backupFile.value)return
  importing.value=true;error.value='';backupNotice.value=''
  try{
    const form=new FormData();form.set('archive',backupFile.value)
    const result:any=await controlApi('/api/admin/platform-migrations/import',{method:'POST',body:form})
    backupNotice.value=result.message;backupFile.value=null;await load()
  }catch(cause){error.value=cause instanceof Error?cause.message:'平台配置恢复失败。'}finally{importing.value=false}
}
async function saveDeletion(){
  saving.value=true;error.value='';message.value=''
  try{
    await controlApi('/api/admin/system-settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({allow_evaluated_model_deletion:deletionEnabled.value})})
    message.value=deletionEnabled.value?'已允许用户删除自己的已评测模型。':'已禁止删除已评测模型。'
  }catch(cause){error.value=cause instanceof Error?cause.message:'系统设置保存失败。'}finally{saving.value=false}
}
async function savePolicy(){
  if(!policy.value)return
  saving.value=true;error.value='';message.value=''
  try{
    const extensions=Object.fromEntries(policy.value.extensions.map((item:any)=>[item.id,Boolean(item.enabled)]))
    const next:any=await controlApi('/api/admin/system-settings/onnx-analysis-policy',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:policy.value.revision,extensions})})
    policy.value={...next,extensions:next.extensions.map((item:any)=>({...item,initialEnabled:item.enabled}))}
    message.value='ONNX 检测策略已发布。它只影响之后新建的分析任务，历史分析和报告保持不变。'
  }catch(cause){error.value=cause instanceof Error?cause.message:'ONNX 检测策略保存失败。'}finally{saving.value=false}
}
onMounted(load)
</script>

<template>
  <section class="page system-settings-page">
    <PageHeader eyebrow="系统治理" title="系统设置" :description="isSuperAdmin?'管理员可备份和恢复平台配置；全局策略仅超级管理员可修改。':'管理员可备份和恢复平台配置；全局策略由超级管理员管理。'"/>
    <p v-if="error" class="feedback error">{{error}}</p><p v-if="message" class="feedback success">{{message}}</p>
    <SectionCard title="平台配置备份与恢复" description="导出已发布平台的受控定义，在新部署中恢复平台类型、版本、镜像兼容约束和固定 Runner 规则。备份不包含 Host、Worker、用户数据、Artifact/Evidence 二进制或任何凭据。">
      <p class="backup-intro">恢复后仍须在目标 Host 安装匹配的固定 Runner，并依据本机镜像发现建立健康 Binding 与 READY Worker；备份不会迁移源主机的执行资源。</p>
      <p v-if="backupNotice" class="feedback success">{{backupNotice}}</p>
      <div v-if="loaded" class="table-wrap"><table class="data-table"><thead><tr><th>备份</th><th>平台 / 版本</th><th>固定 Runner</th><th>镜像兼容约束</th><th>状态</th></tr></thead><tbody><tr v-for="catalog in catalogs" :key="catalog.id"><td><input type="checkbox" :checked="selectedCatalogIds.includes(catalog.id)" @change="toggleCatalog(catalog.id)"></td><td><strong>{{catalog.display_name}}</strong><small>{{catalog.platform_id}} / {{catalog.version}}</small></td><td>{{catalog.runner?.version||'未登记'}}</td><td><small>{{catalog.image_lock?.digest||'未登记 digest'}}</small></td><td><span class="backup-state">已发布</span></td></tr></tbody></table></div>
      <div class="backup-import"><div><strong>恢复平台配置包</strong><small>只接受本系统导出的 ZIP；不会覆盖目标环境中内容不同的同平台同版本 Catalog。</small></div><input type="file" accept=".zip,application/zip" @change="selectBackupFile"><button class="button-secondary" :disabled="!backupFile||importing" @click="importBackup"><ActionIcon name="save"/>{{importing?'正在恢复…':'恢复配置包'}}</button></div>
      <template #actions><button class="button-primary" :disabled="!selectedCatalogIds.length||exporting" @click="exportBackup"><ActionIcon name="download"/>{{exporting?'正在备份…':'备份选中平台'}}</button></template>
    </SectionCard>
    <SectionCard v-if="isSuperAdmin" title="模型删除策略" description="控制普通用户是否可以删除自己的已评测模型。该操作会清除该用户关联的评估、报告和证据。">
      <div v-if="loaded" class="system-setting-row"><div><strong>允许删除被评测模型</strong><p>关闭时，模型和其评估记录只能保留查看；开启后，删除前会明确警告。共享模型仅在所有用户引用均移除后才删除 ONNX 文件。</p></div><label class="setting-switch"><input v-model="deletionEnabled" type="checkbox"><span>{{deletionEnabled?'已允许':'已禁止'}}</span></label></div>
      <template #actions><button class="button-primary" :disabled="!loaded||saving" @click="saveDeletion"><ActionIcon name="save"/>{{saving?'正在保存…':'保存删除策略'}}</button></template>
    </SectionCard>
    <SectionCard v-if="isSuperAdmin" class="analysis-policy-card" title="通用 ONNX 检测策略" description="基础检查始终执行；扩展检查按项启用。策略发布后仅影响新上传或重新分析的模型，历史 Profile、Flow 和报告不会被改写。">
      <div v-if="policy" class="analysis-policy-body">
        <article class="analysis-policy-base"><div class="policy-icon"><ActionIcon name="model"/></div><div><strong>{{policy.base_checks[0].name}}</strong><p>{{policy.base_checks[0].description}}</p></div><span class="policy-required">基础必选</span></article>
        <div class="analysis-policy-extensions"><h4>扩展检查</h4><p>可按部署需求独立开启或关闭；页面不接收脚本、命令、路径或 Docker 参数。</p><article v-for="item in policy.extensions" :key="item.id" class="analysis-policy-extension"><div><strong>{{item.name}}</strong><p>{{item.description}}</p></div><label class="setting-switch"><input v-model="item.enabled" type="checkbox"><span>{{item.enabled?'已启用':'未启用'}}</span></label></article></div>
        <p class="policy-version">当前策略版本：V{{policy.revision}}。每个分析任务都会冻结本次基础项与扩展项状态，以保证结果可追溯。</p>
      </div>
      <template #actions><button class="button-primary" :disabled="!loaded||saving||!hasPolicyChange" @click="savePolicy"><ActionIcon name="save"/>{{saving?'正在发布…':'发布检测策略'}}</button></template>
    </SectionCard>
  </section>
</template>

<style scoped>
.system-settings-page{display:grid;gap:18px}.system-setting-row,.analysis-policy-base,.analysis-policy-extension{display:flex;align-items:center;justify-content:space-between;gap:2rem;padding:.7rem 0}.system-setting-row strong,.analysis-policy-base strong,.analysis-policy-extension strong{color:#173b67;font-size:1rem}.system-setting-row p,.analysis-policy-base p,.analysis-policy-extension p{max-width:760px;margin:.38rem 0 0;color:#667085;line-height:1.6}.setting-switch{display:inline-flex;align-items:center;gap:.5rem;flex:none;color:#173b67;font-weight:750}.setting-switch input{width:18px;height:18px;accent-color:#1768dc}.analysis-policy-body{display:grid;gap:16px}.analysis-policy-base{padding:15px;border:1px solid #d8e8ff;border-radius:11px;background:#f7fbff;justify-content:flex-start}.policy-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:#e4f0ff;color:#1768dc}.policy-icon :deep(.action-icon){width:21px;height:21px}.policy-required{margin-left:auto;padding:5px 9px;border-radius:99px;background:#e3f8ea;color:#21874c;font-size:12px;font-weight:750;white-space:nowrap}.analysis-policy-extensions{display:grid;gap:0;border:1px solid #e1eaf4;border-radius:11px;padding:0 15px}.analysis-policy-extensions h4{margin:15px 0 0;color:#173b67}.analysis-policy-extensions>p{margin:5px 0;color:#71839a;font-size:13px}.analysis-policy-extension{border-top:1px solid #edf1f7}.policy-version{margin:0;color:#71839a;font-size:13px}.backup-intro{margin:0 0 12px;color:#667085;line-height:1.6}.backup-import{display:flex;align-items:center;gap:12px;margin-top:14px;padding:14px;border:1px dashed #bdd5f4;border-radius:10px;background:#f8fbff}.backup-import>div{display:grid;gap:3px;flex:1;color:#173b67}.backup-import small{color:#71839a}.backup-state{display:inline-flex;padding:4px 9px;border-radius:99px;background:#e3f8ea;color:#21874c;font-size:12px;font-weight:750}@media(max-width:640px){.system-setting-row,.analysis-policy-extension,.backup-import{align-items:flex-start;flex-direction:column;gap:.85rem}.analysis-policy-base{align-items:flex-start}.policy-required{margin-left:0}}
</style>

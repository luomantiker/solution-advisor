<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { controlApi } from '../api'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'

const agents = ref<any[]>([]), catalogs = ref<any[]>([]), images = ref<any[]>([]), boards = ref<any[]>([]), bindings = ref<any[]>([])
const error = ref(''), saving = ref(false)
const form = ref({ agent_id: '', catalog_id: '', host_image_id: '', board_id: '', capabilities: ['static_check'], max_concurrency: 1 })
const boardForm = ref({ agent_id: '', name: '', board_type: '', ip_address: '', port: 22, username: '', password: '' })
const selectedImages = computed(() => images.value.filter(item => item.agent_id === form.value.agent_id))
const selectedBoards = computed(() => boards.value.filter(item => item.agent_id === form.value.agent_id && item.status === 'READY'))
async function load() { try { [agents.value, catalogs.value, images.value, boards.value, bindings.value] = await Promise.all([
  controlApi('/api/admin/host-agents'), controlApi('/api/admin/platform-catalogs'), controlApi('/api/admin/host-images'), controlApi('/api/admin/boards'), controlApi('/api/admin/platform-bindings')]) as any } catch (cause:any) { error.value = cause.message || '读取绑定资源失败' } }
function changeAgent(){ form.value.host_image_id=''; form.value.board_id='' }
async function create(){ saving.value=true; error.value=''; try { await controlApi('/api/admin/platform-bindings', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...form.value, host_image_id:form.value.host_image_id || null, board_id:form.value.board_id || null}) }); await load() } catch(cause:any) { error.value=cause.message||'创建 Binding 失败' } finally { saving.value=false } }
async function createBoard(){ saving.value=true; error.value=''; try { await controlApi('/api/admin/boards', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(boardForm.value) }); boardForm.value={agent_id:'',name:'',board_type:'',ip_address:'',port:22,username:'',password:''}; await load() } catch(cause:any) { error.value=cause.message||'登记板卡失败' } finally { saving.value=false } }
async function testBoard(board:any){ try { await controlApi(`/api/admin/boards/${board.id}/test`, {method:'POST'}); await load() } catch(cause:any) { error.value=cause.message||'板卡预检失败' } }
onMounted(load)
</script>

<template>
  <section class="page governance-page">
    <PageHeader title="Platform Binding" eyebrow="平台与执行资源" description="将已识别的 HostAgent、已发布 Platform Catalog、受控镜像和已就绪板卡建立长期执行关系；成功后系统会自动准备 Worker。" />
    <p v-if="error" class="feedback error">{{ error }}</p>
    <SectionCard title="板卡" description="登记可用于评估的板卡。请直接填写 IP、端口和登录账号；密码以掩码输入，控制面不会保存或回显。"><form class="form-grid" @submit.prevent="createBoard"><label>所属 HostAgent<select v-model="boardForm.agent_id" required><option disabled value="">请选择 HostAgent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{agent.id}}</option></select></label><label>板卡名称<input v-model="boardForm.name" required placeholder="例如 s100-board-01"></label><label>板卡类型<input v-model="boardForm.board_type" required placeholder="例如 S100"></label><label>IP 地址<input v-model="boardForm.ip_address" required inputmode="decimal" placeholder="例如 192.168.1.100"></label><label>端口<input v-model.number="boardForm.port" required type="number" min="1" max="65535" placeholder="例如 22"></label><label>用户名<input v-model="boardForm.username" required autocomplete="username" placeholder="例如 root"></label><label>密码<input v-model="boardForm.password" required type="password" autocomplete="new-password" placeholder="请输入板卡登录密码"></label><button class="button-primary" :disabled="saving">登记板卡</button></form><EmptyState v-if="!boards.length" title="暂无已登记板卡" description="登记后先执行 HostAgent 在线预检，预检通过的板卡才可绑定到评估能力。" /><div v-else class="table-wrap"><table class="data-table"><thead><tr><th>板卡</th><th>HostAgent</th><th>连接</th><th>类型</th><th>状态</th><th>预检</th></tr></thead><tbody><tr v-for="board in boards" :key="board.id"><td>{{board.name}}</td><td>{{board.agent_id}}</td><td>{{board.username}}@{{board.ip_address}}:{{board.port}}</td><td>{{board.board_type}}</td><td><StatusBadge :tone="board.status==='READY'?'success':'warning'">{{board.status}}</StatusBadge></td><td><button class="button-secondary" @click="testBoard(board)">运行预检</button></td></tr></tbody></table></div></SectionCard>
    <SectionCard title="新建 Platform Binding" description="只能选择已发布 Catalog、已注册 HostAgent，以及该 Host 上已发现的镜像。板卡为可选项；选择时必须先通过预检。">
      <form class="form-grid" @submit.prevent="create">
        <label>HostAgent<select v-model="form.agent_id" required @change="changeAgent"><option disabled value="">请选择 HostAgent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{agent.id}}（{{agent.host_state}}）</option></select></label>
        <label>Platform Catalog<select v-model="form.catalog_id" required><option disabled value="">请选择已发布 Catalog</option><option v-for="catalog in catalogs.filter(x=>x.state==='AVAILABLE')" :key="catalog.id" :value="catalog.id">{{catalog.display_name}} · {{catalog.version}}</option></select></label>
        <label>实际工具链镜像<select v-model="form.host_image_id"><option value="">自动选择（仅一项或 digest 匹配）</option><option v-for="image in selectedImages" :key="image.id" :value="image.id">{{image.image_ref}}</option></select></label>
        <label>评估板卡<select v-model="form.board_id"><option value="">不绑定板卡（仅静态/编译能力）</option><option v-for="board in selectedBoards" :key="board.id" :value="board.id">{{board.name}} · {{board.board_type}}</option></select></label>
        <label>最大并发<input v-model.number="form.max_concurrency" type="number" min="1" max="32" required></label>
        <fieldset><legend>启用能力</legend><label><input v-model="form.capabilities" type="checkbox" value="static_check"> 静态检查</label><label><input v-model="form.capabilities" type="checkbox" value="compile"> 编译</label><label><input v-model="form.capabilities" type="checkbox" value="board_smoke"> 板端冒烟</label></fieldset>
        <button class="button-primary" :disabled="saving || !form.capabilities.length">{{saving?'正在创建…':'创建 Binding 并准备 Worker'}}</button>
      </form>
    </SectionCard>
    <SectionCard title="已有 Binding" description="每个 Binding 是一个 HostAgent 与一个 Catalog 版本的受控关系。"><EmptyState v-if="!bindings.length" title="暂无 Binding" description="创建 Binding 后，健康的 HostAgent 会自动获得 READY Worker。" /><div v-else class="table-wrap"><table class="data-table"><thead><tr><th>HostAgent</th><th>Catalog / 平台</th><th>板卡</th><th>状态</th><th>Worker</th><th>容量</th></tr></thead><tbody><tr v-for="binding in bindings" :key="binding.id"><td>{{binding.agent_id}}</td><td>{{binding.platform_id}}<small>{{binding.catalog_id}}</small></td><td>{{boards.find(x=>x.id===binding.board_id)?.name||'未绑定'}}</td><td><StatusBadge :tone="binding.state==='HEALTHY'?'success':'warning'">{{binding.state}}</StatusBadge></td><td>{{binding.ready_workers}} / {{binding.workers}}</td><td>{{binding.max_concurrency}}</td></tr></tbody></table></div></SectionCard>
  </section>
</template>

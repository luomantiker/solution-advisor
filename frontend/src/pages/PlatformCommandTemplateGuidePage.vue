<template>
<section>
  <div class="toolbar"><RouterLink to="/admin">返回管理控制台</RouterLink></div>
  <h2>系统授权占位符</h2>
  <article class="card">
    <p>本页用于填写 Candidate 的固定编译命令模板和固定板端验证命令模板。占位符只能由固定 Runner 在执行时替换；不是让接入人员填写服务器路径、凭据或任意命令参数。</p>
    <table>
      <thead><tr><th>占位符</th><th>适用模板</th><th>运行时含义</th></tr></thead>
      <tbody>
        <tr><td><code>{model}</code></td><td>编译、板端验证（必填）</td><td>系统为当前评估任务提供的受管模型文件。</td></tr>
        <tr><td><code>{profile_dir}</code></td><td>板端验证（可选）</td><td>系统为本次板端性能采集创建的受管 profile 输出目录。</td></tr>
      </tbody>
    </table>
    <h3>填写示例</h3>
    <pre><code>hb_compile --fast-perf --march nash-e --model {model}
hrt_model_exec perf --model_file {model} --profile_path {profile_dir}</code></pre>
    <h3>校验边界</h3>
    <p>两个模板都必须含有 <code>{model}</code>。程序名必须是允许的受控工具名；模板不接受 Shell 串联或重定向、Docker 参数、宿主机绝对路径、密码、令牌、密钥及未列出的占位符。保存后会递增 Candidate 修订，旧验证结果失效，需要重新验证。</p>
    <p>完整的接入步骤、规则继承与验证门禁见《平台接入与扩展手册》的“系统授权占位符与固定命令模板”一节。</p>
  </article>
</section>
</template>
